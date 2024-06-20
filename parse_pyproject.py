"""Module for parsing pyproject.toml files and converting them to Spack package.py files.
"""

from typing import Optional, List, Dict, Tuple, Union

import sys
import re
import requests
from packaging import requirements
from packaging import specifiers
from packaging import markers
import packaging.version as pv
import tomli  # type: ignore
import pyproject_metadata as py_metadata  # type: ignore , pylint: disable=import-error,
from spack import spec  # type: ignore , pylint: disable=import-error
import spack.parser  # type: ignore , pylint: disable=import-error
import spack.error  # type: ignore , pylint: disable=import-error
import spack.version as sv  # type: ignore , pylint: disable=import-error


TEST_PKG_PREFIX = "test-"
USE_TEST_PREFIX = True

USE_SPACK_PREFIX = True

################################################################################################################
# The following section contains utilities for converting python packaging requirements and markers
# to Spack dependencies and specs. The code is copied and adapted from Spack/Harmen Stoppels:
# https://github.com/spack/pypi-to-spack-package.

# TODO: document/comment this code
# TODO: check if everything works as expected

# these python versions are not supported anymore, so we shouldn't need to consider them
UNSUPPORTED_PYTHON = sv.VersionRange(
    sv.StandardVersion.typemin(), sv.StandardVersion.from_string("3.5")
)

NAME_REGEX = re.compile(r"[-_.]+")

LOCAL_SEPARATORS_REGEX = re.compile(r"[\._-]")

# TODO: these are the only known python versions?
KNOWN_PYTHON_VERSIONS = (
    (3, 6, 15),
    (3, 7, 17),
    (3, 8, 18),
    (3, 9, 18),
    (3, 10, 13),
    (3, 11, 7),
    (3, 12, 1),
    (3, 13, 0),
    (4, 0, 0),
)

evalled = dict()


def _normalized_name(name: str) -> str:
    return re.sub(NAME_REGEX, "-", name).lower()


def _acceptable_version(version: str) -> Optional[pv.Version]:
    """Try to parse version string using packaging."""
    try:
        v = pv.parse(version)
        # do not support post releases of prereleases etc.
        if v.pre and (v.post or v.dev or v.local):
            return None
        return v
    except pv.InvalidVersion:
        return None


class JsonVersionsLookup:
    """Class for retrieving available versions of package from PyPI JSON API.

    Caches past requests.
    """

    def __init__(self):
        self.cache: Dict[str, List[pv.Version]] = {}

    def _query(self, name: str) -> List[pv.Version]:
        """Call JSON API."""
        r = requests.get(
            f"https://pypi.org/simple/{name}/",
            headers={"Accept": "application/vnd.pypi.simple.v1+json"},
            timeout=10,
        )
        if r.status_code != 200:
            print(
                f"Json lookup error (pkg={name}): status code {r.status_code}",
                file=sys.stderr,
            )
            if r.status_code == 404:
                print(
                    f"Package {name} not found on PyPI...",
                    file=sys.stderr,
                )
            return []
        versions = r.json()["versions"]
        # parse and sort versions
        return sorted({vv for v in versions if (vv := _acceptable_version(v))})

    def _python_versions(self) -> List[pv.Version]:
        """Statically evaluate python versions."""
        return [
            pv.Version(f"{major}.{minor}.{patch}")
            for major, minor, patch in KNOWN_PYTHON_VERSIONS
        ]

    def __getitem__(self, name: str) -> List[pv.Version]:
        result = self.cache.get(name)
        if result is not None:
            return result
        if name == "python":
            result = self._python_versions()
        else:
            result = self._query(name)
        self.cache[name] = result
        return result


def _best_upperbound(
    curr: sv.StandardVersion, nxt: sv.StandardVersion
) -> sv.StandardVersion:
    """Return the most general upper bound that includes curr but not nxt. Invariant is that
    curr < nxt.

    Here, "most general" means the differentiation should happen as high as possible in the version specifier hierarchy.
    3.4.2.5,  3.4.5.1 -> 3.4.3 or 3.4.4, not 3.4.2.6
    """
    assert curr < nxt
    i = 0
    m = min(len(curr), len(nxt))
    # find the first level in the version specifier hierarchy where the two versions differ
    while i < m and curr.version[0][i] == nxt.version[0][i]:
        i += 1

    if i == len(curr) < len(nxt):
        # e.g. curr = 3.4, nxt = 3.4.5, i = 2
        release, _ = curr.version
        release += (
            0,
        )  # one zero should be enough 1.2 and 1.2.0 are not distinct in packaging.
        seperators = (".",) * (len(release) - 1) + ("",)
        as_str = ".".join(str(x) for x in release)
        return sv.StandardVersion(
            as_str, (tuple(release), (sv.common.FINAL,)), seperators
        )
    elif i == m:
        return curr  # include pre-release of curr
    else:
        return curr.up_to(i + 1)


def _best_lowerbound(
    prev: sv.StandardVersion, curr: sv.StandardVersion
) -> sv.StandardVersion:
    """Return the most general lower bound that includes curr but not prev. Invarint is that
    prev < curr.

    Counterpart to _best_upperbound()
    """
    i = 0
    m = min(len(curr), len(prev))
    while i < m and curr.version[0][i] == prev.version[0][i]:
        i += 1
    if i + 1 >= len(curr):
        return curr
    else:
        return curr.up_to(i + 1)


def _packaging_to_spack_version(v: pv.Version) -> sv.StandardVersion:
    # TODO: better epoch support.
    release = []
    prerelease = (sv.common.FINAL,)
    if v.epoch > 0:
        print(f"warning: epoch {v} isn't really supported", file=sys.stderr)
        release.append(v.epoch)
    release.extend(v.release)
    separators = ["."] * (len(release) - 1)

    if v.pre is not None:
        tp, num = v.pre
        if tp == "a":
            prerelease = (sv.common.ALPHA, num)
        elif tp == "b":
            prerelease = (sv.common.BETA, num)
        elif tp == "rc":
            prerelease = (sv.common.RC, num)
        separators.extend(("-", ""))

        if v.post or v.dev or v.local:
            print(f"warning: ignoring post / dev / local version {v}", file=sys.stderr)

    else:
        if v.post is not None:
            release.extend((sv.version_types.VersionStrComponent("post"), v.post))
            separators.extend((".", ""))
        if (
            v.dev is not None
        ):  # dev is actually pre-release like, spack makes it a post-release.
            release.extend((sv.version_types.VersionStrComponent("dev"), v.dev))
            separators.extend((".", ""))
        if v.local is not None:
            local_bits = [
                int(i) if i.isnumeric() else sv.version_types.VersionStrComponent(i)
                for i in LOCAL_SEPARATORS_REGEX.split(v.local)
            ]
            release.extend(local_bits)
            separators.append("-")
            separators.extend("." for _ in range(len(local_bits) - 1))

    separators.append("")

    # Reconstruct a string.
    string = ""
    for i, rel in enumerate(release):
        string += f"{rel}{separators[i]}"
    if v.pre:
        string += f"{sv.common.PRERELEASE_TO_STRING[prerelease[0]]}{prerelease[1]}"

    spack_version = sv.StandardVersion(
        string, (tuple(release), tuple(prerelease)), separators
    )

    return spack_version


def _condensed_version_list(
    _subset_of_versions: List[pv.Version], _all_versions: List[pv.Version]
) -> sv.VersionList:
    """Create a minimal, condensed list of version ranges equivalent to the given subset of all versions."""
    # Sort in Spack's order, which should in principle coincide with packaging's order, but may
    # not in unforseen edge cases.
    subset = sorted(_packaging_to_spack_version(v) for v in _subset_of_versions)
    all_versions = sorted(_packaging_to_spack_version(v) for v in _all_versions)

    # Find corresponding index
    i, j = all_versions.index(subset[0]) + 1, 1
    new_versions: List[sv.ClosedOpenRange] = []

    # If the first when entry corresponds to the first known version, use (-inf, ..] as lowerbound.
    if i == 1:
        lo = sv.StandardVersion.typemin()
    else:
        lo = _best_lowerbound(all_versions[i - 2], subset[0])

    while j < len(subset):
        if all_versions[i] != subset[j]:
            hi = _best_upperbound(subset[j - 1], all_versions[i])
            new_versions.append(sv.VersionRange(lo, hi))
            i = all_versions.index(subset[j])
            lo = _best_lowerbound(all_versions[i - 1], subset[j])
        i += 1
        j += 1

    # Similarly, if the last entry corresponds to the last known version,
    # assume the dependency continues to be used: [x, inf).
    if i == len(all_versions):
        hi = sv.StandardVersion.typemax()
    else:
        hi = _best_upperbound(subset[j - 1], all_versions[i])

    new_versions.append(sv.VersionRange(lo, hi))

    vlist = sv.VersionList(new_versions)

    return vlist


def _pkg_specifier_set_to_version_list(
    pkg: str, specifier_set: specifiers.SpecifierSet, version_lookup: JsonVersionsLookup
) -> sv.VersionList:
    """Convert the specifier set for a given package to an equivalent list of version ranges in spack."""
    # TODO: improve how & where the caching is done?
    key = (pkg, specifier_set)
    if key in evalled:
        return evalled[key]
    all_versions = version_lookup[pkg]
    matching = [s for s in all_versions if specifier_set.contains(s, prereleases=True)]
    result = (
        sv.VersionList()
        if not matching
        else _condensed_version_list(matching, all_versions)
    )
    evalled[key] = result
    return result


def _eval_python_version_marker(
    variable: str, op: str, value: str, version_lookup: JsonVersionsLookup
) -> Optional[sv.VersionList]:
    # TODO: there might be still some bug caused by python_version vs python_full_version
    # differences.
    # Also `in` and `not in` are allowed, but difficult to get right. They take the rhs as a
    # string and do string matching instead of version parsing... so we don't support them now.
    if op not in ("==", ">", ">=", "<", "<=", "!="):
        return None

    try:
        specifier = specifiers.SpecifierSet(f"{op}{value}")
    except specifiers.InvalidSpecifier:
        print(f"could not parse `{op}{value}` as specifier", file=sys.stderr)
        return None

    return _pkg_specifier_set_to_version_list("python", specifier, version_lookup)


def _simplify_python_constraint(versions: sv.VersionList) -> None:
    """Modifies a version list of python versions in place to remove redundant constraints
    implied by UNSUPPORTED_PYTHON."""
    # First delete everything implied by UNSUPPORTED_PYTHON
    vs = versions.versions
    while vs and vs[0].satisfies(UNSUPPORTED_PYTHON):
        del vs[0]

    if not vs:
        return

    # Remove any redundant lowerbound, e.g. @3.7:3.9 becomes @:3.9 if @:3.6 unsupported.
    union = UNSUPPORTED_PYTHON._union_if_not_disjoint(vs[0])
    if union:
        vs[0] = union


def _eval_constraint(
    node: tuple, version_lookup: JsonVersionsLookup
) -> Union[None, bool, List[spec.Spec]]:
    """Evaluate a environment marker (variable, operator, value).
    
    Returns:
        None: If constraint cannot be evaluated.
        True/False: If constraint is statically true or false.
        List of specs: Spack representation of the constraint(s).
    """
    # TODO: os_name, platform_machine, platform_release, platform_version, implementation_version

    # Operator
    variable, op, value = node

    # Flip the comparison if the value is on the left-hand side.
    if isinstance(variable, markers.Value) and isinstance(value, markers.Variable):
        flipped_op = {
            ">": "<",
            "<": ">",
            ">=": "<=",
            "<=": ">=",
            "==": "==",
            "!=": "!=",
            "~=": "~=",
        }.get(op.value)
        if flipped_op is None:
            print(f"do not know how to evaluate `{node}`", file=sys.stderr)
            return None
        variable, op, value = value, markers.Op(flipped_op), variable

    print(f"EVAL MARKER {variable.value} {op.value} '{value.value}'")

    # Statically evaluate implementation name, since all we support is cpython
    if variable.value == "implementation_name" or variable.value == "platform_python_implementation":
        if op.value == "==":
            return value.value.lower() == "cpython"
        elif op.value == "!=":
            return value.value.lower() != "cpython"
        return None

    platforms = ("linux", "cray", "darwin", "windows", "freebsd")

    if (variable.value == "platform_system" or variable.value == "sys_platform") and op.value in ("==", "!="):
        platform = value.value.lower()
        if platform == "win32":
            platform = "windows"
        elif platform == "linux2":
            platform = "linux"

        if platform in platforms:
            return [
                spec.Spec(f"platform={p}")
                for p in platforms
                if (p != platform
                and op.value == "!=")
                or (p == platform
                and op.value == "==")
            ]
        # TODO: NOTE: in the case of != above, this will return a list of [platform=windows, platform=linux, ...] => this means it is an OR of the list... 
        # is this always the case? handled correctly?

        return op.value == "!="  # we don't support it, so statically true/false.

    try:
        if variable.value == "extra":
            if op.value == "==":
                return [spec.Spec(f"+{value.value}")]
            elif op.value == "!=":
                return [spec.Spec(f"~{value.value}")]
    except (spack.parser.SpecSyntaxError, ValueError) as e:
        print(f"could not parse `{value}` as variant: {e}", file=sys.stderr)
        return None

    # Otherwise we only know how to handle constraints on the Python version.
    if variable.value not in ("python_version", "python_full_version"):
        return None

    versions = _eval_python_version_marker(
        variable.value, op.value, value.value, version_lookup
    )

    if versions is None:
        return None

    _simplify_python_constraint(versions)

    if not versions:
        # No supported versions for python remain, so statically false.
        return False
    elif versions == sv.any_version:
        # No constraints on python, so statically true.
        return True
    else:
        sp = spec.Spec("^python")
        sp.dependencies("python")[0].versions = versions
        return [sp]


def _eval_node(
    node, version_lookup: JsonVersionsLookup
) -> Union[None, bool, List[spec.Spec]]:

    if isinstance(node, tuple):
        return _eval_constraint(node, version_lookup)
    return _do_evaluate_marker(node, version_lookup)


def _intersection(lhs: List[spec.Spec], rhs: List[spec.Spec]) -> List[spec.Spec]:
    """Expand: (a or b) and (c or d) = (a and c) or (a and d) or (b and c) or (b and d)
    where `and` is spec intersection."""
    specs: List[spec.Spec] = []
    for l in lhs:
        for r in rhs:
            intersection = l.copy()
            try:
                intersection.constrain(r)
            except spack.error.UnsatisfiableSpecError:
                # empty intersection
                continue
            specs.append(intersection)
    return list(set(specs))


def _union(lhs: List[spec.Spec], rhs: List[spec.Spec]) -> List[spec.Spec]:
    """This case is trivial: (a or b) or (c or d) = a or b or c or d, BUT do a simplification
    in case the rhs only expresses constraints on versions."""
    if len(rhs) == 1 and not rhs[0].variants and not rhs[0].architecture:
        python, *_ = rhs[0].dependencies("python")
        for l in lhs:
            l.versions.add(python.versions)
        return lhs

    return list(set(lhs + rhs))


def _eval_and(group: List, version_lookup):
    lhs = _eval_node(group[0], version_lookup)
    if lhs is False:
        return False

    for node in group[1:]:
        rhs = _eval_node(node, version_lookup)
        if rhs is False:  # false beats none
            return False
        elif lhs is None or rhs is None:  # none beats true / List[Spec]
            lhs = None
        elif rhs is True:
            continue
        elif lhs is True:
            lhs = rhs
        else:  # Intersection of specs
            lhs = _intersection(lhs, rhs)
            if not lhs:  # empty intersection
                return False
    return lhs


def _do_evaluate_marker(
    node: list, version_lookup: JsonVersionsLookup
) -> Union[None, bool, List[spec.Spec]]:
    """A marker is an expression tree, that we can sometimes translate to the Spack DSL."""

    assert isinstance(node, list) and len(node) > 0, "node assert fails"

    # Inner array is "and", outer array is "or".
    groups = [[node[0]]]
    for i in range(2, len(node), 2):
        op = node[i - 1]
        if op == "or":
            groups.append([node[i]])
        elif op == "and":
            groups[-1].append(node[i])
        else:
            assert False, f"unexpected operator {op}"

    lhs = _eval_and(groups[0], version_lookup)
    if lhs is True:
        return True
    for group in groups[1:]:
        rhs = _eval_and(group, version_lookup)
        if rhs is True:
            return True
        elif lhs is None or rhs is None:
            lhs = None
        elif lhs is False:
            lhs = rhs
        elif rhs is not False:
            lhs = _union(lhs, rhs)
    return lhs


def _evaluate_marker(
    m: markers.Marker, version_lookup: JsonVersionsLookup
) -> Union[bool, None, List[spec.Spec]]:
    """Evaluate the marker expression tree either (1) as a list of specs that constitute the when
    conditions, (2) statically as True or False given that we only support cpython, (3) None if
    we can't translate it into Spack DSL."""
    return _do_evaluate_marker(m._markers, version_lookup)


##################################################################################################
# End of code from https://github.com/spack/pypi-to-spack-package/
##################################################################################################


lookup = JsonVersionsLookup()


def _format_dependency(
    dependency_spec: spec.Spec,
    when_spec: spec.Spec,
    dep_types: Optional[List[str]] = None,
) -> str:
    """Format a Spack dependency.

    Format the dependency (given as the main dependency spec and a "when" spec) as a
    "depends_on(...)" statement for package.py.

    Parameters:
        dependency_spec: Main dependency spec, e.g. "package@4.2:"
        when_spec: Spec for "when=" argument, e.g. "+extra ^python@:3.10"

    Returns:
        Formatted "depends_on(...)" statement for package.py.
    """

    s = f'depends_on("{str(dependency_spec)}"'

    if when_spec is not None and when_spec != spec.Spec():
        if when_spec.architecture:
            platform_str = f"platform={when_spec.platform}"
            when_spec.architecture = None 
        else:
            platform_str = ""
        when_str = f"{platform_str} {str(when_spec)}".strip()
        s += f', when="{when_str}"'

    if dep_types is not None:
        typestr = '", "'.join(dep_types)
        s += f', type=("{typestr}")'

    s += ")"

    return s


def _get_archive_extension(filename: str) -> "str | None":
    if filename.endswith(".whl"):
        print(
            "Supplied filename is a wheel file, please provide archive file!",
            file=sys.stderr,
        )
        return ".whl"

    archive_formats = [
        ".zip",
        ".tar",
        ".tar.gz",
        ".tar.bz2",
        ".rar",
        ".7z",
        ".gz",
        ".xz",
        ".bz2",
    ]

    l = [ext for ext in archive_formats if filename.endswith(ext)]

    if len(l) == 0:
        print(f"No extension recognized for: {filename}!", file=sys.stderr)
        return None

    if len(l) == 1:
        return l[0]

    longest_matching_ext = max(l, key=len)
    return longest_matching_ext


def _pkg_to_spack_name(name: str) -> str:
    """Convert PyPI package name to Spack python package name."""
    spack_name = _normalized_name(name)
    if USE_SPACK_PREFIX and spack_name != "python":
        # in general, if the package name already contains the "py-" prefix, we don't want to add it again
        # exception: 3 existing packages on spack with double "py-" prefix
        if not spack_name.startswith("py-") or spack_name in [
            "py-cpuinfo",
            "py-tes",
            "py-spy",
        ]:
            spack_name = "py-" + spack_name

    return spack_name


def _convert_requirement(
    r: requirements.Requirement, from_extra: Optional[str] = None
) -> List[Tuple[spec.Spec, spec.Spec]]:
    """Convert a packaging Requirement to its Spack equivalent.

    Each Spack requirement consists of a main dependency Spec and "when" Spec
    for conditions like variants or markers. It can happen that one requirement 
    is converted into a list of multiple Spack requirements, which all need to 
    be added.

    Parameters:
        r: packaging requirement
        from_extra: If this requirement an optional requirement dependent on an
        extra of the main package, supply the extra's name here.

    Returns:
        A list of tuples of (main_dependency_spec, when_spec).
    """

    spack_name = _pkg_to_spack_name(r.name)

    requirement_spec = spec.Spec(spack_name)

    # by default contains just an empty when_spec
    when_spec_list = [spec.Spec()]
    if r.marker is not None:
        # TODO: make sure we're evaluating and handling markers correctly
        # harmens code returns a list of specs for  marker => represents OR of specs
        # for each spec, add the requirement individually
        marker_eval = _evaluate_marker(r.marker, lookup)

        print("Marker eval:", str(marker_eval))

        if marker_eval is False:
            print("Marker is statically false, skip this requirement.")
            return []

        elif marker_eval is True:
            print("Marker is statically true, don't need to include in when_spec.")

        else:
            if isinstance(marker_eval, list):
                # replace empty when spec with marker specs
                when_spec_list = marker_eval

    if r.extras is not None:
        for extra in r.extras:
            requirement_spec.constrain(spec.Spec(f"+{extra}"))

    if r.specifier is not None:
        vlist = _pkg_specifier_set_to_version_list(r.name, r.specifier, lookup)
        
        # TODO: how to handle the case when version list is empty, i.e. no matching versions found?
        if not vlist:
            req_string = str(r)
            if from_extra:
                req_string += " from extra '" + from_extra + "'"
            raise ValueError(f"Could not resolve dependency {req_string}: No matching versions for '{r.name}' found!")

        requirement_spec.versions = vlist

    if from_extra is not None:
        # further constrain when_specs with extra 
        for when_spec in when_spec_list:
            when_spec.constrain(spec.Spec(f"+{from_extra}"))

    return [(requirement_spec, when_spec) for when_spec in when_spec_list]


# TODO: replace with spack mod_to_class?
def _name_to_class_name(name: str) -> str:
    """Convert a package name to a canonical class name for package.py."""
    classname = ""
    # in case there would be both - and _ in name
    name = name.replace("_", "-")
    name_arr = name.split("-")
    for w in name_arr:
        classname += w.capitalize()

    return classname



class PyProject:
    """
    A class to represent a pyproject.toml file. Contains all fields which are
    present in METADATA, plus additional ones only found in pyproject.toml.
    E.g. build-backend, build dependencies
    """

    def __init__(self):
        self.name: str = ""

        self.tool: Dict = dict()
        self.build_backend: Optional[str] = None
        self.build_requires: List[requirements.Requirement] = []
        self.metadata: Optional[py_metadata.StandardMetadata] = None
        self.dynamic: List[str] = []
        self.version: Optional[pv.Version] = None
        self.description: Optional[str] = None
        self.readme: Optional[str] = None
        self.requires_python: Optional[specifiers.SpecifierSet] = None
        self.license: Optional[py_metadata.License] = None
        self.authors: Optional[List] = None
        self.maintainers: Optional[List] = None
        self.keywords: Optional[List[str]] = None
        self.classifiers: Optional[List[str]] = None
        self.urls: Optional[Dict[str, str]] = None
        self.scripts: Optional[Dict[str, str]] = None
        self.gui_scripts: Optional[Dict[str, str]] = None
        self.entry_points: Optional[Dict[str, List[str]]] = None
        self.dependencies: List[requirements.Requirement] = []
        self.optional_dependencies: Dict[str, List[requirements.Requirement]] = dict()

    @staticmethod
    def from_toml(path: str, version: str = "") -> "PyProject | None":
        """
        Create a PyProject instance from a pyproject.toml file.

        The version corresponding to the pyproject.toml file should be known a-priori and
        should be passed here as a string argument. Alternatively, it can be read from the
        pyproject.toml file if it is specified explicitly there.

        Parameters:
            path: The path to the toml file.
            version: The version of the package which the pyproject.toml corresponds to.

        Returns:
            A PyProject instance.
        """
        try:
            with open(path, "rb") as f:
                toml_data = tomli.load(f)
        except (FileNotFoundError, IOError) as e:
            print(f"Failed to read .toml file: {e}", file=sys.stderr)
            return None

        pyproject = PyProject()

        # TODO: parse build system
        # if backend is poetry things are a bit different (dependencies)

        # parse pyproject metadata
        # this handles all the specified fields in the [project] table of pyproject.toml
        pyproject.metadata = py_metadata.StandardMetadata.from_pyproject(toml_data)

        # parse [build] table of pyproject.toml
        pyproject.build_backend = toml_data["build-system"]["build-backend"]
        build_dependencies = toml_data["build-system"]["requires"]
        pyproject.build_requires = [
            requirements.Requirement(req) for req in build_dependencies
        ]

        # transfer fields from metadata to pyproject instance
        attributes = [
            "name",
            "version",
            "description",
            "readme",
            "requires_python",
            "license",
            "authors",
            "maintainers",
            "keywords",
            "classifiers",
            "urls",
            "scripts",
            "gui_scripts",
            "entry_points",
            "dependencies",
            "optional_dependencies",
        ]

        for attr in attributes:
            setattr(pyproject, attr, getattr(pyproject.metadata, attr, None))

        # normalize the name
        pyproject.name = _normalized_name(pyproject.name)

        pyproject.tool = toml_data.get("tool", {})

        # TODO: handling the version, make sure we have the version of the current project
        # NOTE: in general, since we have downloaded and are parsing the pyproject.toml of a specific version,
        # we should know the version number a-priori. In this case it should be passed as a string argument to
        # the "from_toml(..)" method.
        if version:
            pyproject.version = _acceptable_version(version)
        if pyproject.version is None:
            if pyproject.dynamic is not None and "version" in pyproject.dynamic:
                # TODO: get version dynamically?
                print(
                    "ERROR: version specified as dynamic, this is not supported yet!",
                    file=sys.stderr,
                )
                return None
            else:
                print("ERROR: no version for pyproject.toml found!", file=sys.stderr)
                return None

        # TODO: build-backend-specific parsing of tool and other tables,
        # e.g. for additional dependencies
        # for example poetry could use "tool.poetry.dependencies" to specify dependencies

        if (
            pyproject.license is None
            or pyproject.license.text is None
            or pyproject.license.text == ""
        ):
            # license can also be specified in classifiers
            if pyproject.classifiers is not None:
                # get all classifiers detailing licenses
                license_classifiers = list(
                    filter(lambda x: x.startswith("License"), pyproject.classifiers)
                )
                # for each license classifier, split by "::" and take the last substring (and strip unnecessary whitespace)
                licenses = list(
                    map(lambda x: x.split("::")[-1].strip(), license_classifiers)
                )
                if len(licenses) > 0:
                    # TODO: can we decide purely from classifiers whether AND or OR? AND is more restrictive => be safe
                    license_txt = " AND ".join(licenses)
                    pyproject.license = py_metadata.License(text=license_txt, file=None)

        # manual checking of license format & text
        if pyproject.license is not None:
            if pyproject.license.text is not None and len(pyproject.license.text) > 200:
                print(
                    "License text appears to be full license content instead of license identifier. Please double check and add license identifier manually to package.py file.",
                    file=sys.stderr,
                )
                pyproject.license = None
            elif pyproject.license.text is None and pyproject.license.file is not None:
                print(
                    "License is supplied as a file. This is not supported, please add license identifier manually to package.py file.",
                    file=sys.stderr,
                )

        return pyproject

    @staticmethod
    def from_wheel(path: str):
        """TODO: not implemented"""
        pass

    def to_spack_pkg(self) -> "SpackPyPkg | None":
        """Convert this PyProject instance to a SpackPyPkg instance.

        Queries the PyPI JSON API in order to get information on available versions, archive
        file extensions, and file hashes.
        """
        spackpkg = SpackPyPkg()
        spackpkg.name = _pkg_to_spack_name(self.name)
        spackpkg.pypi_name = self.name

        spackpkg.description = self.description

        r = requests.get(
            f"https://pypi.org/simple/{self.name}/",
            headers={"Accept": "application/vnd.pypi.simple.v1+json"},
            timeout=10,
        )

        if r.status_code != 200:
            print(
                f"Error when querying json API. status code : {r.status_code}",
                file=sys.stderr,
            )
            if r.status_code == 404:
                print(
                    f"Package {self.name} not found on PyPI...",
                    file=sys.stderr,
                )
            return None

        files = r.json()["files"]
        non_wheels = list(filter(lambda f: not f["filename"].endswith(".whl"), files))

        if len(non_wheels) == 0:
            print(
                "No archive files found, only wheels!\nWheel file parsing not supported yet...",
                file=sys.stderr,
            )
            return None

        # TODO: use different approach to filename parsing?
        spackpkg.archive_extension = _get_archive_extension(non_wheels[-1]["filename"])
        if spackpkg.archive_extension is None:
            print(
                f"No archive file extension recognized!",
                file=sys.stderr,
            )
            return None

        filename = f"{self.name}-{self.version}{spackpkg.archive_extension}"

        matching_files = list(filter(lambda f: f["filename"] == filename, non_wheels))

        if len(matching_files) == 0:
            print(f"No file on PyPI matches filename '{filename}'!", file=sys.stderr)
            return None

        spackpkg.pypi = f"{self.name}/{filename}"

        file = matching_files[0]
        sha256 = file["hashes"]["sha256"]

        if self.version is not None:
            spack_version = _packaging_to_spack_version(self.version)
            spackpkg.versions.append((spack_version, sha256))

        for r in self.build_requires:
            spec_list = _convert_requirement(r)
            for specs in spec_list:
                spackpkg.build_dependencies.append(specs)

        for r in self.dependencies:
            spec_list = _convert_requirement(r)
            for specs in spec_list:
                spackpkg.runtime_dependencies.append(specs)

        for extra, deps in self.optional_dependencies.items():
            spackpkg.variants.append(extra)
            for r in deps:
                spec_list = _convert_requirement(r, from_extra=extra)
                for specs in spec_list:
                    spackpkg.variant_dependencies.append(specs)

        if self.requires_python is not None:
            r = requirements.Requirement("python")
            r.specifier = self.requires_python
            spec_list = _convert_requirement(r)
            for specs in spec_list:
                spackpkg.python_dependencies.append(specs)

        if self.authors is not None:
            for elem in self.authors:
                if isinstance(elem, str):
                    spackpkg.authors.append([elem])
                elif isinstance(elem, dict):
                    if set(elem.keys()).issubset(set(["name", "email"])):
                        l = []
                        for key in ["name", "email"]:
                            if key in elem.keys():
                                l.append(elem[key])
                        spackpkg.authors.append(l)
                    else:
                        print(
                            f"Expected author dict to contain keys 'name' or 'email': {elem}",
                            file=sys.stderr,
                        )
                elif isinstance(elem, tuple) or isinstance(elem, list):
                    spackpkg.authors.append(list(elem))
                else:
                    print(
                        f"Expected authors to be either string or dict elements: {elem}",
                        file=sys.stderr,
                    )

        if self.maintainers is not None:
            for elem in self.maintainers:
                if isinstance(elem, str):
                    spackpkg.maintainers.append([elem])
                elif isinstance(elem, dict):
                    if set(elem.keys()).issubset(set(["name", "email"])):
                        l = []
                        for key in ["name", "email"]:
                            if key in elem.keys():
                                l.append(elem[key])
                        spackpkg.maintainers.append(l)
                    else:
                        print(
                            f"Expected maintainer dict to contain keys 'name' or 'email': {elem}",
                            file=sys.stderr,
                        )
                elif isinstance(elem, tuple) or isinstance(elem, list):
                    spackpkg.maintainers.append(list(elem))
                else:
                    print(
                        f"Expected maintainer to be either string or dict elements: {elem}",
                        file=sys.stderr,
                    )

        if self.license is not None and self.license.text is not None:
            spackpkg.license = self.license.text
        else:
            print("No license identifier found!", file=sys.stderr)

        return spackpkg


class SpackPyPkg:
    """Class representing a Spack PythonPackage object.

    Instances are created directly from PyProject objects, by converting PyProject fields and
    semantics to their Spack equivalents (where possible).
    """

    def __init__(self):
        self.name: str = ""
        self.pypi_name: str = ""
        self.description: Optional[str] = None
        self.pypi: str = ""
        self.versions: List[Tuple[sv.Version, str]] = []
        self.build_dependencies: List[Tuple[spec.Spec, spec.Spec]] = []
        self.runtime_dependencies: List[Tuple[spec.Spec, spec.Spec]] = []
        self.variant_dependencies: List[Tuple[spec.Spec, spec.Spec]] = []
        self.variants: List[str] = []
        self.python_dependencies: List[Tuple[spec.Spec, spec.Spec]] = []
        self.maintainers: List[List[str]] = []
        self.authors: List[List[str]] = []
        self.license: Optional[str] = None

        self.archive_extension: Optional[str] = None

        # import_modules = []

    def print_package(self, outfile=sys.stdout):
        """Format and write the package to 'outfile'.

        By default outfile=sys.stdout. The package can be written directly to a package.py file
        by supplying the corresponding file object.
        """
        print("Outputting package.py...\n")

        copyright = """\
# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
"""

        print(copyright, file=outfile)

        print("from spack.package import *", file=outfile)
        print("", file=outfile)

        print(f"class {_name_to_class_name(self.name)}(PythonPackage):", file=outfile)

        if self.description is not None and len(self.description) > 0:
            print(f'    """{self.description}"""', file=outfile)
        else:
            print(
                '    """FIXME: Put a proper description of your package here."""',
                file=outfile,
            )

        print("", file=outfile)

        print(f'    pypi = "{self.pypi}"', file=outfile)

        print("", file=outfile)

        if self.license is not None and self.license != "":
            print(f'    license("{self.license}")', file=outfile)
            print("", file=outfile)

        if self.authors:
            print("    # Authors:", file=outfile)
            for author in self.authors:
                author_string = ", ".join(author)
                print(f"    # {author_string}", file=outfile)

            print("", file=outfile)

        if self.maintainers:
            print("    # Maintainers:", file=outfile)
            for maintainer in self.maintainers:
                maintainer_string = ", ".join(maintainer)
                print(f"    # {maintainer_string}", file=outfile)

            print("", file=outfile)

        for v, sha256 in self.versions:
            print(f'    version("{str(v)}", sha256="{sha256}")', file=outfile)

        print("", file=outfile)

        for v in self.variants:
            print(f'    variant("{v}", default=False)', file=outfile)

        print("", file=outfile)

        if self.build_dependencies:
            print('    with default_args(type="build"):', file=outfile)
            for dep_spec, when_spec in self.build_dependencies:
                print(
                    "        " + _format_dependency(dep_spec, when_spec), file=outfile
                )

            print("", file=outfile)

        if (
            self.python_dependencies
            + self.runtime_dependencies
            + self.variant_dependencies
        ):
            print('    with default_args(type=("build", "run")):', file=outfile)

            for dep_spec, when_spec in self.python_dependencies:
                print(
                    "        " + _format_dependency(dep_spec, when_spec), file=outfile
                )

            for dep_spec, when_spec in self.runtime_dependencies:
                print(
                    "        " + _format_dependency(dep_spec, when_spec), file=outfile
                )

            print("", file=outfile)

            for dep_spec, when_spec in self.variant_dependencies:
                print(
                    "        " + _format_dependency(dep_spec, when_spec), file=outfile
                )

        print("", file=outfile)


FILE_PATH = "example_black24.3.0_pyproject.toml"

if __name__ == "__main__":
    py_pkg = PyProject.from_toml(FILE_PATH, version="24.3.0")

    if py_pkg is None:
        print("Error: could not generate PyProject from .toml", file=sys.stderr)
        exit()

    spack_pkg = py_pkg.to_spack_pkg()

    if spack_pkg is None:
        print("Error: could not generate spack package from PyProject", file=sys.stderr)
        exit()

    if USE_TEST_PREFIX:
        spack_pkg.name = TEST_PKG_PREFIX + spack_pkg.name

    print("spack pkg built")

    spack_pkg.print_package(outfile=sys.stdout)
    # with open("package.py", "w+") as f:
    #    spack_pkg.print_package(outfile=f)