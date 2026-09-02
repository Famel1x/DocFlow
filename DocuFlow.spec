# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Дополнительные файлы данных
datas = [
    ('app/static', 'app/static'),
]

# Автоматически собираем данные для ключевых библиотек
datas += collect_data_files('rapidocr_onnxruntime')
datas += collect_data_files('easyocr')
datas += collect_data_files('fitz')
datas += collect_data_files('pymupdf')

# Скрытые импорты, которые PyInstaller может не обнаружить динамически
hiddenimports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'pydantic',
    'pydantic_core',
    'starlette',
    'starlette.routing',
    'multipart',
    'python_multipart',
    'openpyxl',
    'docx',
    'pptx',
    'pdfplumber',
    'pymupdf',
    'fitz',
    'PIL',
    'PIL.Image',
    'rapidocr_onnxruntime',
    'onnxruntime',
    'gigachat',
    'httpx',
]

hiddenimports += collect_submodules('rapidocr_onnxruntime')
hiddenimports += collect_submodules('easyocr')

a = Analysis(
    ['run_app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DocuFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DocuFlow',
)
