# -*- mode: python ; coding: utf-8 -*-
"""
Phase 13 -- PyInstaller build spec for Lyra.

Build with:
    pyinstaller lyra.spec

Do NOT build with the bare CLI (`pyinstaller main.py --onefile --windowed`)
instead of this spec -- three of this project's dependencies hide files or
submodules that PyInstaller's static import scan can't see on its own:
chromadb and sentence-transformers ship data files + lazily-imported
plugins, and googleapiclient ships a discovery-cache JSON. collect_all()
below pulls those in explicitly. Skipping this spec builds a .exe that
looks fine at build time and only crashes the first time RAG or Gmail
features actually get used at runtime.

See BUILD.md for the full build + verification checklist.
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [("assets", "assets")]
binaries = []
hiddenimports = []

# Each of these ships data files, lazy submodule imports, or a
# plugin/entry-point registry that PyInstaller's static analysis can't
# discover by just scanning `import` statements.
for pkg in ("chromadb", "sentence_transformers", "googleapiclient"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# Belt-and-suspenders: tokenizers' compiled data files are sometimes missed
# by collect_all's default scan depending on version. Harmless no-op if
# already covered above.
datas += collect_data_files("tokenizers")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# --onefile equivalent: a.binaries/a.datas passed straight into EXE()
# (no separate COLLECT step) bundles everything into one .exe that
# self-extracts to a temp dir at launch -- see lyra/paths.py for why
# persistent app data deliberately does NOT live in that temp dir.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Lyra",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # --windowed: no console window behind the GUI.
                     # (Was temporarily True to debug the mic in the
                     # packaged build -- confirmed clean, no errors, so
                     # reverted back to the real --windowed setting.)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
