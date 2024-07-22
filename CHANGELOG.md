# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Parser for pyproject.toml files.
- Conversion of dependencies and markers from packaging to spack using functionality from [pypi-to-spack-package](https://github.com/spack/pypi-to-spack-package).
- Multiple pyproject.toml files can now be converted to a single package.py file, combining the various dependencies for different versions.
- Dump package.py to console or file.
- Downloader for sdist archives from PyPI
- Convert packages to Spack directly from PyPI using SpackPyPkg.convert_pkg()

### Removed

- old files and directories.
