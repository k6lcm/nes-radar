#!/usr/bin/env python3
"""Build, smoke-test, archive, and hash NES Radar Server distributions."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
RELEASE = PROJECT / "artifacts"
SPEC = PROJECT / "packaging" / "nes-radar-server.spec"
VERSION = (PROJECT / "VERSION").read_text(encoding="utf-8").strip()
PRODUCT = f"NES-Radar-Server-{VERSION}"
PORTABLE_FILES = (
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "requirements.txt",
    "start_nes_radar_server.py",
    "start_nes_radar_server.command",
    "start_nes_radar_server.bat",
    "src",
    "licenses",
)
TARGETS = {
    ("Darwin", "x86_64"): "macos-universal",
    ("Darwin", "arm64"): "macos-universal",
    ("Windows", "AMD64"): "windows-x64",
    ("Windows", "x86_64"): "windows-x64",
    ("Linux", "x86_64"): "linux-x86_64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Linux", "arm64"): "linux-arm64",
}


def copy_item(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def populate_portable_source(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in PORTABLE_FILES:
        copy_item(PROJECT / relative, destination / relative)
    launcher = destination / "start_nes_radar_server.command"
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_binary_launcher(destination: Path, target: str) -> None:
    if target == "windows-x64":
        launcher = destination / "start_nes_radar_server.bat"
        launcher.write_text(
            '@echo off\ncd /d "%~dp0"\nnes-radar-server.exe %*\n',
            encoding="ascii",
        )
        return
    suffix = ".command" if target == "macos-universal" else ".sh"
    launcher = destination / f"start_nes_radar_server{suffix}"
    launcher.write_text(
        '#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\nexec ./nes-radar-server "$@"\n',
        encoding="ascii",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def zip_tree(source: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source.parent)
            info = zipfile.ZipInfo.from_file(path, relative.as_posix())
            info.date_time = (2026, 7, 31, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as handle:
                output.writestr(info, handle.read(), compresslevel=9)


def tar_tree(source: Path, archive: Path) -> None:
    with tarfile.open(archive, "w:gz", compresslevel=9) as output:
        for path in sorted((source, *source.rglob("*"))):
            arcname = path.relative_to(source.parent)
            info = output.gettarinfo(str(path), str(arcname))
            info.mtime = 1785456000
            if path.is_file():
                with path.open("rb") as handle:
                    output.addfile(info, handle)
            else:
                output.addfile(info)


def write_hashes() -> None:
    lines = []
    for path in sorted(RELEASE.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.name}\n")
    (RELEASE / "SHA256SUMS").write_text("".join(lines), encoding="ascii")


def build_source() -> Path:
    RELEASE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nes-radar-source-") as temporary:
        root = Path(temporary) / f"{PRODUCT}-python-source"
        populate_portable_source(root)
        archive = RELEASE / f"{PRODUCT}-python-source.zip"
        zip_tree(root, archive)
    write_hashes()
    return archive


def native_target() -> str:
    key = (platform.system(), platform.machine())
    try:
        return TARGETS[key]
    except KeyError as error:
        raise SystemExit(f"unsupported build host: {key[0]} {key[1]}") from error


def run_checked(command: list[str], **kwargs) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, **kwargs)


def build_binary(target: str | None) -> Path:
    target = target or native_target()
    if target != native_target():
        raise SystemExit(f"target {target} cannot be built on this {native_target()} host")
    if target == "macos-universal":
        architecture = subprocess.check_output(
            ["/usr/bin/lipo", "-archs", sys.executable], text=True
        ).split()
        if not {"x86_64", "arm64"}.issubset(architecture):
            raise SystemExit("macOS Universal requires a Universal 2 Python interpreter")

    RELEASE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nes-radar-build-") as temporary:
        temporary_path = Path(temporary)
        dist = temporary_path / "dist"
        work = temporary_path / "work"
        environment = os.environ.copy()
        environment["PYINSTALLER_CONFIG_DIR"] = str(work / "config")
        if target == "macos-universal":
            environment["NES_RADAR_TARGET_ARCH"] = "universal2"
            environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:" + environment.get("PATH", "")
        run_checked([
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            str(SPEC),
        ], cwd=PROJECT, env=environment)
        executable = dist / ("nes-radar-server.exe" if target == "windows-x64" else "nes-radar-server")
        run_checked([str(executable), "--version"])
        run_checked([str(executable), "--self-test"])

        root = temporary_path / f"{PRODUCT}-{target}"
        root.mkdir()
        shutil.copy2(executable, root / executable.name)
        if target != "windows-x64":
            installed = root / executable.name
            installed.chmod(installed.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        for relative in ("README.md", "THIRD_PARTY_NOTICES.md", "licenses"):
            copy_item(PROJECT / relative, root / relative)
        write_binary_launcher(root, target)

        suffix = ".tar.gz" if target.startswith("linux-") else ".zip"
        archive = RELEASE / f"{PRODUCT}-{target}{suffix}"
        if suffix == ".zip":
            zip_tree(root, archive)
        else:
            tar_tree(root, archive)
    write_hashes()
    return archive


def verify_release() -> None:
    sums = RELEASE / "SHA256SUMS"
    if not sums.exists():
        raise SystemExit(f"missing {sums}")
    for line in sums.read_text(encoding="ascii").splitlines():
        expected, filename = line.split("  ", 1)
        path = RELEASE / filename
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"hash mismatch: {filename}")
        print(f"OK  {filename}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("source", help="build the portable Python source archive")
    binary = subparsers.add_parser("binary", help="build the native binary for this host")
    binary.add_argument("--target", choices=sorted(set(TARGETS.values())))
    subparsers.add_parser("verify", help="verify SHA256SUMS")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "source":
        print(build_source())
    elif args.command == "binary":
        print(build_binary(args.target))
    else:
        verify_release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
