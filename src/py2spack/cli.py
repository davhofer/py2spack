"""Script for command-line functionality `convert-package`."""

from __future__ import annotations

import argparse

from py2spack import core


def main() -> None:
    """Parses the command line arguments and calls convert_package.

    Example usage of CLI: "py2spack my_package --max-conversions 5
        --versions-per-package 8 --repo-path /path/to/repo --ignore package1 package2"
    """
    parser = argparse.ArgumentParser(
        description="CLI for converting a python package and its dependencies to Spack."
    )
    parser.add_argument("package", type=str, help="Name of the package")
    parser.add_argument(
        "--max-conversions",
        type=int,
        default=10,
        help="Maximum number of packages that are converted",
    )
    parser.add_argument(
        "--versions-per-package",
        type=int,
        default=10,
        help="Versions per package to be downloaded and converted",
    )
    parser.add_argument(
        "--repo-path", type=str, help="Path to local spack repository", default=None
    )
    parser.add_argument("--ignore", nargs="*", help="List of packages to ignore", default=None)

    args = parser.parse_args()

    core.convert_package(
        name=args.package,
        max_conversions=args.max_conversions,
        versions_per_package=args.versions_per_package,
        repo_path=args.repo_path,
        ignore=args.ignore,
    )


if __name__ == "__main__":
    main()
