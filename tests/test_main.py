"""Tests for main.py module."""
from __future__ import annotations

import pytest
from packaging import requirements
from spack import spec

from py2spack import loading, main




@pytest.mark.parametrize(
    "dep_list, expected",
    [
        ([(spec.Spec(), spec.Spec(), "")], True),
        ([(spec.Spec("pkg@4.2:"), spec.Spec(), "")], True),
        ([(spec.Spec("pkg@4.2:"), spec.Spec("^python@:3.11"), "")], True),
        (
            [
                (spec.Spec("pkg@4.2:"), spec.Spec("platform=linux"), ""),
                (spec.Spec("pkg@:4.3"), spec.Spec("platform=windows"), ""),
            ],
            True,
        ),
        (
            [
                (spec.Spec("pkg@4.2:"), spec.Spec("platform=windows"), ""),
                (spec.Spec("pkg@:4.3"), spec.Spec("platform=windows"), ""),
            ],
            True,
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("platform=windows"), ""),
                (spec.Spec("pkg@4.3:"), spec.Spec("platform=windows"), ""),
            ],
            False,
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("^python@:3.9"), ""),
                (spec.Spec("pkg@4.3:"), spec.Spec("^python@3.9:"), ""),
            ],
            False,
        ),
        (
            [
                (spec.Spec("pkg@:4.2"), spec.Spec("^python@:3.8"), ""),
                (spec.Spec("pkg@4.3:"), spec.Spec("^python@3.9:"), ""),
            ],
            True,
        ),
    ],
)
def test_check_dependency_satisfiability(dep_list, expected):
    assert main._check_dependency_satisfiability(dep_list) == expected


@pytest.mark.parametrize(
    "dep_spec, when_spec, expected",
    [
        (
            spec.Spec("py-typing-extensions@4.0.1:"),
            spec.Spec("@23.9: ^python@:3.10"),
            'depends_on("py-typing-extensions@4.0.1:", when="@23.9:'
            ' ^python@:3.10")',
        ),
        (
            spec.Spec("py-colorama@0.4.3:"),
            spec.Spec("platform=linux +colorama"),
            'depends_on("py-colorama@0.4.3:", when="platform=linux +colorama")',
        ),
    ],
)
def test_format_dependency(dep_spec, when_spec, expected):
    assert main._format_dependency(dep_spec, when_spec) == expected



# TODO: functions to test:
# _get_spack_version_hash_list
# _people_to_strings
# SpackPyPkg._get_dependencies
# SpackPyPkg._get_metadata
#
# these last to maybe already integration tests?
# PyProject.from_toml
# SpackPyPkg.convert_pkg
