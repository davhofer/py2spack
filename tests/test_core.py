"""Tests for core.py module."""

from __future__ import annotations

import os
import pathlib

import pytest
from spack import spec

from py2spack import core, package_providers


def test_format_types():
    assert core._format_types({"build"}) == '"build"'
    assert core._format_types({"run", "build"}) == '("build", "run")'


def test_people_to_strings():
    parsed_people = [
        (None, None),
        ("name", None),
        (None, "hello@email.com"),
        ("name", "name@email.com"),
    ]
    expected = ["name", "hello@email.com", "name, name@email.com"]

    assert core._people_to_strings(parsed_people) == expected


def test_convert_single():
    provider = package_providers.PyPIProvider()
    assert isinstance(core._convert_single("black", provider, num_versions=4), core.SpackPyPkg)

    assert isinstance(core._convert_single("tqdm", provider, num_versions=4), core.SpackPyPkg)


def test_package_exists_in_spack():
    repo = pathlib.Path.cwd() / "tests" / "test_data" / "test_repo"

    assert core._package_exists_in_spack("py-test-pkg", repo)

    assert not core._package_exists_in_spack("not-a-package", repo)


def test_get_spack_repo1():
    repo = pathlib.Path.cwd() / "tests" / "test_data" / "test_repo"

    assert core._get_spack_repo(str(repo)) == repo


def test_get_spack_repo2():
    if "SPACK_ROOT" in os.environ:
        spack_dir = pathlib.Path(os.environ["SPACK_ROOT"])
        builtin_repo = spack_dir / "var" / "spack" / "repos" / "builtin"
        if builtin_repo.is_dir():
            assert core._get_spack_repo(None) == builtin_repo


def write_package_to_repo():
    pass  # TODO


def test_convert_package():
    # TODO: test this here? basically end to end. move to integration
    pass  # TODO


@pytest.mark.parametrize(
    ("dep_list", "expected"),
    [
        ([(spec.Spec(), spec.Spec(), {})], []),
        ([(spec.Spec("pkg@4.2:"), spec.Spec(), {})], []),
        ([(spec.Spec("pkg@4.2:"), spec.Spec("^python@:3.11"), {})], []),
        (
            [
                (spec.Spec("pkg@4.2:"), spec.Spec("platform=linux"), {}),
                (spec.Spec("pkg@:4.3"), spec.Spec("platform=windows"), {}),
            ],
            [],
        ),
        (
            [
                (spec.Spec("pkg@4.2:"), spec.Spec("platform=windows"), {}),
                (spec.Spec("pkg@:4.3"), spec.Spec("platform=windows"), {}),
            ],
            [],
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("platform=windows"), {}),
                (spec.Spec("pkg@4.3:"), spec.Spec("platform=windows"), {}),
            ],
            [
                core.DependencyConflictError(
                    'depends_on("pkg@:4.2", when="platform=windows") and depends_on("pkg@4.3:", when="platform=windows")'
                )
            ],
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("^python@:3.9"), {}),
                (spec.Spec("pkg@4.3:"), spec.Spec("^python@3.9:"), {}),
            ],
            [
                core.DependencyConflictError(
                    'depends_on("pkg@:4.2", when="^python@:3.9") and depends_on("pkg@4.3:", when="^python@3.9:")'
                )
            ],
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("^python@:3.8"), {}),
                (spec.Spec("pkg@4.3:"), spec.Spec("^python@3.9:"), {}),
            ],
            [],
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("@:2.5 ^python@:3.9"), {}),
                (spec.Spec("pkg@4.3:"), spec.Spec("@2: ^python@3.9:"), {}),
            ],
            [
                core.DependencyConflictError(
                    'depends_on("pkg@:4.2", when="@:2.5 ^python@:3.9") and depends_on("pkg@4.3:", when="@2: ^python@3.9:")'
                )
            ],
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("@:2.5 ^python@:3.9 platform=windows"), {}),
                (spec.Spec("pkg@4.3:"), spec.Spec("@2: ^python@3.9: platform=linux"), {}),
            ],
            [],
        ),
    ],
)
def test_find_dependency_satisfiability_conflicts(
    dep_list: list[tuple[spec.Spec, spec.Spec, set[str]]],
    expected: list[core.DependencyConflictError],
) -> None:
    """Unit tests for method."""
    assert core._find_dependency_satisfiability_conflicts(dep_list) == expected


@pytest.mark.parametrize(
    ("dep_spec", "when_spec", "expected"),
    [
        (
            spec.Spec("py-typing-extensions@4.0.1:"),
            spec.Spec("@23.9: ^python@:3.10"),
            'depends_on("py-typing-extensions@4.0.1:", when="@23.9:' ' ^python@:3.10")',
        ),
        (
            spec.Spec("py-colorama@0.4.3:"),
            spec.Spec("platform=linux +colorama"),
            'depends_on("py-colorama@0.4.3:", when="platform=linux +colorama")',
        ),
    ],
)
def test_format_dependency(dep_spec: spec.Spec, when_spec: spec.Spec, expected: str) -> None:
    """Unit tests for method."""
    assert core._format_dependency(dep_spec, when_spec) == expected


# TODO @davhofer: functions to test:
# _get_spack_version_hash_list
# _people_to_strings
# SpackPyPkg._get_dependencies
# SpackPyPkg._get_metadata
#
# these last to maybe already integration tests?
# PyProject.from_toml
# SpackPyPkg.convert_pkg
