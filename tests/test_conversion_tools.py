"""Tests for conversion_tools.py module."""
from __future__ import annotations

import pytest
from packaging import markers, requirements, specifiers, version as pv
from spack import spec, version as sv

from py2spack import conversion_tools, loading



@pytest.mark.parametrize(
    "prev, curr",
    [
        # ("23.1-alpha1", "23.1.0"),
        # ("23.1-alpha1", "23.1"),
        # ("23.1.0", "23.2-alpha1"),
        # ("23.1", "23.2-alpha1"),
        ("23.0", "23.0.0.1"),
        ("23.0", "23.0.1"),
        ("22.1.3.4.5", "22.1.6"),
        ("22.1.3.4.5", "22.2.6.1"),
        ("22.1.3", "22.1.3.4"),
        ("22.1.3", "22.1.4"),
    ],
)
def test_best_lowerbound(prev, curr):
    prev = sv.Version(prev)
    curr = sv.Version(curr)

    result = conversion_tools._best_lowerbound(prev, curr)
    result_range = sv.VersionRange(result, sv.StandardVersion.typemax())

    assert prev not in result_range
    assert curr in result_range


@pytest.mark.parametrize(
    "curr, nxt",
    [
        # ("23.1-alpha1", "23.1.0"),
        # ("23.1-alpha1", "23.1"),
        # ("23.1.0", "23.2-alpha1"),
        # ("23.1", "23.2-alpha1"),
        ("23.0", "23.0.0.1"),
        ("23.0", "23.0.1"),
        ("22.1.3.4.5", "22.1.6"),
        ("22.1.3.4.5", "22.2.6.1"),
        ("22.1.3", "22.1.3.4"),
        ("22.1.3", "22.1.4"),
    ],
)
def test_best_upperbound(curr, nxt):
    curr = sv.Version(curr)
    nxt = sv.Version(nxt)

    result = conversion_tools._best_upperbound(curr, nxt)
    result_range = sv.VersionRange(sv.StandardVersion.typemin(), result)

    assert nxt not in result_range
    assert curr in result_range


@pytest.mark.parametrize(
    "version_str, expected",
    [
        ("4.3.2.5.4", pv.Version("4.3.2.5.4")),
        ("2..4", None),
        ("2", pv.Version("2")),
        ("4.dev2", pv.Version("4.dev2")),
        ("3.pre.dev2", None),
    ],
)
def test_acceptable_version(version_str, expected):
    assert conversion_tools.acceptable_version(version_str) == expected


@pytest.mark.parametrize(
    "version, expected",
    [
        (pv.Version("2"), sv.Version("2")),
        (pv.Version("4.3.2.0"), sv.Version("4.3.2.0")),
        (pv.Version("4.dev2"), sv.Version("4.dev2")),
    ],
)
def test_packaging_to_spack_version(version, expected):
    assert conversion_tools.packaging_to_spack_version(version) == expected


def test_condensed_version_list_specific1():
    subset = [pv.Version("2.0.1"), pv.Version("2.1.0")]
    all_versions = [
        pv.Version("2.0.1"),
        pv.Version("2.1.0"),
        pv.Version("2.0.5"),
    ]
    result = conversion_tools.condensed_version_list(subset, all_versions)

    assert sv.Version("2.0.5") not in result
    assert sv.Version("2.0.1") in result
    assert sv.Version("2.1.0") in result


def test_condensed_version_list_specific2():
    subset = ["2.0", "2.1"]
    all_versions = [
        "2.0",
        "2.1",
        "2.0.0.1",
    ]
    pv_subset = [pv.Version(v) for v in subset]
    pv_all_versions = [pv.Version(v) for v in all_versions]
    result = conversion_tools.condensed_version_list(pv_subset, pv_all_versions)

    for v in subset:
        v_spack = sv.Version(v)
        assert v_spack in result

    excluded = [v for v in all_versions if v not in subset]
    for v in excluded:
        v_spack = sv.Version(v)
        assert v_spack not in result


def test_condensed_version_list_specific3():
    subset = ["2.0.0", "2.1"]
    all_versions = [
        "2.0.0",
        "2.1",
        "2.0.0.1",
    ]
    pv_subset = [pv.Version(v) for v in subset]
    pv_all_versions = [pv.Version(v) for v in all_versions]
    result = conversion_tools.condensed_version_list(pv_subset, pv_all_versions)

    for v in subset:
        v_spack = sv.Version(v)
        assert v_spack in result

    excluded = [v for v in all_versions if v not in subset]
    for v in excluded:
        v_spack = sv.Version(v)
        assert v_spack not in result


def test_condensed_version_list():
    subset = ["2.0", "3.5", "4.2", "2.0.1", "2.1.0", "1.9"]
    all_versions = [
        "2.0",
        "3.5",
        "4.2",
        "2.0.1",
        "2.1.0",
        "1.9",
        "2.0.5",
        "2.0.0.2",
        "1.2",
        "3.5.1",
        "3.5.2",
        "5",
        "4.3",
        "2.0.1.1",
        "1.8.0",
    ]
    pv_subset = [pv.Version(v) for v in subset]
    pv_all_versions = [pv.Version(v) for v in all_versions]
    result = conversion_tools.condensed_version_list(pv_subset, pv_all_versions)

    for v in subset:
        v_spack = sv.Version(v)
        assert v_spack in result

    excluded = [v for v in all_versions if v not in subset]
    for v in excluded:
        v_spack = sv.Version(v)
        assert v_spack not in result


BLACK_VERSIONS = [
    "22.1.0",
    "22.3.0",
    "22.6.0",
    "22.8.0",
    "22.10.0",
    "22.12.0",
    # "23.1a1",
    "23.1.0",
    "23.3.0",
    "23.7.0",
    "23.9.0",
    "23.9.1",
    "23.10.0",
    "23.10.1",
    "23.11.0",
    "23.12.0",
    "23.12.1",
]


@pytest.mark.parametrize(
    "specifier_set, expect_included",
    [
        (specifiers.SpecifierSet("==23.2"), []),
        (
            specifiers.SpecifierSet("==23.1"),
            ["23.1.0"],
        ),
        (
            specifiers.SpecifierSet("~=22.6"),
            ["22.6.0", "22.8.0", "22.10.0", "22.12.0"],
        ),
        (
            specifiers.SpecifierSet(">=22.6,<23"),
            ["22.6.0", "22.8.0", "22.10.0", "22.12.0"],
        ),
        (
            specifiers.SpecifierSet(">=22.11"),
            [
                "22.12.0",
                # "23.1a1",
                "23.1.0",
                "23.3.0",
                "23.7.0",
                "23.9.0",
                "23.9.1",
                "23.10.0",
                "23.10.1",
                "23.11.0",
                "23.12.0",
                "23.12.1",
            ],
        ),
        (specifiers.SpecifierSet(">23.12"), ["23.12.1"]),
        (specifiers.SpecifierSet("<22.6.0"), ["22.1.0", "22.3.0"]),
        (specifiers.SpecifierSet(">=22"), BLACK_VERSIONS),
        (specifiers.SpecifierSet(">23,<23"), []),
        (
            specifiers.SpecifierSet(">=22.6,<23.9.1"),
            [
                "22.6.0",
                "22.8.0",
                "22.10.0",
                "22.12.0",
                # "23.1a1",
                "23.1.0",
                "23.3.0",
                "23.7.0",
                "23.9.0",
            ],
        ),
    ],
)
def test_pkg_specifier_set_to_version_list(
    specifier_set,
    expect_included,
):
    """.

    We use the package black, with versions limited to the range 22 <= v < 24
    for reproducibility even when black adds versions.
    """
    lookup = loading.PyPILookup()

    specifier_set &= specifiers.SpecifierSet(">=22")
    specifier_set &= specifiers.SpecifierSet("<24")

    result = conversion_tools._pkg_specifier_set_to_version_list(
        "black", specifier_set, lookup
    )

    sv_included = [sv.Version(v) for v in expect_included]

    expect_excluded = list(
        filter(lambda x: x not in expect_included, BLACK_VERSIONS)
    )
    sv_excluded = [sv.Version(v) for v in expect_excluded]

    for v in sv_included:
        assert v in result

    for v in sv_excluded:
        assert v not in result


@pytest.mark.parametrize(
    "marker, expected",
    [
        (markers.Marker("implementation_name == 'cpython'"), True),
        (markers.Marker("platform_python_implementation != 'cpython'"), False),
        (
            markers.Marker("sys_platform == 'linux'"),
            [spec.Spec("platform=linux")],
        ),
        (
            markers.Marker("platform_system != 'windows'"),
            [
                spec.Spec("platform=linux"),
                spec.Spec("platform=cray"),
                spec.Spec("platform=darwin"),
                spec.Spec("platform=freebsd"),
            ],
        ),
        (markers.Marker("sys_platform != 'obscure_platform'"), True),
        (
            markers.Marker(
                "sys_platform == 'linux' or sys_platform == 'windows'"
            ),
            [spec.Spec("platform=linux"), spec.Spec("platform=windows")],
        ),
        (
            markers.Marker(
                "sys_platform != 'linux' and sys_platform != 'windows'"
            ),
            [
                spec.Spec("platform=freebsd"),
                spec.Spec("platform=cray"),
                spec.Spec("platform=darwin"),
            ],
        ),
        (
            markers.Marker("python_version >= '3.9'"),
            [spec.Spec("^python@3.9:")],
        ),
        (
            markers.Marker("python_full_version < '3.9'"),
            [spec.Spec("^python@:3.8")],
        ),
        (
            markers.Marker(
                "python_full_version < '3.9' and python_version > '3.9'"
            ),
            False,
        ),
        (
            markers.Marker(
                "python_version >= '3.8' and sys_platform == 'linux'"
            ),
            [spec.Spec("platform=linux ^python@3.8:")],
        ),
        (
            markers.Marker(
                "python_version >= '3.10' or sys_platform == 'windows'"
            ),
            [spec.Spec("^python@3.10:"), spec.Spec("platform=windows")],
        ),
        (markers.Marker("extra == 'extension'"), [spec.Spec("+extension")]),
        (
            markers.Marker("extra == 'test' and sys_platform != 'freebsd'"),
            [
                spec.Spec("+test platform=linux"),
                spec.Spec("+test platform=windows"),
                spec.Spec("+test platform=cray"),
                spec.Spec("+test platform=darwin"),
            ],
        ),
    ],
)
def test_evaluate_marker(marker, expected):
    lookup = loading.PyPILookup()
    result = conversion_tools.evaluate_marker(marker, lookup)

    if isinstance(expected, list):
        assert isinstance(result, list)
        result = set(result)
        expected = set(expected)

    assert result == expected

@pytest.mark.parametrize(
    "req, from_extra, expected",
    [
        (
            requirements.Requirement("black>=24.2"),
            None,
            [(spec.Spec("py-black@24.2:"), spec.Spec())],
        ),
        (
            requirements.Requirement("black>=24.2; extra == 'foo'"),
            None,
            [(spec.Spec("py-black@24.2:"), spec.Spec("+foo"))],
        ),
        (
            requirements.Requirement("black[foo]>=24.2"),
            None,
            [(spec.Spec("py-black@24.2: +foo"), spec.Spec())],
        ),
        (
            requirements.Requirement("black>=24.2"),
            "extra",
            [(spec.Spec("py-black@24.2:"), spec.Spec("+extra"))],
        ),
        (
            requirements.Requirement("black>=24.2; python_version >= '3.8'"),
            None,
            [(spec.Spec("py-black@24.2:"), spec.Spec("^python@3.8:"))],
        ),
        (
            requirements.Requirement(
                "black>=24.2; python_version >= '3.8' and sys_platform =="
                " 'linux'"
            ),
            "test",
            [
                (
                    spec.Spec("py-black@24.2:"),
                    spec.Spec("platform=linux +test ^python@3.8:"),
                )
            ],
        ),
        (
            requirements.Requirement(
                "black>=24.2; python_version >= '3.8' or sys_platform =="
                " 'windows'"
            ),
            None,
            [
                (spec.Spec("py-black@24.2:"), spec.Spec("^python@3.8:")),
                (spec.Spec("py-black@24.2:"), spec.Spec("platform=windows")),
            ],
        ),
        (
            requirements.Requirement("black>=24.2; sys_platform != 'darwin'"),
            "extra",
            [
                (
                    spec.Spec("py-black@24.2:"),
                    spec.Spec("platform=linux +extra"),
                ),
                (
                    spec.Spec("py-black@24.2:"),
                    spec.Spec("platform=windows +extra"),
                ),
                (
                    spec.Spec("py-black@24.2:"),
                    spec.Spec("platform=freebsd +extra"),
                ),
                (
                    spec.Spec("py-black@24.2:"),
                    spec.Spec("platform=cray +extra"),
                ),
            ],
        ),
    ],
)
def test_convert_requirement(req, from_extra, expected):
    lookup = loading.PyPILookup()
    result = conversion_tools._convert_requirement(req, lookup, from_extra=from_extra)
    assert set(result) == set(expected)


def test_convert_requirement_invalid():
    lookup = loading.PyPILookup()
    result = conversion_tools._convert_requirement(
        requirements.Requirement("black>=4.2,<4"), lookup
    )
    assert isinstance(result, conversion_tools.ConversionError)

@pytest.mark.parametrize(
    "name, expected",
    [
        ("python", "python"),
        ("package", "py-package"),
        ("special_custom-pkg", "py-special-custom-pkg"),
        ("py-pkg", "py-pkg"),
        ("py-cpuinfo", "py-py-cpuinfo"),
    ],
)
def test_pkg_to_spack_name(name, expected):
    assert conversion_tools.pkg_to_spack_name(name) == expected

