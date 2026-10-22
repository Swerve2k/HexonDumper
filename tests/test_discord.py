import sys
import threading
import time
import types

import pytest

import hexon_discord


class FakePresence:
    instances = []
    fail_connect = 0
    fail_update = None

    def __init__(self, cid):
        self.cid = cid
        self.updates = []
        self.closed = False
        self.cleared = False
        self.changed = threading.Event()
        FakePresence.instances.append(self)

    def connect(self):
        if FakePresence.fail_connect:
            FakePresence.fail_connect -= 1
            raise type("DiscordNotFound", (Exception,), {})()

    def update(self, **payload):
        if FakePresence.fail_update:
            err, FakePresence.fail_update = FakePresence.fail_update, None
            raise err
        self.updates.append(payload)
        self.changed.set()

    def clear(self):
        self.cleared = True

    def close(self):
        self.closed = True


@pytest.fixture
def presence(monkeypatch):
    FakePresence.instances = []
    FakePresence.fail_connect = 0
    FakePresence.fail_update = None
    monkeypatch.setitem(sys.modules, "pypresence", types.SimpleNamespace(Presence=FakePresence))
    monkeypatch.setattr(hexon_discord.DiscordPresence, "MIN_INTERVAL", 0.3)
    monkeypatch.setattr(hexon_discord.DiscordPresence, "RETRY_INTERVAL", 0.2)
    statuses = []
    dp = hexon_discord.DiscordPresence(on_status=statuses.append)
    dp.statuses = statuses
    yield dp
    dp.shutdown()


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_connects_and_sends(presence):
    presence.configure("123", {"details": "Using Hexon", "large_image": "hexon"})
    assert wait(lambda: FakePresence.instances and FakePresence.instances[-1].updates)
    rpc = FakePresence.instances[-1]
    assert rpc.cid == "123" and rpc.updates[0] == {"details": "Using Hexon", "large_image": "hexon"}
    assert "Connected to Discord." in presence.statuses


def test_rate_limited_and_coalesced(presence):
    presence.configure("123", {"details": "a"})
    assert wait(lambda: FakePresence.instances and FakePresence.instances[-1].updates)
    rpc = FakePresence.instances[-1]
    t0 = time.monotonic()
    presence.configure("123", {"details": "b"})
    presence.configure("123", {"details": "c"})
    assert wait(lambda: len(rpc.updates) >= 2)
    assert time.monotonic() - t0 >= 0.2
    time.sleep(0.5)
    assert [u["details"] for u in rpc.updates] == ["a", "c"]


def test_waits_for_discord_then_connects(presence):
    FakePresence.fail_connect = 2
    presence.configure("123", {"details": "x"})
    assert wait(lambda: any("Waiting for Discord" in s for s in presence.statuses))
    assert wait(lambda: FakePresence.instances and FakePresence.instances[-1].updates, timeout=8)


def test_reconnects_after_pipe_error(presence):
    presence.configure("123", {"details": "a"})
    assert wait(lambda: FakePresence.instances and FakePresence.instances[-1].updates)
    first = FakePresence.instances[-1]
    FakePresence.fail_update = type("PipeClosed", (Exception,), {})()
    presence.configure("123", {"details": "b"})
    assert wait(lambda: first.closed)
    assert wait(lambda: len(FakePresence.instances) >= 2 and FakePresence.instances[-1].updates, timeout=8)
    assert FakePresence.instances[-1].updates[-1]["details"] == "b"


def test_turning_off_clears(presence):
    presence.configure("123", {"details": "a"})
    assert wait(lambda: FakePresence.instances and FakePresence.instances[-1].updates)
    rpc = FakePresence.instances[-1]
    presence.configure("123", None)
    assert wait(lambda: rpc.closed) and rpc.cleared
    assert wait(lambda: "Off." in presence.statuses)


def test_payload_is_locked_down(ui_factory):
    ui = ui_factory(settings_text="rpc_large=evil\nrpc_small=evil\nrpc_btn_label=Click\nrpc_btn_url=https://bad.example\n"
                                  "rpc_custom=custom top line\nrpc_id=999\n",
                    game_name="Siege " + "x" * 300)
    w = ui.win
    w.chk_rpc.setChecked(True)
    p = w._presence_payload()
    assert p["large_image"] == "hexon" and "small_image" not in p
    assert p["buttons"] == [{"label": "Get Hexon", "url": "https://github.com/Swerve2k/HexonDumper"}]
    assert p["large_text"].startswith("Hexon ")
    assert p["details"].startswith("Modding Siege") and len(p["details"]) <= 120
    assert "evil" not in str(p) and "bad.example" not in str(p) and "custom top line" not in str(p)
    assert "start" in p
    import hexon_app
    assert hexon_app.DISCORD_APP_ID == "1558850044126568501"


def test_payload_toggles(ui_factory):
    import hexon_app
    ui = ui_factory()
    w = ui.win
    w.chk_rpc.setChecked(True)
    for c in (w.chk_rpc_game, w.chk_rpc_tab, w.chk_rpc_dumped, w.chk_rpc_replaced, w.chk_rpc_usage,
              w.chk_rpc_running, w.chk_rpc_elapsed):
        c.setChecked(False)
    p = w._presence_payload()
    assert p["details"] == "Using Hexon" and "state" not in p and "start" not in p
    w.chk_rpc_tab.setChecked(True)
    w.chk_rpc_dumped.setChecked(True)
    w.tabs.setCurrentIndex(hexon_app.TAB_CHANGED)
    p = w._presence_payload()
    assert p["state"] == f"{hexon_app.TAB_ACTIVITY[hexon_app.TAB_CHANGED]} · 0 dumped"
    w.chk_rpc.setChecked(False)
    assert w._presence_payload() is None
    assert len(hexon_app.TAB_ACTIVITY) == w.tabs.count()


def test_game_watcher_sees_running_process():
    import os
    import psutil
    name = psutil.Process(os.getpid()).name()
    gw = hexon_discord.GameWatcher(interval=0.1)
    try:
        gw.set_exe(name)
        assert wait(lambda: gw.running is True)
        gw.set_exe("definitely-not-running-hexon.exe")
        assert wait(lambda: gw.running is False)
    finally:
        gw.shutdown()
