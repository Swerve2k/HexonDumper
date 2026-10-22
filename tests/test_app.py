import threading
import time

import pytest

from helpers import DXGI, dds_bytes, dump_name, write_dds

hexon_app = pytest.importorskip("hexon_app")
from hexon_profiles import INDEX_NAME, read_ini


def add_dump(ui, hash_hex, w=64, h=64, family="BC1", dxgi=None):
    path = ui.hexon / "dump" / dump_name(hash_hex, w, h, family)
    write_dds(path, w, h, dxgi or DXGI[family])
    return path.name


def select(ui, name):
    t = ui.win.table
    for r in range(t.rowCount()):
        if t.item(r, 0).data(hexon_app.Qt.UserRole) == name:
            t.selectRow(r)
            ui.pump(timeout=0.05)
            return True
    return False


def test_tabs_and_constants(ui_factory):
    ui = ui_factory()
    w = ui.win
    names = [w.tabs.tabText(i) for i in range(w.tabs.count())]
    assert names == ["Profiles", "Textures", "Changed", "Settings", "Log"]
    for const, label in ((hexon_app.TAB_PROFILES, "Profiles"), (hexon_app.TAB_TEXTURES, "Textures"),
                         (hexon_app.TAB_CHANGED, "Changed"), (hexon_app.TAB_SETTINGS, "Settings"),
                         (hexon_app.TAB_LOG, "Log")):
        assert w.tabs.tabText(const) == label
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        ui.pump(timeout=0.02)


def test_settings_write_ini_and_profile(ui_factory):
    ui = ui_factory()
    w = ui.win
    w.spin_min.setValue(50)
    w.chk_dump.setChecked(False)
    ui.pump(timeout=0.05)
    s = read_ini(ui.game)
    assert s["min_dim"] == 50 and s["dump"] is False
    assert w.profile().settings["min_dim"] == 50
    assert "text" not in (ui.hexon / "hexon.ini").read_text()


def test_old_text_settings_are_dropped(ui_factory):
    ui = ui_factory(profile_settings={"min_dim": 41, "text_mode": "replace", "text_trace": True})
    assert ui.win.profile().settings["min_dim"] == 41
    assert not any(k.startswith("text") for k in ui.win.profile().settings)


def test_texture_list_and_selection_survive_refresh(ui_factory):
    ui = ui_factory()
    w = ui.win
    a = add_dump(ui, "00000000000000a1")
    add_dump(ui, "00000000000000a2", 128, 128, "BC7")
    w._refresh_tex()
    assert w.table.rowCount() == 2
    assert select(ui, a)
    time.sleep(0.02)
    add_dump(ui, "00000000000000a3", 32, 32, "RGBA8")
    w._refresh_tex()
    assert w.table.rowCount() == 3 and w._selected_name() == a
    w.filter.setText("bc7")
    ui.pump(timeout=0.05)
    assert w.table.rowCount() == 1


def test_replace_with_dds(ui_factory):
    ui = ui_factory()
    w = ui.win
    name = add_dump(ui, "00000000000000b1", 64, 64, "BC1")
    w._refresh_tex()
    good = write_dds(ui.game.parent / "good.dds", 64, 64, DXGI["BC1"], payload=b"\x11" * (16 * 16 * 8))
    bad = write_dds(ui.game.parent / "bad.dds", 32, 32, DXGI["BC1"])
    assert w._apply_dds(name, bad) is not None
    assert not (ui.hexon / "replace" / name).exists()
    assert w._apply_dds(name, good) is None
    rep = ui.hexon / "replace" / name
    assert rep.read_bytes() == good.read_bytes()
    assert sorted(p.name for p in rep.parent.iterdir()) == [name]
    newer = write_dds(ui.game.parent / "newer.dds", 64, 64, DXGI["BC1"], payload=b"\x22" * (16 * 16 * 8))
    assert w._apply_dds(name, newer) is None and rep.read_bytes() == newer.read_bytes()
    w._fill_table()
    assert select(ui, name)
    assert w.table.item(w.table.currentRow(), 3).text() == "Replaced"
    w._unreplace()
    assert not rep.exists()


def test_replace_while_dll_reads(ui_factory):
    import ctypes
    from ctypes import wintypes
    ui = ui_factory()
    w = ui.win
    name = add_dump(ui, "00000000000000b2", 64, 64, "BC1")
    rep = ui.hexon / "replace" / name
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_bytes(dds_bytes(64, 64, DXGI["BC1"]))
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                wintypes.DWORD, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def hold(seconds):
        h = k32.CreateFileW(str(rep), 0x80000000, 0x1 | 0x2 | 0x4, None, 3, 0x80, None)
        assert h and h != wintypes.HANDLE(-1).value
        t = threading.Timer(seconds, k32.CloseHandle, args=(h,))
        t.start()
        return t

    newer = write_dds(ui.game.parent / "newer.dds", 64, 64, DXGI["BC1"], payload=b"\x33" * (16 * 16 * 8))
    hold(0.2)
    assert w._apply_dds(name, newer) is None
    assert rep.read_bytes() == newer.read_bytes()
    stuck = hold(5)
    try:
        err = w._apply_dds(name, write_dds(ui.game.parent / "third.dds", 64, 64, DXGI["BC1"]))
        assert err and err.startswith("Couldn't copy third.dds")
        assert rep.read_bytes() == newer.read_bytes() and not rep.with_name(rep.name + ".part").exists()
    finally:
        stuck.cancel()
        stuck.function(*stuck.args)


def test_drop_named_dds_files(ui_factory):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent
    ui = ui_factory()
    w = ui.win
    names = [add_dump(ui, f"00000000000000c{i}", 64, 64, "BC1") for i in range(3)]
    w._refresh_tex()
    srcdir = ui.game.parent / "mods"
    files = [write_dds(srcdir / n, 64, 64, DXGI["BC1"]) for n in names[:2]]
    files.append(write_dds(srcdir / names[2], 16, 16, DXGI["BC1"]))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f)) for f in files])
    ev = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    w.dropEvent(ev)
    msg = ui.messages("information")[-1]
    assert msg.startswith("Replaced 2 of 3 texture(s).")
    assert sorted(p.name for p in (ui.hexon / "replace").iterdir()) == sorted(names[:2])


def test_clear_dump_keeps_replacements(ui_factory):
    ui = ui_factory()
    w = ui.win
    name = add_dump(ui, "00000000000000d1")
    add_dump(ui, "00000000000000d2")
    (ui.hexon / "dump" / INDEX_NAME).write_text("hash\tw\n")
    write_dds(ui.hexon / "replace" / name, 64, 64, DXGI["BC1"])
    w._clear_dump()
    assert list((ui.hexon / "dump").iterdir()) == []
    assert (ui.hexon / "replace" / name).exists()
    assert w.table.rowCount() == 0


FAKE_TEXCONV = r"""@echo off
setlocal enabledelayedexpansion
set OUT=
set LAST=
set ALL=
:loop
if "%~1"=="" goto done
set ALL=!ALL! %1
if "%~1"=="-o" set "OUT=%~2"
set "LAST=%~1"
shift
goto loop
:done
>"%FAKE_TEXCONV_LOG%" echo !ALL!
if "%FAKE_TEXCONV_FAIL%"=="1" (
  echo FAILED: simulated error
  exit /b 1
)
for %%F in ("%LAST%") do set "STEM=%%~nF"
copy /y "%FAKE_TEXCONV_DDS%" "%OUT%\%STEM%.dds" >nul
exit /b 0
"""


@pytest.fixture
def fake_texconv(tmp_path, monkeypatch):
    bat = tmp_path / "texconv.bat"
    bat.write_text(FAKE_TEXCONV)
    log = tmp_path / "texconv_args.txt"
    monkeypatch.setenv("FAKE_TEXCONV_LOG", str(log))
    monkeypatch.setenv("FAKE_TEXCONV_FAIL", "0")
    return bat, log


def convert(ui, name, image):
    w = ui.win
    w._convert_image(name, image)
    assert ui.pump(lambda: not w._converting, timeout=20)
    ui.pump(timeout=0.05)


def test_texconv_conversion(ui_factory, fake_texconv, tmp_path, monkeypatch):
    bat, log = fake_texconv
    ui = ui_factory()
    w = ui.win
    name = add_dump(ui, "00000000000000e1", 64, 64, "BC1")
    out = write_dds(tmp_path / "converted.dds", 64, 64, DXGI["BC1"], payload=b"\x44" * (16 * 16 * 8))
    monkeypatch.setenv("FAKE_TEXCONV_DDS", str(out))
    w.texconv_edit.setText(str(bat))
    w.chk_genmips.setChecked(True)
    png = tmp_path / "my edit.png"
    png.write_bytes(b"\x89PNG fake")
    convert(ui, name, png)
    assert (ui.hexon / "replace" / name).read_bytes() == out.read_bytes(), ui.messages()
    args = log.read_text()
    assert "-f BC1_UNORM" in args and "-w 64" in args and "-h 64" in args and "-m 0" in args and "-dx10" in args
    assert "my edit.png" in args


def test_texconv_failure_reports(ui_factory, fake_texconv, tmp_path, monkeypatch):
    bat, log = fake_texconv
    monkeypatch.setenv("FAKE_TEXCONV_FAIL", "1")
    monkeypatch.setenv("FAKE_TEXCONV_DDS", str(tmp_path / "none.dds"))
    ui = ui_factory()
    w = ui.win
    name = add_dump(ui, "00000000000000e2", 64, 64, "BC1")
    w.texconv_edit.setText(str(bat))
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG fake")
    convert(ui, name, png)
    assert any("texconv could not convert" in m and "simulated error" in m for m in ui.messages("warning"))
    assert not (ui.hexon / "replace" / name).exists()


def test_texconv_missing(ui_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(hexon_app.shutil, "which", lambda *_: None)
    monkeypatch.setattr(hexon_app, "EXE_DIR", tmp_path / "nowhere")
    ui = ui_factory()
    w = ui.win
    name = add_dump(ui, "00000000000000e3", 64, 64, "BC1")
    png = tmp_path / "x.png"
    png.write_bytes(b"png")
    w._convert_image(name, png)
    assert any("needs texconv" in m for m in ui.messages("information"))


def test_install_flow_with_anticheat_warning(ui_factory, tmp_path, monkeypatch):
    from helpers import fake_dll
    core = fake_dll(tmp_path / "core" / "dxgi.dll", "9.9.9")
    monkeypatch.setattr(hexon_app, "find_core_dll", lambda: core)
    ui = ui_factory()
    (ui.game / "BattlEye").mkdir()
    ui.box.answer = False
    ui.win._install()
    assert not (ui.game / "dxgi.dll").exists()
    assert any("anti-cheat" in m.lower() for m in ui.messages("ask"))
    ui.box.answer = True
    ui.win._install()
    assert (ui.game / "dxgi.dll").read_bytes() == core.read_bytes()
    ui.win._uninstall()
    assert not (ui.game / "dxgi.dll").exists()
