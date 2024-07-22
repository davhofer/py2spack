# CSCS Internship: Automating Spack Package Generation for Python Packages

Github repository for the CSCS internship project with the goal of developing a Python tool for automatically generating Spark package recipes based on existing Python packages, with the ability to handle direct and transitive dependencies and flexible versions.

## Important links

- [Detailed Project Description](<CSCS Internship Project Description.md>)
- [Changelog](CHANGELOG.md)
- [Wiki](https://github.com/davhofer/py2spack/wiki)

## Installation

The package is still in development and not yet published to PyPI. It can however be installed manually.

1. [Install Spack](https://spack.readthedocs.io/en/latest/getting_started.html) on your system.
2. Make sure that the environment variable `SPACK_ROOT` is set, e.g. `export SPACK_ROOT=/home/<user>/spack`.
3. Either execute the following in your active shell or place it in your shell rc file (e.g. `.bashrc`, `.zshrc`):

   ```bash
   export PYTHONPATH=$SPACK_ROOT/lib/spack/external/_vendoring:$SPACK_ROOT/lib/spack/external:$SPACK_ROOT/lib/spack:$PYTHONPATH
   ```

   If you place it in the rc file, make sure `$SPACK_ROOT` is set when the file is executed or replace it with the explicit path.

4. Clone the [py2spack github repository](https://github.com/davhofer/py2spack):
   ```bash
   git clone git@github.com:davhofer/py2spack.git
   ```
5. `cd py2spack`
6. Install the package:
   ```bash
   python -m pip install .
   ```

## Running tests

After installing the package, the tests can be run from the project root directory as follows:

```
python -m pytest
```

## Usage

> Work in progress

Currently, the main file can be executed to run through an example:

```
python src/py2spack/main.py
```

This will build a `package.py` from the `.toml` files in `example_pyprojects/black/` and print the output to the console.
