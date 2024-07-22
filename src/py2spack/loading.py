"""Utils for downloading packages from PyPI and opening the pyproject.tomls."""

from __future__ import annotations

import io
import tarfile
from typing import Any

import requests
import tomli
from packaging import version as vn


KNOWN_ARCHIVE_FORMATS = [
    ".tar",
    ".tar.gz",
    ".tar.bz2",
    ".gz",
    ".xz",
    ".bz2",
]

HTTP_STATUS_SUCCESS = 200
HTTP_STATUS_NOT_FOUND = 404


class APIError(Exception):
    """Error during version lookup or querying of the PyPI JSON API."""

    def __init__(
        self,
        msg: str,
    ):
        """Initialize error."""
        super().__init__(msg)


def _acceptable_version(version: str) -> vn.Version | None:
    """Check whether version string can be parsed and has correct format."""
    try:
        v = vn.parse(version)
        # do not support post releases of prereleases etc.
        if v.pre and (v.post or v.dev or v.local):
            return None
        return v
    except vn.InvalidVersion:
        return None


class PyPILookup:
    """Performs PyPI API calls and caches package versions.

    The full API response (including available files and metadata) is not cached
    due to its larger size and sparser usage.
    """

    def __init__(self) -> None:
        """Initialize empty PyPILookup."""
        # cache for package name and corresponding version list
        self.version_cache: dict[str, list[vn.Version]] = {}

    def _get(self, name: str) -> dict | APIError:
        """Load info for the available distribution files from PyPI.

        Available versions are cached.
        """
        r = requests.get(
            f"https://pypi.org/simple/{name}/",
            headers={"Accept": "application/vnd.pypi.simple.v1+json"},
            timeout=10,
        )
        if r.status_code != HTTP_STATUS_SUCCESS:
            if r.status_code == HTTP_STATUS_NOT_FOUND:
                msg = f"Package {name} not found on PyPI (status code 404)"
                return APIError(msg)

            msg = (
                f"Error when querying JSON API (status code {r.status_code})."
                f" Response: {r.text}"
            )
            return APIError(msg)

        data: dict = r.json()
        versions = data["versions"]

        # parse and sort versions
        parsed_versions = sorted({vv for v in versions if (vv := _acceptable_version(v))})

        self.version_cache[name] = parsed_versions

        return data

    def get_versions(self, name: str) -> list[vn.Version]:
        """Get acceptable versions for package (from cache if possible)."""
        if name not in self.version_cache:
            data = self._get(name)

            if isinstance(data, APIError):
                self.version_cache[name] = []

        return self.version_cache[name]

    def get_files(self, name: str, last_n_versions: int = -1) -> list[dict[Any, Any]] | APIError:
        """Get metadata for available distribution files from PyPI.

        Returns:
            - List of dictionaries including filename, download url, version,
            sdist archive extension, and archive sha256 hash.
            If an error occurs, returns APIError object.
        """
        data = self._get(name)
        if isinstance(data, APIError):
            return data
        files = data["files"]

        # for now we only support tarball archives like .tar.gz
        files_known_format = [f for f in files if _known_archive_format(f["filename"])]

        if len(files_known_format) == 0:
            msg = (
                "No files with known archive format found (note: wheel file"
                " parsing not supported)"
            )
            return APIError(msg)

        # for each file, get the filename, url, version, extension, and sha256
        # TODO @davhofer: in case of an error, skip the file or return the error?  # noqa: TD003
        files_parsed: list[dict[str, str]] = []
        for f in files_known_format:
            filename = f["filename"]
            archive_ext = _parse_archive_extension(filename)
            if isinstance(archive_ext, APIError):
                continue

            v = _parse_version(filename, name, archive_ext)

            if v is None:
                continue

            try:
                sha256 = f["hashes"]["sha256"]
            except KeyError:
                continue

            files_parsed.append(
                {
                    "filename": filename,
                    "url": f["url"],
                    "version": v,
                    "extension": archive_ext,
                    "hash": sha256,
                }
            )

        if not files_parsed:
            return APIError("No valid files found")

        # if argument is -1, return all versions
        if last_n_versions == -1:
            return files_parsed

        return files_parsed[-last_n_versions:]


def _parse_archive_extension(filename: str) -> str | APIError:
    extension_list = [ext for ext in KNOWN_ARCHIVE_FORMATS if filename.endswith(ext)]

    if len(extension_list) == 0:
        # we return an API error here because the filenames are obtained through
        # the API and the function is used during the API lookup process
        msg = f"Extension not recognized for: {filename}"
        return APIError(msg)

    if len(extension_list) == 1:
        return extension_list[0]
    # get the longest matching extension, e.g. .tar.gz instead of .gz
    return max(extension_list, key=len)


def _parse_version(filename: str, pkg_name: str, archive_ext: str) -> vn.Version | None:
    """Parse version from filename and check correct formatting."""
    prefix = pkg_name + "-"
    if not (filename.startswith(prefix) and filename.endswith(archive_ext)):
        return None
    version_str = filename[len(prefix) : -len(archive_ext)]
    try:
        parsed_version: vn.Version = vn.parse(version_str)
        return parsed_version

    except vn.InvalidVersion:
        return None


def _known_archive_format(filename: str) -> bool:
    return any(filename.endswith(ext) for ext in KNOWN_ARCHIVE_FORMATS)


def _download_sdist(url: str) -> io.BytesIO | APIError:
    """Download source distribution from url as BytesIO object (in memory)."""
    response = requests.get(url)
    if response.status_code == HTTP_STATUS_SUCCESS:
        return io.BytesIO(response.content)

    filename = url.split("/")[-1]
    msg = f"Failed to download sdist {filename}," f" status code: {response.status_code}"
    return APIError(msg)


def _extract_from_tar(file_like_object: io.BytesIO, directory_name: str) -> dict | APIError:
    """Extract pyproject.toml from tar archive.

    The top level directory name inside the archive must be given explicitly.
    Contents are returned as a dictionary.
    """
    # works for .gz, .bz2, .xz, ...
    try:
        with tarfile.open(fileobj=file_like_object, mode="r:*") as tar:
            member = tar.getmember(f"{directory_name}/pyproject.toml")
            f = tar.extractfile(member)

            if f is not None:
                pyproject_content = f.read().decode("utf-8")
                return tomli.loads(pyproject_content)

    except (OSError, tarfile.TarError, UnicodeDecodeError, tomli.TOMLDecodeError, KeyError) as e:
        msg = f"Exception {type(e)}: {e}"
        return APIError(msg)

    return APIError("Could not extract pyproject.toml from sdist")


# TODO @davhofer: handle zip archives  # noqa: TD003
def try_load_toml(url: str, directory_name: str, archive_ext: str) -> dict | APIError:
    """Load sdist from url and extract pyproject.toml contents."""
    sdist_file_obj = _download_sdist(url)
    if isinstance(sdist_file_obj, APIError):
        return sdist_file_obj

    if archive_ext in KNOWN_ARCHIVE_FORMATS:
        return _extract_from_tar(sdist_file_obj, directory_name)

    msg = "Failed to open sdist, format must be tarball archive (.tar.gz," " .bz2, etc.)"

    return APIError(msg)
