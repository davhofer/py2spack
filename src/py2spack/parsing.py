"""Utilities for parsing pyproject.toml files.

Parts of the code adapted from https://github.com/pypa/pyproject-metadata.
"""
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
import typing
from typing import Any

from packaging import requirements, specifiers


LICENSE_IDENTIFIER_LEN = 250


if typing.TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping


class ConfigurationError(Exception):
    """Error in the backend metadata."""

    def __init__(self, msg: str, *, key: str | None = None):
        """Initialize error."""
        super().__init__(msg)
        self._key = key

    @property
    def key(self) -> str | None:  # pragma: no cover
        """Get key."""
        return self._key


def _validate_license_txt(license_text: str) -> str | ConfigurationError:
    if len(license_text) > LICENSE_IDENTIFIER_LEN:
        msg = "License text appears to be full license content instead of " "license identifier"
        return ConfigurationError(msg, key="project.license")
    return license_text


class DataFetcher:
    """Fetcher class for parsing and extracting the various metadata fields."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        """Initialize DataFetcher with raw toml data (dictionary)."""
        self._data = data

    def __contains__(self, key: Any) -> bool:
        """Check if DataFetcher contains the (nested) key.

        Examples for key:
            'project'
            'project.dependencies'
            'project.optional-dependencies.extra'
        """
        if not isinstance(key, str):
            return False
        val = self._data
        try:
            for part in key.split("."):
                val = val[part]
        except KeyError:
            return False
        return True

    def get(self, key: str) -> Any:
        """Get value for a specific (multi-level) key."""
        val = self._data
        for part in key.split("."):
            val = val[part]
        return val

    def get_str(self, key: str) -> str | None | ConfigurationError:
        """Get string."""
        try:
            val = self.get(key)
            if not isinstance(val, str):
                msg = f'Field "{key}" has an invalid type, ' f'expecting a string (got "{val}")'
                return ConfigurationError(msg, key=key)
            return val
        except KeyError:
            return None

    def get_list(self, key: str) -> list[str] | ConfigurationError:
        """Get list of strings."""
        try:
            val = self.get(key)
            if not isinstance(val, list):
                msg = (
                    f'Field "{key}" has an invalid type, expecting a list '
                    f'of strings (got "{val}")'
                )
                return ConfigurationError(msg, key=val)
            for item in val:
                if not isinstance(item, str):
                    msg = (
                        f'Field "{key}" contains item with invalid type,'
                        f' expecting a string (got "{item}")'
                    )
                    return ConfigurationError(msg, key=key)
            return val
        except KeyError:
            return []

    def get_dict(self, key: str) -> dict[str, str] | ConfigurationError:
        """Get dict of string keys and values."""
        try:
            val = self.get(key)
            if not isinstance(val, dict):
                msg = (
                    f'Field "{key}" has an invalid type, expecting a dictionary'
                    f' of strings (got "{val}")'
                )
                return ConfigurationError(msg, key=key)
            for subkey, item in val.items():
                if not isinstance(item, str):
                    msg = (
                        f'Field "{key}.{subkey}" has an invalid type, expecting'
                        f' a string (got "{item}")'
                    )
                    return ConfigurationError(msg, key=f"{key}.{subkey}")
            return val
        except KeyError:
            return {}

    def get_people(self, key: str) -> list[tuple[str | None, str | None]] | ConfigurationError:
        """Used for parsing the 'authors' and 'maintainers' fields."""
        try:
            val = self.get(key)
            if not (
                isinstance(val, list)
                and all(isinstance(x, dict) for x in val)
                and all(
                    isinstance(item, str)
                    for items in [_dict.values() for _dict in val]
                    for item in items
                )
            ):
                msg = (
                    f'Field "{key}" has an invalid type, expecting a list of '
                    'dictionaries containing the "name" and/or "email" keys '
                    f'(got "{val}")'
                )
                return ConfigurationError(msg, key=key)
            return [(entry.get("name"), entry.get("email")) for entry in val]
        except KeyError:
            return []

    def get_dependencies(
        self,
    ) -> tuple[list[requirements.Requirement], list[ConfigurationError]] | ConfigurationError:
        """Parses the 'dependencies' field."""
        requirement_strings = self.get_list("project.dependencies")

        if isinstance(requirement_strings, ConfigurationError):
            return requirement_strings

        requirements_list: list[requirements.Requirement] = []
        requirement_errors: list[ConfigurationError] = []
        for req in requirement_strings:
            # TODO @davhofer: the requirements here of course SHOULD be formatted correctly...  # noqa: TD003
            # but what if they are not
            try:
                requirements_list.append(requirements.Requirement(req))
            except requirements.InvalidRequirement:  # noqa: PERF203
                msg = (
                    'Field "project.dependencies" contains an invalid PEP 508 '
                    f'requirement string "{req}"'
                )
                requirement_errors.append(ConfigurationError(msg, key="project.dependencies"))
        return (requirements_list, requirement_errors)

    def get_optional_dependencies(
        self,
    ) -> (
        tuple[dict[str, list[requirements.Requirement]], list[ConfigurationError]]
        | ConfigurationError
    ):
        """Parses the 'optional-dependencies' field."""
        try:
            val = self.get("project.optional-dependencies")
        except KeyError:
            return {}, []

        if not isinstance(val, dict):
            msg = (
                'Field "project.optional-dependencies" has an invalid type, '
                "expecting a dictionary of PEP 508 requirement strings "
                f'(got "{val}")'
            )
            return ConfigurationError(msg, key="project.optional-dependences")

        requirements_dict: dict[str, list[requirements.Requirement]] = {}
        requirement_errors: list[ConfigurationError] = []
        for extra, requirements_list in val.copy().items():
            if not isinstance(extra, str):
                msg = (
                    "Field project.optional-dependencies contains extra of "
                    f"invalid type, expected string (got '{extra}')"
                )
                requirement_errors.append(
                    ConfigurationError(msg, key="project.optional-dependencies")
                )
                continue

            if not isinstance(requirements_list, list):
                msg = (
                    f'Field "project.optional-dependencies.{extra}" has an '
                    f"invalid type, expecting a dictionary PEP 508 requirement "
                    f'strings (got "{requirements_list}")'
                )
                requirement_errors.append(
                    ConfigurationError(msg, key="project.optional-dependencies")
                )
                continue

            requirements_dict[extra] = []
            for req in requirements_list:
                if not isinstance(req, str):
                    msg = (
                        f'Field "project.optional-dependencies.{extra}" has an '
                        "invalid type, expecting a PEP 508 requirement string "
                        f'(got "{req}")'
                    )
                    requirement_errors.append(
                        ConfigurationError(msg, key="project.optional-dependencies")
                    )
                    continue
                try:
                    requirements_dict[extra].append(requirements.Requirement(req))
                except requirements.InvalidRequirement:
                    msg = (
                        f'Field "project.optional-dependencies.{extra}" '
                        "contains an invalid PEP 508 requirement string "
                        f'"{req}"'
                    )
                    requirement_errors.append(
                        ConfigurationError(msg, key="project.optional-dependencies")
                    )
                    continue
        return (dict(requirements_dict), requirement_errors)

    def get_license(self) -> str | None | ConfigurationError:
        """Tries to get the project license.

        Parses the 'license' field. If the license is not specified there,
        tries to parse 'classifiers' field and read license from it.
        """
        _license = self._get_license_from_field()

        if isinstance(_license, str):
            return _license

        classifier_license = self._get_license_from_classifiers()
        if classifier_license:
            return classifier_license

        return _license

    def _get_license_from_field(self) -> str | None | ConfigurationError:
        """Parses the 'license' field."""
        if "project.license" not in self:
            return None

        # license SHOULD be dict but sometimes is specified directly as a string
        _license = self.get_dict("project.license")
        license_str = self.get_str("project.license")

        license_text = ""
        if isinstance(license_str, str):
            license_text = license_str

        elif isinstance(_license, dict):
            text = self.get_str("project.license.text")

            if isinstance(text, str):
                license_text = text

        if license_text:
            return _validate_license_txt(license_text)

        return ConfigurationError('Unable to get license text from "project.license" field')

    def _get_license_from_classifiers(self) -> str | None:
        """Parses the 'classifiers' field, tries to exract license from it."""
        # license can also be specified in classifiers
        classifiers = self.get_list("project.classifiers")
        if isinstance(classifiers, list):
            # get all classifiers detailing licenses
            license_classifiers = list(filter(lambda x: x.startswith("License"), classifiers))
            # for each license classifier, split by "::" and take the
            # last substring (and strip unnecessary whitespace)
            licenses = [x.split("::")[-1].strip() for x in license_classifiers]
            if len(licenses) > 0:
                # AND is more restrictive => be safe (?)
                return " AND ".join(licenses)
        return None

    def get_requires_python(
        self,
    ) -> specifiers.SpecifierSet | ConfigurationError:
        """Parses the 'requires-python' field."""
        parsed_requires_python = self.get_str("project.requires-python")
        if isinstance(parsed_requires_python, str):
            try:
                return specifiers.SpecifierSet(parsed_requires_python)
            except specifiers.InvalidSpecifier:
                msg = (
                    'Field "project.requires-python" contains an invalid PEP '
                    f'508 requirement string "{parsed_requires_python}"'
                )
                return ConfigurationError(msg, key="project.requires-python")

        # if parsed_requires_python is None or ConfigurationError
        return parsed_requires_python

    def get_build_requires(
        self,
    ) -> tuple[list[requirements.Requirement], list[ConfigurationError]] | ConfigurationError:
        """Parses the 'build-system.requires' field."""
        requirement_strings = self.get_list("build-system.requires")

        if isinstance(requirement_strings, ConfigurationError):
            return requirement_strings

        requirements_list: list[requirements.Requirement] = []
        requirement_errors: list[ConfigurationError] = []
        for req in requirement_strings:
            try:
                requirements_list.append(requirements.Requirement(req))
            except requirements.InvalidRequirement as e:  # noqa: PERF203
                msg = (
                    'Field "build-system.requires" contains an invalid PEP 508 '
                    f'requirement string "{req}" ("{e}")'
                )
                requirement_errors.append(ConfigurationError(msg, key="build-system.requires"))
        return (requirements_list, requirement_errors)

    def get_build_backend(self) -> str | None | ConfigurationError:
        """Parses the 'build-system.build-backend' field."""
        return self.get_str("build-system.build-backend")

    def get_homepage(self) -> str | None | ConfigurationError:
        """Parses the 'urls' field and tries to extract the homepage."""
        parsed_urls = self.get_dict("project.urls")
        if isinstance(parsed_urls, dict):
            for key in ["Homepage", "Repository", "Github", "Wiki"]:
                if key in parsed_urls:
                    return parsed_urls[key]

                if key.lower() in parsed_urls:
                    return parsed_urls[key.lower()]
            return None
        return parsed_urls


class License(typing.NamedTuple):
    """Represents the project license."""

    text: str
    file: pathlib.Path | None


class Readme(typing.NamedTuple):
    """Represents the project README."""

    text: str
    file: pathlib.Path | None
    content_type: str


def valid_pypi_name(name: str) -> bool:
    """Checks whether 'name' is a valid pypi name."""
    return re.match(r"^([A-Z0-9]|[A-Z0-9][A-Z0-9._-]*[A-Z0-9])$", name, re.IGNORECASE) is not None
