import os

import pytest

import hexon_profiles as hp
from helpers import DXGI, dds_bytes, legacy_dds_bytes, write_dds

hexon_app = pytest.importorskip("hexon_app")


def test_read_dds_header_dx10(tmp_path):
    h = hexon_app.read_dds_header(write_dds(tmp_path / "a.dds", 64, 32, DXGI["BC7"], mips=3))
    assert (h["w"], h["h"], h["family"], h["mips"], h["dxgi"]) == (64, 32, "BC7", 3, 98)


@pytest.mark.parametrize("fourcc,family", [(b"DXT1", "BC1"), (b"DXT5", "BC3"), (b"ATI2", "BC5")])
def test_read_dds_header_legacy(tmp_path, fourcc, family):
    f = tmp_path / "l.dds"
    f.write_bytes(legacy_dds_bytes(16, 16, fourcc=fourcc))
    assert hexon_app.read_dds_header(f)["family"] == family


def test_read_dds_header_masks(tmp_path):
    f = tmp_path / "m.dds"
    f.write_bytes(legacy_dds_bytes(8, 8, masks=(0xFF0000, 0xFF00, 0xFF)))
    assert hexon_app.read_dds_header(f)["family"] == "BGRA8"


def test_read_dds_header_rejects(tmp_path):
    arr = write_dds(tmp_path / "arr.dds", 8, 8, DXGI["RGBA8"], array=6)
    with pytest.raises(ValueError, match="arrays"):
        hexon_app.read_dds_header(arr)
    bad = tmp_path / "bad.dds"
    bad.write_bytes(b"nope" * 40)
    with pytest.raises(ValueError, match="not a DDS"):
        hexon_app.read_dds_header(bad)
    odd = tmp_path / "odd.dds"
    odd.write_bytes(dds_bytes(8, 8, 2, payload=b""))
    with pytest.raises(ValueError, match="not supported"):
        hexon_app.read_dds_header(odd)


def test_scan_and_sizes(tmp_path):
    write_dds(tmp_path / "a.dds", 8, 8, DXGI["RGBA8"])
    write_dds(tmp_path / "b.dds", 4, 4, DXGI["BC1"])
    (tmp_path / "note.txt").write_text("x")
    n, total = hexon_app.scan_dds(tmp_path)
    assert n == 2 and total == (148 + 256) + (148 + 8)
    assert hexon_app.dir_size(tmp_path) == total + 1
    assert hexon_app.scan_dds(tmp_path / "missing") == (0, 0)
    assert hexon_app.human(512) == "512 B" and hexon_app.human(1536) == "1.5 KB" and hexon_app.human(3 * 1024 ** 3) == "3.0 GB"


def test_atomic_copy_replaces_without_leftovers(tmp_path):
    src1, src2 = tmp_path / "s1.dds", tmp_path / "s2.dds"
    src1.write_bytes(b"one")
    src2.write_bytes(b"two-two")
    dest = tmp_path / "replace" / "x.dds"
    hp.atomic_copy(src1, dest)
    hp.atomic_copy(src2, dest)
    assert dest.read_bytes() == b"two-two"
    assert sorted(p.name for p in dest.parent.iterdir()) == ["x.dds"]


def test_atomic_copy_retries_while_locked(tmp_path, monkeypatch):
    src = tmp_path / "s.dds"
    src.write_bytes(b"data")
    dest = tmp_path / "d.dds"
    real = os.replace
    calls = {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("in use")
        return real(a, b)

    monkeypatch.setattr(hp.os, "replace", flaky)
    hp.atomic_copy(src, dest, delay=0)
    assert dest.read_bytes() == b"data" and calls["n"] == 3


def test_atomic_copy_gives_up_and_cleans(tmp_path, monkeypatch):
    src = tmp_path / "s.dds"
    src.write_bytes(b"data")
    dest = tmp_path / "d.dds"

    def locked(a, b):
        raise PermissionError("in use")

    monkeypatch.setattr(hp.os, "replace", locked)
    with pytest.raises(PermissionError):
        hp.atomic_copy(src, dest, attempts=3, delay=0)
    assert not dest.exists() and not (tmp_path / "d.dds.part").exists()


INDEX_HEADER = "hash\tw\th\tfamily\tmip\tmips\tslice\ttop_w\ttop_h\tgroup\tsession\ttime_ms"


def test_read_dump_index(tmp_path):
    f = tmp_path / hp.INDEX_NAME
    f.write_text("\n".join([
        INDEX_HEADER,
        "00000000000000aa\t64\t64\tBC7\t0\t3\t0\t64\t64\t0000000000000001\t00000000000000ff\t1700000000000",
        "00000000000000bb\t32\t32\tBC7\t1\t3\t0\t64\t64\t0000000000000001\t00000000000000ff\t1700000000001",
        "00000000000000AA\t64\t64\tBC7\t0\t1\t0\t64\t64\t0000000000000009\t0000000000000100\t1800000000000",
        "zz\t1\t1\tBC7\t0\t1\t0\t1\t1\t1\t1\t1",
        "00000000000000cc\tx\t1\tBC7\t0\t1\t0\t1\t1\t1\t1\t1",
        "00000000000000dd\t8\t8",
        "00000000000000ee\t16\t16\tRGBA8\t0\t1\t0\t16\t16\t0000000000000002\t00000000000000ff\t17000",
    ]) + "\n00000000000000ff\t4\t4\tBC1")
    idx = hp.read_dump_index(f)
    assert sorted(idx) == ["00000000000000aa", "00000000000000bb", "00000000000000ee"]
    assert idx["00000000000000aa"]["mips"] == 3 and idx["00000000000000aa"]["session"] == "00000000000000ff"
    assert idx["00000000000000bb"]["mip"] == 1 and idx["00000000000000bb"]["top_w"] == 64
    assert hp.read_dump_index(tmp_path / "missing.tsv") == {}
    empty = tmp_path / "e.tsv"
    empty.write_text("")
    assert hp.read_dump_index(empty) == {}
    nohdr = tmp_path / "n.tsv"
    nohdr.write_text("00000000000000aa\t1\n")
    assert hp.read_dump_index(nohdr) == {}
    assert "top_hash" not in idx["00000000000000aa"]


def test_read_dump_index_with_top_hash(tmp_path):
    f = tmp_path / hp.INDEX_NAME
    f.write_text("\n".join([
        INDEX_HEADER + "\ttop_hash",
        "00000000000000aa\t64\t64\tBC7\t0\t3\t0\t64\t64\t0000000000000001\t00000000000000ff\t1\t00000000000000AA",
        "00000000000000bb\t32\t32\tBC7\t1\t3\t0\t64\t64\t0000000000000001\t00000000000000ff\t2\t00000000000000aa",
        "00000000000000cc\t32\t32\tBC7\t1\t3\t0\t64\t64\t0000000000000001\t00000000000000ff\t3\t0000000000000000",
        "00000000000000dd\t32\t32\tBC7\t1\t3\t0\t64\t64\t0000000000000001\t00000000000000ff\t4\tnot-a-hash",
        "00000000000000ee\t32\t32\tBC7\t1\t3\t0\t64\t64\t0000000000000001\t00000000000000ff\t5",
    ]) + "\n")
    idx = hp.read_dump_index(f)
    assert sorted(idx) == ["00000000000000aa", "00000000000000bb", "00000000000000cc", "00000000000000dd"]
    assert idx["00000000000000aa"]["top_hash"] == "00000000000000aa"
    assert idx["00000000000000bb"]["top_hash"] == "00000000000000aa"
    assert idx["00000000000000cc"]["top_hash"] == "0000000000000000"
    assert idx["00000000000000dd"]["top_hash"] == ""
