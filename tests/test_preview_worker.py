import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import DXGI, dds_bytes

WORKER = Path(__file__).resolve().parent.parent / "app" / "hexon_preview.py"


@pytest.fixture
def worker():
    proc = subprocess.Popen([sys.executable, str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    first = json.loads(proc.stdout.readline())
    assert first == {"ready": True}
    seq = {"n": 0}

    def ask(src, dst, px=128):
        seq["n"] += 1
        proc.stdin.write(json.dumps({"id": seq["n"], "src": str(src), "dst": str(dst), "px": px}) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        assert resp["id"] == seq["n"]
        return resp

    yield ask
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0


CASES = {
    "rgba8": (64, 64, DXGI["RGBA8"], bytes([200, 30, 30, 255]) * 64 * 64),
    "bgra8": (32, 16, DXGI["BGRA8"], bytes([30, 30, 200, 255]) * 32 * 16),
    "bc1": (64, 64, DXGI["BC1"], bytes([0x00, 0xF8, 0x1F, 0x00, 0, 0, 0, 0]) * 256),
    "bc7": (16, 16, DXGI["BC7"], None),
    "r8": (32, 32, DXGI["R8"], bytes(range(256)) * 4),
    "a8": (32, 32, DXGI["A8"], bytes(range(256)) * 4),
    "r16f": (32, 32, DXGI["R16F"], struct.pack("<e", 0.5) * 32 * 32),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_formats_render(worker, tmp_path, name):
    w, h, dxgi, payload = CASES[name]
    src = tmp_path / f"{name}.dds"
    src.write_bytes(dds_bytes(w, h, dxgi, payload))
    dst = tmp_path / f"{name}.jpg"
    resp = worker(src, dst)
    assert resp["ok"], resp
    assert dst.read_bytes()[:2] == b"\xff\xd8"
    assert not (tmp_path / f"{name}.jpg.tmp").exists()


def test_bad_inputs(worker, tmp_path):
    junk = tmp_path / "junk.dds"
    junk.write_bytes(b"not a dds at all" * 20)
    r = worker(junk, tmp_path / "junk.jpg")
    assert not r["ok"] and "not a DDS" in r["err"]
    r = worker(tmp_path / "missing.dds", tmp_path / "m.jpg")
    assert not r["ok"] and r["err"].startswith("FileNotFoundError")
