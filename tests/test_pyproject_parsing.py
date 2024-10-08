"""Tests for pyproject_parsing.py module."""

from __future__ import annotations

from packaging import specifiers

from py2spack import pyproject_parsing


data = {
    "project": {
        "dependencies": ["package1>=1.0", "package2==2.0"],
        "optional-dependencies": {"extra": ["extra-package1>=1.0", "extra-package2==2.0"]},
        "license": {"text": "MIT"},
        "classifiers": ["License :: OSI Approved :: MIT License"],
        "requires-python": ">=3.6",
        "urls": {
            "Homepage": "https://example.com",
            "Repository": "https://github.com/example/repo",
        },
        "authors": [{"name": "Author One", "email": "author1@example.com"}],
    },
    "build-system": {
        "requires": ["setuptools>=40.8.0", "wheel"],
        "build-backend": "setuptools.build_meta",
    },
}
fetcher = pyproject_parsing.DataFetcher(data)


def test_contains() -> None:
    """Unit tests for method."""
    assert "project" in fetcher
    assert "project.dependencies" in fetcher
    assert "project.optional-dependencies.extra" in fetcher
    assert "nope" not in fetcher


def test_get() -> None:
    """Unit tests for method."""
    assert fetcher.get("project.dependencies") == [
        "package1>=1.0",
        "package2==2.0",
    ]
    assert fetcher.get("project.license.text") == "MIT"


def test_get_str() -> None:
    """Unit tests for method."""
    assert fetcher.get_str("project.license.text") == "MIT"
    assert fetcher.get_str("project.nonexistent") is None
    assert isinstance(fetcher.get_str("project.dependencies"), pyproject_parsing.ConfigurationError)


def test_get_list() -> None:
    """Unit tests for method."""
    assert fetcher.get_list("project.dependencies") == [
        "package1>=1.0",
        "package2==2.0",
    ]
    assert fetcher.get_list("project.nonexistent") == []
    assert isinstance(
        fetcher.get_list("project.license.text"), pyproject_parsing.ConfigurationError
    )


def test_get_dict() -> None:
    """Unit tests for method."""
    assert fetcher.get_dict("project.urls") == {
        "Homepage": "https://example.com",
        "Repository": "https://github.com/example/repo",
    }

    assert fetcher.get_dict("project.nonexistent") == {}
    assert isinstance(
        fetcher.get_dict("project.license.text"), pyproject_parsing.ConfigurationError
    )


def test_get_people() -> None:
    """Unit tests for method."""
    assert fetcher.get_people("project.authors") == [("Author One", "author1@example.com")]
    assert fetcher.get_people("project.nonexistent") == []
    assert isinstance(
        fetcher.get_people("project.license.text"), pyproject_parsing.ConfigurationError
    )


def test_get_dependencies() -> None:
    """Unit tests for method."""
    deps, errs = fetcher.get_dependencies()
    assert [str(d) for d in deps] == ["package1>=1.0", "package2==2.0"]
    assert errs == []

    dep_err_fetcher = pyproject_parsing.DataFetcher(
        {"project": {"dependencies": ["package1>=1.0", "package2??2.0"]}}
    )
    deps, errs = dep_err_fetcher.get_dependencies()
    assert [str(d) for d in deps] == ["package1>=1.0"]
    assert len(errs) == 1
    assert isinstance(errs[0], pyproject_parsing.ConfigurationError)


def test_get_optional_dependencies() -> None:
    """Unit tests for method."""
    deps, errs = fetcher.get_optional_dependencies()
    assert [str(d) for d in deps["extra"]] == [
        "extra-package1>=1.0",
        "extra-package2==2.0",
    ]
    assert errs == []


def test_get_license() -> None:
    """Unit tests for method."""
    assert fetcher.get_license() == "MIT"
    # Simulate a scenario where the license is extracted from classifiers
    fetcher_with_classifier = pyproject_parsing.DataFetcher(
        {"project": {"classifiers": ["License :: OSI Approved :: MIT License"]}}
    )
    assert fetcher_with_classifier.get_license() == "MIT License"


def test_get_requires_python() -> None:
    """Unit tests for method."""
    requires_python = fetcher.get_requires_python()
    assert isinstance(requires_python, specifiers.SpecifierSet)
    assert str(requires_python) == ">=3.6"
    # Simulate invalid requires-python field
    invalid_fetcher = pyproject_parsing.DataFetcher({"project": {"requires-python": "invalid"}})
    assert isinstance(invalid_fetcher.get_requires_python(), pyproject_parsing.ConfigurationError)


def test_get_build_requires() -> None:
    """Unit tests for method."""
    build_reqs, build_errs = fetcher.get_build_requires()
    assert [str(r) for r in build_reqs] == ["setuptools>=40.8.0", "wheel"]
    assert build_errs == []


def test_get_build_backend() -> None:
    """Unit tests for method."""
    assert fetcher.get_build_backend() == "setuptools.build_meta"
    # Simulate a scenario where build-backend is missing
    backend_missing_fetcher = pyproject_parsing.DataFetcher({"build-system": {}})
    assert backend_missing_fetcher.get_build_backend() is None


def test_get_homepage() -> None:
    """Unit tests for method."""
    assert fetcher.get_homepage() == "https://example.com"
    # Simulate a scenario where homepage is missing
    no_homepage_fetcher = pyproject_parsing.DataFetcher({"project": {"urls": {}}})
    assert no_homepage_fetcher.get_homepage() is None
