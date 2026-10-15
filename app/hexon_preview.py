import io
import json
import os
import struct
import sys


def lower_priority():
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
        else:
            os.nice(10)
    except Exception:
        pass


def _float_bits(v, mbits, np):
    e = (v >> mbits) & 0x1F
    m = (v & ((1 << mbits) - 1)).astype(np.float32) / float(1 << mbits)
    val = np.where(e == 0, m * 2.0 ** -14, (1.0 + m) * np.exp2(e.astype(np.float32) - 15.0))
    return np.where(e == 31, 1.0, val)


def _to_u8(a, np):
    return (np.clip(np.nan_to_num(a.astype(np.float32)), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def raw_to_image(data, w, h, fmt, px):
    import numpy as np
    from PIL import Image

    k = max(1, max(w, h) // (px * 2))

    def grid(dtype, ch):
        a = np.frombuffer(data, dtype=dtype, count=w * h * ch).reshape(h, w, ch)
        return a[::k, ::k]

    if fmt in (87, 90, 91):
        rgb = grid(np.uint8, 4)[..., [2, 1, 0]]
    elif fmt in (27, 28, 29):
        rgb = grid(np.uint8, 4)[..., :3]
    elif fmt in (60, 61, 65):
        g = grid(np.uint8, 1)[..., 0]
        rgb = np.stack([g, g, g], -1)
    elif fmt in (48, 49):
        a = grid(np.uint8, 2)
        rgb = np.concatenate([a, np.zeros_like(a[..., :1])], -1)
    elif fmt in (53, 56):
        g = (grid(np.uint16, 1)[..., 0] >> 8).astype(np.uint8)
        rgb = np.stack([g, g, g], -1)
    elif fmt == 54:
        g = _to_u8(grid(np.float16, 1)[..., 0], np)
        rgb = np.stack([g, g, g], -1)
    elif fmt in (33, 35):
        a = (grid(np.uint16, 2) >> 8).astype(np.uint8)
        rgb = np.concatenate([a, np.zeros_like(a[..., :1])], -1)
    elif fmt == 34:
        a = _to_u8(grid(np.float16, 2), np)
        rgb = np.concatenate([a, np.zeros_like(a[..., :1])], -1)
    elif fmt in (9, 11):
        rgb = (grid(np.uint16, 4)[..., :3] >> 8).astype(np.uint8)
    elif fmt == 10:
        rgb = _to_u8(grid(np.float16, 4)[..., :3], np)
    elif fmt in (23, 24):
        v = grid(np.uint32, 1)[..., 0]
        rgb = np.stack([(v & 0x3FF) >> 2, ((v >> 10) & 0x3FF) >> 2, ((v >> 20) & 0x3FF) >> 2], -1).astype(np.uint8)
    elif fmt == 26:
        v = grid(np.uint32, 1)[..., 0]
        rgb = _to_u8(np.stack([_float_bits(v & 0x7FF, 6, np), _float_bits((v >> 11) & 0x7FF, 6, np),
                               _float_bits((v >> 22) & 0x3FF, 5, np)], -1), np)
    else:
        raise ValueError(f"format {fmt} has no preview")
    return Image.fromarray(np.ascontiguousarray(rgb), "RGB")


def render(src, dst, px):
    from PIL import Image

    with open(src, "rb") as f:
        raw = f.read()
    if len(raw) < 128 or raw[:4] != b"DDS ":
        raise ValueError("not a DDS file")
    h, w = struct.unpack_from("<2I", raw, 12)
    dx10 = raw[84:88] == b"DX10" and len(raw) >= 148
    fmt = struct.unpack_from("<I", raw, 128)[0] if dx10 else None

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (NotImplementedError, OSError):
        if fmt is None:
            raise ValueError("this DDS format has no preview")
        img = raw_to_image(raw[148:], w, h, fmt, px)

    img = img.convert("RGB")
    img.thumbnail((px, px), Image.BILINEAR, reducing_gap=2.0)
    tmp = dst + ".tmp"
    img.save(tmp, "JPEG", quality=85)
    os.replace(tmp, dst)


def main():
    lower_priority()
    try:
        import numpy
        from PIL import Image
    except Exception as e:
        sys.stdout.write(json.dumps({"fatal": f"Previews need Pillow and numpy ({e})"}) + "\n")
        sys.stdout.flush()
        return
    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except ValueError:
            continue
        out = {"id": req.get("id"), "ok": False}
        try:
            render(req["src"], req["dst"], int(req["px"]))
            out["ok"] = True
        except Exception as e:
            out["err"] = f"{type(e).__name__}: {e}"[:200]
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
