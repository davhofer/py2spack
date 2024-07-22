"""Utilities for converting packaging requirements to Spack dependency specs.

Parts of the code are adapted from Spack/Harmen Stoppels: https://github.com/spack/pypi-to-spack-package.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import packaging.version as pv
import spack.error
import spack.parser
from packaging import markers, requirements, specifiers
from spack import spec, version as sv
from spack.util import naming


if TYPE_CHECKING:
    from py2spack import loading


# these python versions are not supported anymore, so we shouldn't need to
# consider them
UNSUPPORTED_PYTHON = sv.VersionRange(
    sv.StandardVersion.typemin(), sv.StandardVersion.from_string("3.5")
)

NAME_REGEX = re.compile(r"[-_.]+")

LOCAL_SEPARATORS_REGEX = re.compile(r"[\._-]")

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


class ConversionError(Exception):
    """Error while converting a packaging requirement to spack."""

    def __init__(
        self,
        msg: str,
        *,
        requirement: str | None = None,
    ):
        """Initialize error."""
        super().__init__(msg)
        self._requirement = requirement

    @property
    def requirement(self) -> str | None:
        """Get requirement."""
        return self._requirement


# TODO @davhofer: integrate this into a datastructure, omit mutable global state  # noqa: TD003
evalled: dict = {}


def acceptable_version(version: str) -> pv.Version | None:
    """Check whether version string can be parsed and has correct format."""
    try:
        v = pv.parse(version)
        # do not support post releases of prereleases etc.
        if v.pre and (v.post or v.dev or v.local):
            return None
        return v
    except pv.InvalidVersion:
        return None


def _get_python_versions() -> list[pv.Version]:
    """Statically evaluate python versions."""
    return [pv.Version(f"{major}.{minor}.{patch}") for major, minor, patch in KNOWN_PYTHON_VERSIONS]


def _best_upperbound(curr: sv.StandardVersion, nxt: sv.StandardVersion) -> sv.StandardVersion:
    """Return the most general upper bound that includes curr but not nxt.

    Invariant is that curr < nxt. Here, "most general" means the differentiation
    should happen as high as possible in the version specifier hierarchy.
    """
    assert curr < nxt
    i = 0
    m = min(len(curr), len(nxt))
    # find the first level in the version specifier hierarchy where the two
    # versions differ
    while i < m and curr.version[0][i] == nxt.version[0][i]:
        i += 1

    if i == len(curr) < len(nxt):
        ldiff = len(nxt) - len(curr)
        # e.g. curr = 3.4, nxt = 3.4.5, i = 2
        release, _ = curr.version
        # need to add enough zeros to not include a sub-version by accident
        # (e.g. when curr=2.0, nxt=2.0.0.1)
        release += (0,) * ldiff
        seperators = (".",) * (len(release) - 1) + ("",)
        as_str = ".".join(str(x) for x in release)
        return sv.StandardVersion(as_str, (tuple(release), (sv.common.FINAL,)), seperators)
    if i == m:
        return curr  # include pre-release of curr

    return curr.up_to(i + 1)


def _best_lowerbound(prev: sv.StandardVersion, curr: sv.StandardVersion) -> sv.StandardVersion:
    """Return the most general lower bound that includes curr but not prev.

    Invariant is that prev < curr. Counterpart to _best_upperbound().
    Cases:
        Same length:
            There exists index i s.t. prev[i] < curr[i]. Find i,
            take curr[:i+1] (including i).

        Prev is longer:
            Same as before.

        Curr is longer:
            Either ther exists index i s.t. prev[i] < curr[i],
            or they have the same prefix, then take curr up to the first
            non-zero index after.

    Edge case:
        prereleases, post, dev, local versions: NOT SUPPORTED!
        Semantics of prereleases are tricky.
        E.g. version 1.1-alpha1 is included in range :1.0, but not in
        range :1.0.0
    """
    assert prev < curr

    # check if prev is a prerelease of curr
    if curr.version[0] == prev.version[0]:
        return curr

    i = 0
    m = min(len(curr), len(prev))
    while i < m:
        if prev.version[0][i] < curr.version[0][i]:
            return curr.up_to(i + 1)
        i += 1

    # both have the same prefix and curr is longer (otherwise we would have
    # found an index i where prev[i] < curr[i], according to invariant)
    assert len(curr) > len(prev)

    # according to invariant, there must be a non-zero value (otherwise the
    # versions would be identical)
    while i < len(curr) and curr.version[0][i] == 0:
        i += 1

    # necessary in order not to exclude relevant prerelease of curr
    # e.g. if prev = 4.2, curr = 4.3-alpha1
    # we want the bound to be 4.3-alpha1, not 4.3
    if i >= len(curr):
        return curr

    return curr.up_to(i + 1)


def packaging_to_spack_version(v: pv.Version) -> sv.StandardVersion:
    """Convert packaging version to equivalent spack version."""
    # TODO @davhofer: better epoch support.  # noqa: TD003
    release = []
    prerelease = [sv.common.FINAL]
    if v.epoch > 0:
        msg = f"warning: epoch {v} isn't really supported"
        logging.warning(msg)
        release.append(v.epoch)
    release.extend(v.release)
    separators = ["."] * (len(release) - 1)

    if v.pre is not None:
        tp, num = v.pre
        if tp == "a":
            prerelease = [sv.common.ALPHA, num]
        elif tp == "b":
            prerelease = [sv.common.BETA, num]
        elif tp == "rc":
            prerelease = [sv.common.RC, num]
        separators.extend(("-", ""))

        if v.post or v.dev or v.local:
            msg = f"warning: ignoring post / dev / local version {v}"
            logging.warning(msg)

    else:
        if v.post is not None:
            release.extend((sv.version_types.VersionStrComponent("post"), v.post))
            separators.extend((".", ""))
        if v.dev is not None:  # dev is actually pre-release like, spack makes it a post-release.
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

    return sv.StandardVersion(string, (tuple(release), tuple(prerelease)), separators)


def _version_type_supported(version: pv.Version) -> bool:
    return (
        version.pre is None
        and version.post is None
        and version.dev is None
        and version.local is None
    )


def condensed_version_list(
    _subset_of_versions: list[pv.Version], _all_versions: list[pv.Version]
) -> sv.VersionList:
    """Create condensed list of version ranges equivalent to version subset."""
    # for now, don't support prereleases etc.
    subset_filtered = list(filter(_version_type_supported, _subset_of_versions))
    all_versions_filtered = list(filter(_version_type_supported, _all_versions))

    if len(subset_filtered) < len(_subset_of_versions) or len(all_versions_filtered) < len(
        _all_versions
    ):
        # TODO @davhofer: this msg is displayed 100s of times. move it somewhere else and  # noqa: TD003
        # display it only once
        msg = (
            "Prereleases as well as post, dev, and local versions are not "
            "supported and will be excluded!"
        )
        logging.warning(msg)

    # Sort in Spack's order, which should in principle coincide with
    # packaging's order, but may not in unforseen edge cases.
    subset = sorted(packaging_to_spack_version(v) for v in subset_filtered)
    all_versions = sorted(packaging_to_spack_version(v) for v in all_versions_filtered)

    if len(subset) == 0:
        return sv.VersionList([])

    # Find corresponding index
    i, j = all_versions.index(subset[0]) + 1, 1
    new_versions: list[sv.ClosedOpenRange] = []

    # If the first when entry corresponds to the first known version, use
    # (-inf, ..] as lowerbound.
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

    return sv.VersionList(new_versions)


def _pkg_specifier_set_to_version_list(
    pkg: str,
    specifier_set: specifiers.SpecifierSet,
    lookup: loading.PyPILookup,
) -> sv.VersionList:
    """Convert the specifier set to an equivalent list of version ranges."""
    # TODO @davhofer: improve how & where the caching is done?  # noqa: TD003
    key = (pkg, specifier_set)
    if key in evalled:
        return evalled[key]

    all_versions = _get_python_versions() if pkg == "python" else lookup.get_versions(pkg)

    matching = [s for s in all_versions if specifier_set.contains(s, prereleases=True)]
    result = sv.VersionList() if not matching else condensed_version_list(matching, all_versions)
    evalled[key] = result
    return result


def _eval_python_version_marker(
    op: str, value: str, lookup: loading.PyPILookup
) -> sv.VersionList | None:
    # TODO @davhofer: there might be still some bug caused by python_version vs  # noqa: TD003
    # python_full_version differences.
    # Also `in` and `not in` are allowed, but difficult to get right. They take
    # the rhs as a string and do string matching instead of version parsing...
    # so we don't support them now.
    if op not in ("==", ">", ">=", "<", "<=", "!="):
        return None

    try:
        specifier = specifiers.SpecifierSet(f"{op}{value}")
    except specifiers.InvalidSpecifier:
        msg = f"could not parse `{op}{value}` as specifier"
        logging.warning(msg)
        return None

    return _pkg_specifier_set_to_version_list("python", specifier, lookup)


def _simplify_python_constraint(versions: sv.VersionList) -> None:
    """Modifies a version list to remove redundant constraints.

    These redundant constraints are implied by UNSUPPORTED_PYTHON. Version list
    is modified in place.
    """
    # First delete everything implied by UNSUPPORTED_PYTHON
    vs = versions.versions
    while vs and vs[0].satisfies(UNSUPPORTED_PYTHON):
        del vs[0]

    if not vs:
        return

    # Remove any redundant lowerbound, e.g. @3.7:3.9 becomes @:3.9 if @:3.6
    # unsupported.
    union = UNSUPPORTED_PYTHON._union_if_not_disjoint(vs[0])
    if union:
        vs[0] = union


def _eval_platform_constraint(node: tuple) -> bool | list[spec.Spec] | None:
    platforms = ("linux", "cray", "darwin", "windows", "freebsd")

    variable, op, value = node

    assert variable.value in {"platform_system", "sys_platform"}

    if op.value not in {"==", "!="}:
        return None

    platform = value.value.lower()
    if platform == "win32":
        platform = "windows"
    elif platform == "linux2":
        platform = "linux"

    if platform in platforms:
        return [
            spec.Spec(f"platform={p}")
            for p in platforms
            if (p != platform and op.value == "!=") or (p == platform and op.value == "==")
        ]
    # TODO @davhofer: NOTE: in the case of != above, this will return a list of  # noqa: TD003
    # [platform=windows, platform=linux, ...] => this means it is an OR of
    # the list... is this always the case? handled correctly?

    # we don't support it, so statically true/false.
    return bool(op.value == "!=")


def _eval_python_constraint(
    node: tuple, lookup: loading.PyPILookup
) -> bool | list[spec.Spec] | None:
    variable, op, value = node
    versions = _eval_python_version_marker(op.value, value.value, lookup)

    if versions is not None:
        _simplify_python_constraint(versions)

        if not versions:
            # No supported versions for python remain, so statically false.
            return False

        if versions == sv.any_version:
            # No constraints on python, so statically true.
            return True

        sp = spec.Spec("^python")
        sp.dependencies("python")[0].versions = versions
        return [sp]

    return None


def _eval_constraint(node: tuple, lookup: loading.PyPILookup) -> None | bool | list[spec.Spec]:
    """Evaluate a environment marker (variable, operator, value).

    Returns:
        None: If constraint cannot be evaluated.
        True/False: If constraint is statically true or false.
        List of specs: Spack representation of the constraint(s).
    """
    # TODO @davhofer: os_name, platform_machine, platform_release, platform_version,  # noqa: TD003
    # implementation_version

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
            msg = f"do not know how to evaluate `{node}`"
            logging.warning(msg)
            return None
        variable, op, value = value, markers.Op(flipped_op), variable

    return_val: bool | list[spec.Spec] | None = None

    # Statically evaluate implementation name, since all we support is cpython
    if variable.value in {"implementation_name", "platform_python_implementation"}:
        if op.value == "==":
            return_val = bool(value.value.lower() == "cpython")

        if op.value == "!=":
            return_val = bool(value.value.lower() != "cpython")

    elif variable.value in {"platform_system", "sys_platform"}:
        return_val = _eval_platform_constraint(node)

    elif variable.value in ("python_version", "python_full_version"):
        return_val = _eval_python_constraint(node, lookup)

    else:
        try:
            if variable.value == "extra":
                if op.value == "==":
                    return_val = [spec.Spec(f"+{value.value}")]

                if op.value == "!=":
                    return_val = [spec.Spec(f"~{value.value}")]

        except (spack.parser.SpecSyntaxError, ValueError) as e:
            msg = f"could not parse `{value}` as variant: {e}"
            logging.warning(msg)
            return None

    return return_val


def _eval_node(node: tuple | list, lookup: loading.PyPILookup) -> None | bool | list[spec.Spec]:
    if isinstance(node, tuple):
        return _eval_constraint(node, lookup)
    return _do_evaluate_marker(node, lookup)


def _intersection(lhs: list[spec.Spec], rhs: list[spec.Spec]) -> list[spec.Spec]:
    """Compute intersection of spec lists.

    Expand: (a or b) and (c or d) = (a and c) or (a and d) or (b and c) or
    (b and d) where `and` is spec intersection.
    """
    specs: list[spec.Spec] = []
    for expr in lhs:
        for r in rhs:
            intersection = expr.copy()
            try:
                intersection.constrain(r)
            except spack.error.UnsatisfiableSpecError:
                # empty intersection
                continue
            specs.append(intersection)
    return list(set(specs))


def _union(lhs: list[spec.Spec], rhs: list[spec.Spec]) -> list[spec.Spec]:
    """Compute union of spec lists.

    This case is trivial: (a or b) or (c or d) = a or b or c or d, BUT do a
    simplification in case the rhs only expresses constraints on versions.
    """
    if len(rhs) == 1 and not rhs[0].variants and not rhs[0].architecture:
        python, *_ = rhs[0].dependencies("python")
        for expr in lhs:
            expr.versions.add(python.versions)
        return lhs

    return list(set(lhs + rhs))


def _eval_and(group: list, version_lookup: loading.PyPILookup) -> bool | list[Any] | None:
    lhs = _eval_node(group[0], version_lookup)
    if lhs is False:
        return False

    for node in group[1:]:
        rhs = _eval_node(node, version_lookup)
        if rhs is False:  # false beats none
            return False
        if lhs is None or rhs is None:  # none beats true / List[Spec]
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


def _do_evaluate_marker(node: list, lookup: loading.PyPILookup) -> None | bool | list[spec.Spec]:
    """Recursively try to evaluate a node (in the marker expression tree).

    A marker is an expression tree, that we can sometimes translate to the
    Spack DSL.
    """
    # Inner array is "and", outer array is "or".
    groups = [[node[0]]]
    for i in range(2, len(node), 2):
        op = node[i - 1]
        if op == "or":
            groups.append([node[i]])
        elif op == "and":
            groups[-1].append(node[i])
        else:
            raise ValueError(f"unexpected operator {op}")

    lhs: bool | list[Any] | None = _eval_and(groups[0], lookup)
    if lhs is True:
        return True
    for group in groups[1:]:
        rhs = _eval_and(group, lookup)
        if rhs is True:
            return True
        if lhs is None or rhs is None:
            lhs = None
        elif lhs is False:
            lhs = rhs
        elif rhs is not False:
            lhs = _union(lhs, rhs)
    return lhs


def evaluate_marker(m: markers.Marker, lookup: loading.PyPILookup) -> bool | None | list[spec.Spec]:
    """Evaluate a marker.

    Evaluate the marker expression tree either (1) as a list of specs that
    constitute the when conditions, (2) statically as True or False given that
    we only support cpython, (3) None if we can't translate it into Spack DSL.
    """
    return _do_evaluate_marker(m._markers, lookup)


# TODO @davhofer: verify whether spack name actually corresponds to PyPI package  # noqa: TD003
def pkg_to_spack_name(name: str) -> str:
    """Convert PyPI package name to Spack python package name."""
    spack_name: str = naming.simplify_name(name)
    # in general, if the package name already contains the "py-" prefix, we
    # don't want to add it again. exception: 3 existing packages on spack
    # with double "py-" prefix
    if spack_name != "python" and (
        not spack_name.startswith("py-")
        or spack_name
        in [
            "py-cpuinfo",
            "py-tes",
            "py-spy",
        ]
    ):
        spack_name = "py-" + spack_name

    return spack_name


def _convert_requirement(
    r: requirements.Requirement,
    lookup: loading.PyPILookup,
    from_extra: str | None = None,
) -> list[tuple[spec.Spec, spec.Spec]] | ConversionError:
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
    spack_name = pkg_to_spack_name(r.name)

    requirement_spec = spec.Spec(spack_name)

    # by default contains just an empty when_spec
    when_spec_list = [spec.Spec()]
    if r.marker is not None:
        # 'evaluate_marker' code returns a list of specs for  marker =>
        # represents OR of specs
        try:
            marker_eval = evaluate_marker(r.marker, lookup)
        except ValueError as e:
            from_extra_str = "" if not from_extra else f" from extra '{from_extra}'"
            msg = f"Unable to convert marker {r.marker} for dependency" f" {r}{from_extra_str}: {e}"
            return ConversionError(msg, requirement=str(r))

        if isinstance(marker_eval, bool) and marker_eval is False:
            # Marker is statically false, skip this requirement
            # (because the "when" clause cannot be true)
            return []

        # if the marker eval is not bool, then it is a list
        if not isinstance(marker_eval, bool) and isinstance(marker_eval, list):
            # replace empty when spec with marker specs
            when_spec_list = marker_eval

        # if marker_eval is True, then the marker is statically true, we don't
        # need to include it

    # these are the extras passed to the dependency itself; not the extras of
    # the main package for which this requirement is necessary
    if r.extras is not None:
        for extra in r.extras:
            requirement_spec.constrain(spec.Spec(f"+{extra}"))

    if r.specifier is not None:
        vlist = _pkg_specifier_set_to_version_list(r.name, r.specifier, lookup)

        # return Error if no version satisfies the requirement
        if not vlist:
            from_extra_str = "" if not from_extra else f" from extra {from_extra}"
            msg = f"Unable to convert dependency" f" {r}{from_extra_str}: no matching versions"
            return ConversionError(msg, requirement=str(r))

        requirement_spec.versions = vlist

    if from_extra is not None:
        # further constrain when_specs with extra
        for when_spec in when_spec_list:
            when_spec.constrain(spec.Spec(f"+{from_extra}"))

    return [(requirement_spec, when_spec) for when_spec in when_spec_list]
