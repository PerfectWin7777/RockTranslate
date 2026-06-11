# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('d:\\Projets\\RockTranslate\\src\\assets', 'src\\assets')]
datas += collect_data_files('litellm')


a = Analysis(
    ['d:\\Projets\\RockTranslate\\main.py'],
    pathex=['d:\\Projets\\RockTranslate\\src'],
    binaries=[],
    datas=datas,
    hiddenimports=['tiktoken_ext.openai_public', 'tiktoken_ext'],
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
    [],
    exclude_binaries=True,
    name='RockTranslate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['d:\\Projets\\RockTranslate\\src\\assets\\rocktranslate_icon.png'],
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
