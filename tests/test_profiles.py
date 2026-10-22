import json
import os

import pytest

import hexon_profiles as hp
from helpers import fake_dll, make_game


def test_clean_settings_defaults_and_bounds():
    assert hp.clean_settings(None) == hp.DEFAULT_SETTINGS
    s = hp.clean_settings({"dump": 0, "verbose": 1, "min_dim": 1, "dump_gb": 99999, "text_mode": "find", "junk": 1})
    assert s["dump"] is False and s["verbose"] is True
    assert s["min_dim"] == 4 and s["dump_gb"] == 2000.0
    assert set(s) == set(hp.DEFAULT_SETTINGS)
    assert hp.clean_settings({"min_dim": "abc"})["min_dim"] == hp.DEFAULT_SETTINGS["min_dim"]
    assert hp.clean_settings({"min_dim": 50000})["min_dim"] == 8192


def test_ini_round_trip(tmp_path):
    exe = make_game(tmp_path / "g")
    p = hp.Profile(id="x", name="G", exe=str(exe), settings=hp.clean_settings(
        {"dump": False, "replace": True, "mips": False, "verbose": True, "min_dim": 41, "dump_gb": 26}))
    hp.write_ini(p)
    text = (p.hexon_dir / "hexon.ini").read_text()
    assert "max_dump_mb=26624" in text and "text" not in text
    assert hp.read_ini(p.game_dir) == p.settings
    assert hp.read_ini(tmp_path / "missing") is None


def test_store_add_save_load_remove(tmp_path):
    exe1, exe2 = make_game(tmp_path / "a", "RainbowSix.exe"), make_game(tmp_path / "b", "My_CoolGame.exe")
    store = hp.ProfileStore(tmp_path / "data")
    p1 = store.add(exe1)
    p2 = store.add(exe2, name="  Custom  ")
    assert p1.name == "Rainbow Six Siege" and p2.name == "Custom" and store.active == p2.id
    with pytest.raises(ValueError):
        store.add(exe1)
    with pytest.raises(ValueError):
        store.add(tmp_path / "nope.exe")
    again = hp.ProfileStore(tmp_path / "data")
    again.load()
    assert [p.id for p in again.profiles] == [p1.id, p2.id] and again.active == p2.id
    again.remove(p2.id)
    assert again.active == p1.id and len(again.profiles) == 1


def test_store_recovers_from_corrupt_file(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "profiles.json").write_text("{not json")
    store = hp.ProfileStore(d)
    store.load()
    assert store.profiles == [] and (d / "profiles.json.bad").exists()


def test_store_skips_bad_entries_and_fixes_active(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    exe = make_game(tmp_path / "g")
    (d / "profiles.json").write_text(json.dumps({"active": "gone", "profiles": [
        {"id": "a", "exe": str(exe)}, {"name": "no id"}, "junk", {"id": "b"}]}))
    store = hp.ProfileStore(d)
    store.load()
    assert [p.id for p in store.profiles] == ["a"] and store.active == "a"


def test_guess_game_name():
    assert hp.guess_game_name("C:/x/RainbowSix_BE.exe") == "Rainbow Six Siege"
    assert hp.guess_game_name("C:/x/super_cool-Game.exe") == "super cool Game"
    assert hp.guess_game_name("C:/x/DarkSouls.exe") == "Dark Souls"


def test_versions_and_markers(tmp_path):
    v = hp.version_tuple
    assert v("1.10.0") > v("1.9.9") and v("1.2") == v("1.2.0")
    assert v("1.2.0") < v("2.0.0-dev.1") < v("2.0.0-dev.2") < v("2.0.0-dev.10") < v("2.0.0") < v("2.0.1")
    assert v("2.0.0-dev") < v("2.0.0") and v("") == v("0")
    assert hp.find_marker_version(fake_dll(tmp_path / "a.dll", "1.2.3")) == "1.2.3"
    assert hp.find_marker_version(fake_dll(tmp_path / "b.dll")) is None
    assert hp.find_marker_version(tmp_path / "missing.dll") is None


@pytest.fixture
def game(tmp_path):
    exe = make_game(tmp_path / "game")
    core = fake_dll(tmp_path / "core" / "dxgi.dll", "2.0.0")
    return hp.Profile(id="p", name="G", exe=str(exe)), core


def test_dll_states(game, tmp_path):
    p, core = game
    assert hp.dll_state(hp.Profile(id="x", name="x", exe=str(tmp_path / "none.exe")), core) == hp.NO_EXE
    assert hp.dll_state(p, core) == hp.NOT_INSTALLED
    fake_dll(p.dll_path)
    assert hp.dll_state(p, core) == hp.FOREIGN
    fake_dll(p.dll_path, "1.1.2")
    assert hp.dll_state(p, core) == hp.OUTDATED
    fake_dll(p.dll_path, "2.0.0")
    assert hp.dll_state(p, core) == hp.CURRENT


def test_install_update_uninstall(game):
    p, core = game
    assert hp.install(p, core).kind == "ok"
    assert p.dll_path.read_bytes() == core.read_bytes() and p.hexon_dir.is_dir()
    assert hp.install(p, core).kind == "skipped"
    fake_dll(p.dll_path, "1.0.0")
    r = hp.install(p, core)
    assert r.kind == "ok" and r.message == "Updated."
    assert not p.dll_path.with_name("dxgi.dll.hexon-new").exists()
    r = hp.uninstall(p)
    assert r.kind == "ok" and not p.dll_path.exists()


def test_foreign_dll_backup_and_restore(game):
    p, core = game
    original = fake_dll(p.dll_path, extra=b"original")
    original_bytes = original.read_bytes()
    fake_dll(p.game_dir / "dxgi.dll.hexon-backup", extra=b"older backup")
    assert hp.install(p, core).kind == "confirm" and p.dll_path.read_bytes() == original_bytes
    r = hp.install(p, core, replace_foreign=True)
    assert r.kind == "ok" and p.backup == "dxgi.dll.hexon-backup2"
    assert (p.game_dir / "dxgi.dll.hexon-backup2").read_bytes() == original_bytes
    r = hp.uninstall(p)
    assert r.kind == "ok" and p.dll_path.read_bytes() == original_bytes and p.backup == ""
    assert hp.uninstall(p).kind == "skipped"


def test_install_failure_leaves_game_untouched(game, monkeypatch):
    p, core = game
    original = fake_dll(p.dll_path, extra=b"original").read_bytes()
    real_replace = os.replace

    def flaky(a, b):
        if str(b).endswith("dxgi.dll") and str(a).endswith(".hexon-new"):
            raise PermissionError("locked")
        return real_replace(a, b)

    monkeypatch.setattr(hp.os, "replace", flaky)
    r = hp.install(p, core, replace_foreign=True)
    assert r.kind == "error" and "Close the game" in r.message
    assert p.dll_path.read_bytes() == original and p.backup == ""
    assert not p.dll_path.with_name("dxgi.dll.hexon-new").exists()


def test_install_needs_exe_and_core(game, tmp_path):
    p, core = game
    assert hp.install(p, tmp_path / "missing.dll").kind == "error"
    assert hp.install(hp.Profile(id="x", name="x", exe=str(tmp_path / "none.exe")), core).kind == "error"


def test_remove_all(tmp_path):
    core = fake_dll(tmp_path / "core" / "dxgi.dll", "2.0.0")
    store = hp.ProfileStore(tmp_path / "data")
    a = store.add(make_game(tmp_path / "a"))
    b = store.add(make_game(tmp_path / "b"))
    orig = fake_dll(b.dll_path, extra=b"orig").read_bytes()
    assert hp.install(a, core).ok and hp.install(b, core, replace_foreign=True).ok
    store.save()
    assert hp.remove_all(tmp_path / "data") == 0
    assert not a.dll_path.exists() and b.dll_path.read_bytes() == orig


def test_detect_anticheat(tmp_path):
    g = tmp_path / "g"
    (g / "BattlEye").mkdir(parents=True)
    (g / "sub").mkdir()
    (g / "sub" / "EasyAntiCheat_EOS_Setup.exe").write_bytes(b"")
    (g / "hexon").mkdir()
    (g / "hexon" / "vgc.exe").write_bytes(b"")
    assert hp.detect_anticheat(g) == ["BattlEye", "Easy Anti-Cheat"]
    assert hp.detect_anticheat(tmp_path / "missing") == []


def test_bitness(tmp_path):
    assert hp.bitness_problem(make_game(tmp_path / "x64")) is None
    assert "32-bit" in hp.bitness_problem(make_game(tmp_path / "x86", machine=0x14C))
    assert "ARM64" in hp.bitness_problem(make_game(tmp_path / "arm", machine=0xAA64))
    junk = tmp_path / "junk.exe"
    junk.write_bytes(b"not a pe")
    assert hp.bitness_problem(junk) is None and hp.pe_machine(junk) is None


def test_last_launch_summary(tmp_path):
    p = hp.Profile(id="p", name="G", exe=str(make_game(tmp_path / "g")))
    assert hp.last_launch_summary(p)[0] == "never"
    p.hexon_dir.mkdir()
    log = p.hexon_dir / "hexon.log"
    log.write_text("[1] ---- Hexon 1.0 started (x) ----\n[2] D3D12 hooks installed (copy=0)\n"
                   "[3] ---- Hexon 2.0 started (y) ----\n[4] D3D12CreateDevice hook: ok\n")
    assert hp.last_launch_summary(p)[0] == "no_dx12"
    log.write_text(log.read_text() + "[5] D3D12 hooks FAILED\n")
    assert hp.last_launch_summary(p)[0] == "failed"
    log.write_text(log.read_text() + "[6] ---- Hexon 2.0 started (z) ----\n[7] D3D12 hooks installed (copy=0)\n")
    assert hp.last_launch_summary(p)[0] == "hooked"
