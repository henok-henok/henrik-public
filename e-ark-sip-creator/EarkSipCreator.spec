# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for E-ARK SIP Creator.

Build with:
    pyinstaller EarkSipCreator.spec

Output: dist/EarkSipCreator.exe
"""

import os
import customtkinter

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[(os.path.dirname(customtkinter.__file__), 'customtkinter')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EarkSipCreator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
