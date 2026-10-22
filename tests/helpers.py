import struct
from pathlib import Path

DXGI = {"RGBA8": 28, "RGBA8_SRGB": 29, "BGRA8": 87, "R8": 61, "A8": 65, "R16F": 54, "BC1": 71, "BC3": 77, "BC7": 98}
BLOCK_BYTES = {71: 8, 77: 16, 98: 16}
PIXEL_BYTES = {28: 4, 29: 4, 87: 4, 61: 1, 65: 1, 54: 2}


def surface_size(dxgi, w, h):
    if dxgi in BLOCK_BYTES:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * BLOCK_BYTES[dxgi]
    return w * h * PIXEL_BYTES[dxgi]


def dds_bytes(w, h, dxgi, payload=None, mips=1, array=1):
    if payload is None:
        total, mw, mh = 0, w, h
        for _ in range(mips):
            total += surface_size(dxgi, mw, mh)
            mw, mh = max(1, mw // 2), max(1, mh // 2)
        payload = bytes((i * 7 + 3) & 0xFF for i in range(total))
    hdr = bytearray(148)
    hdr[0:4] = b"DDS "
    flags = 0x1007 | (0x20000 if mips > 1 else 0)
    struct.pack_into("<7I", hdr, 4, 124, flags, h, w, 0, 0, mips)
    struct.pack_into("<I", hdr, 76, 32)
    struct.pack_into("<I", hdr, 80, 4)
    hdr[84:88] = b"DX10"
    struct.pack_into("<5I", hdr, 128, dxgi, 3, 0, array, 0)
    return bytes(hdr) + payload


def legacy_dds_bytes(w, h, fourcc=None, masks=None):
    hdr = bytearray(128)
    hdr[0:4] = b"DDS "
    struct.pack_into("<7I", hdr, 4, 124, 0x1007, h, w, 0, 0, 1)
    struct.pack_into("<I", hdr, 76, 32)
    if fourcc:
        struct.pack_into("<I", hdr, 80, 4)
        hdr[84:88] = fourcc
        body = bytes(max(1, w // 4) * max(1, h // 4) * (8 if fourcc in (b"DXT1", b"ATI1") else 16))
    else:
        struct.pack_into("<II", hdr, 80, 0x41, 0)
        struct.pack_into("<5I", hdr, 88, 32, *masks, 0xFF000000)
        body = bytes(w * h * 4)
    return bytes(hdr) + body


def write_dds(path, w, h, dxgi, payload=None, mips=1, array=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dds_bytes(w, h, dxgi, payload, mips, array))
    return path


def dump_name(hash_hex, w, h, family):
    return f"{hash_hex}_{w}x{h}_{family}.dds"


def pe_bytes(machine=0x8664):
    data = bytearray(1024)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x84, machine)
    return bytes(data)


def make_game(root, exe="Game.exe", machine=0x8664):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    exe_path = root / exe
    exe_path.write_bytes(pe_bytes(machine))
    return exe_path


def fake_dll(path, version=None, extra=b""):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = f"HEXON-PROXY-DLL:{version}".encode() if version else b""
    path.write_bytes(b"MZ" + bytes(64) + marker + bytes(16) + extra)
    return path
