"""py2spack package.

This package allows converting standard python packages to Spack packages.
"""

from .parse_pyproject import SpackPyPkg

__version__ = "0.0.1"

__all__ = ["SpackPyPkg"]
