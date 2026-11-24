"""Build the hash-verified native reader into an explicit local/image prefix."""

import argparse
import ctypes
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "3.8.10"
SHA256 = "56cad765459d5ee25a3b761f90c47d99379d28297fbfb72d908880d6b875fb96"
SOURCE_URL = (
    f"https://github.com/libarchive/libarchive/releases/download/v{VERSION}/"
    f"libarchive-{VERSION}.tar.xz"
)
DISABLED = (
    "--disable-static",
    "--disable-bsdtar",
    "--disable-bsdcpio",
    "--disable-bsdcat",
    "--disable-bsdunzip",
    "--disable-acl",
    "--disable-xattr",
    "--disable-rpath",
    "--without-bz2lib",
    "--without-lzma",
    "--without-zstd",
    "--without-lz4",
    "--without-openssl",
    "--without-mbedtls",
    "--without-nettle",
    "--without-xml2",
    "--without-expat",
    "--without-lzo2",
    "--without-libb2",
    "--without-md",
    "--without-bsdxml",
    "--without-iconv",
)


def verify_library(path: Path) -> None:
    library = ctypes.CDLL(str(path))
    library.archive_version_number.restype = ctypes.c_int
    library.archive_zlib_version.restype = ctypes.c_char_p
    if library.archive_version_number() != 3008010 or not library.archive_zlib_version():
        raise SystemExit("Expected libarchive 3.8.10 with zlib support")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path)
    args = parser.parse_args()
    prefix = args.prefix.absolute()
    args.build_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="libarchive-", dir=args.build_dir) as temporary:
        work = Path(temporary).absolute()
        archive = work / "source.tar.xz"
        if args.source_archive:
            shutil.copyfile(args.source_archive, archive)
        else:
            with (
                urllib.request.urlopen(SOURCE_URL, timeout=60) as response,
                archive.open("wb") as target,
            ):
                shutil.copyfileobj(response, target)
        with archive.open("rb") as source_file:
            digest = hashlib.file_digest(source_file, "sha256").hexdigest()
        if digest != SHA256:
            raise SystemExit("libarchive source digest mismatch")
        with tarfile.open(archive) as source:
            source_epoch = max(int(member.mtime) for member in source.getmembers())
            source.extractall(work, filter="data")
        environment = {
            **os.environ,
            "SOURCE_DATE_EPOCH": str(source_epoch),
            "CFLAGS": f"-O2 -g0 -ffile-prefix-map={work}=.",
        }
        subprocess.run(
            [
                str(work / f"libarchive-{VERSION}" / "configure"),
                f"--prefix={prefix}",
                *DISABLED,
                "--with-zlib",
            ],
            cwd=work,
            env=environment,
            check=True,
        )
        subprocess.run(["make", "-j2"], cwd=work, env=environment, check=True)
        subprocess.run(["make", "install"], cwd=work, env=environment, check=True)
        shutil.copyfile(work / f"libarchive-{VERSION}" / "COPYING", prefix / "COPYING")
    library = prefix / "lib" / "libarchive.so.13.8.10"
    if not library.is_file():
        raise SystemExit("Expected libarchive shared library was not installed")
    verify_library(library)
    print(f"LIBARCHIVE={library}")


if __name__ == "__main__":
    main()
