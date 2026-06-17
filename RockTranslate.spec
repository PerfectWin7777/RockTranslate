# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('d:\\Projets\\RockTranslate\\src\\rocktranslate\\assets', 'rocktranslate\\assets')]
datas += collect_data_files('litellm')


a = Analysis(
    ['d:\\Projets\\RockTranslate\\src\\rocktranslate\\web_gui.py'],
    pathex=['d:\\Projets\\RockTranslate\\src'],
    binaries=[],
    datas=datas,
    hiddenimports=['tiktoken_ext.openai_public', 'tiktoken_ext', 'clr', 'webview.platforms.winforms', 'webview.platforms.cocoa'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'shiboken6', 'pyside6_essentials', 'PySide2', 'PyQt6', 'PyQt5', 'fitz', 'pymupdf'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RockTranslate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['d:\\Projets\\RockTranslate\\src\\rocktranslate\\assets\\rocktranslate_icon.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RockTranslate',
)
