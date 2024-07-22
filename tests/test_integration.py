"""Integration tests for py2spack package."""
from __future__ import annotations

import sys

from py2spack import loading, main


def test_e2e_uninterrupted1():
    lookup = loading.PyPILookup()
    spack_pkg = main.SpackPyPkg.convert_pkg("black", lookup, last_n_versions=5)

    assert spack_pkg is not None

    spack_pkg.print_package(outfile=sys.stdout)

    assert True


def test_e2e_uninterrupted2():
    lookup = loading.PyPILookup()
    spack_pkg = main.SpackPyPkg.convert_pkg("tqdm", lookup, last_n_versions=5)

    assert spack_pkg is not None

    spack_pkg.print_package(outfile=sys.stdout)

    assert True


def test_e2e_uninterrupted3():
    lookup = loading.PyPILookup()
    spack_pkg = main.SpackPyPkg.convert_pkg("pandas", lookup, last_n_versions=5)

    assert spack_pkg is not None

    spack_pkg.print_package(outfile=sys.stdout)

    assert True
