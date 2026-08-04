# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os


PROJECT = Path(SPECPATH).resolve().parent
SOURCE = PROJECT / "src"
TARGET_ARCH = os.environ.get("NES_RADAR_TARGET_ARCH") or None

a = Analysis(
    [str(SOURCE / "nes_radar_server.py")],
    pathex=[str(SOURCE)],
    binaries=[],
    datas=[
        (str(SOURCE / "data"), "data"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nes-radar-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
)
