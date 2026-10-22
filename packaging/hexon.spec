from pathlib import Path

root = Path(SPECPATH).parent
app = root / "app"
core = next((p for p in (root / "build" / "Release" / "dxgi.dll", root / "prebuilt" / "dxgi.dll") if p.exists()), None)
if core is None:
    raise SystemExit("dxgi.dll was not found. Put the provided dxgi.dll in the prebuilt folder, or build it with CMake first.")

main_a = Analysis(
    [str(app / "hexon.py")],
    pathex=[str(app)],
    datas=[(str(app / "assets"), "assets"), (str(core), "core")],
    hiddenimports=["pypresence", "psutil"],
    excludes=["PIL", "numpy", "tkinter"],
)
main_pyz = PYZ(main_a.pure)
main_exe = EXE(
    main_pyz, main_a.scripts, [],
    exclude_binaries=True,
    name="Hexon",
    console=False,
    icon=str(app / "assets" / "logo.ico"),
)

worker_a = Analysis(
    [str(app / "hexon_preview.py")],
    pathex=[str(app)],
    hiddenimports=["PIL.DdsImagePlugin", "PIL.JpegImagePlugin"],
    excludes=["PySide6", "tkinter"],
)
worker_pyz = PYZ(worker_a.pure)
worker_exe = EXE(
    worker_pyz, worker_a.scripts, [],
    exclude_binaries=True,
    name="hexon-preview",
    console=True,
)

COLLECT(
    main_exe, main_a.binaries, main_a.datas,
    worker_exe, worker_a.binaries, worker_a.datas,
    name="Hexon",
)
