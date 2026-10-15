#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

namespace hexon_dds {

struct FmtInfo { const char* name; uint32_t bytes; bool block; };

inline bool FmtFromCode(uint32_t f, FmtInfo& o) {
    switch (f) {
    case 27: case 28: case 29:           o = {"RGBA8", 4, false}; return true;
    case 87: case 90: case 91:           o = {"BGRA8", 4, false}; return true;
    case 60: case 61:                    o = {"R8", 1, false}; return true;
    case 48: case 49:                    o = {"RG8", 2, false}; return true;
    case 65:                             o = {"A8", 1, false}; return true;
    case 53: case 54: case 56:           o = {"R16", 2, false}; return true;
    case 33: case 34: case 35:           o = {"RG16", 4, false}; return true;
    case 9: case 10: case 11:            o = {"RGBA16", 8, false}; return true;
    case 23: case 24:                    o = {"RGB10A2", 4, false}; return true;
    case 26:                             o = {"R11G11B10", 4, false}; return true;
    case 70: case 71: case 72:           o = {"BC1", 8, true}; return true;
    case 73: case 74: case 75:           o = {"BC2", 16, true}; return true;
    case 76: case 77: case 78:           o = {"BC3", 16, true}; return true;
    case 79: case 80: case 81:           o = {"BC4", 8, true}; return true;
    case 82: case 83: case 84:           o = {"BC5", 16, true}; return true;
    case 94: case 95: case 96:           o = {"BC6H", 16, true}; return true;
    case 97: case 98: case 99:           o = {"BC7", 16, true}; return true;
    default: return false;
    }
}

inline uint32_t FormatFromFourCC(uint32_t cc) {
    switch (cc) {
    case 0x31545844: return 71;
    case 0x33545844: return 74;
    case 0x35545844: return 77;
    case 0x31495441: case 0x55344342: return 80;
    case 0x32495441: case 0x55354342: return 83;
    default: return 0;
    }
}

struct MipInfo { uint32_t w, h, rowBytes, rows; size_t offset; };

inline MipInfo MipGeometry(const FmtInfo& fi, uint32_t w0, uint32_t h0, uint32_t level, size_t offset) {
    MipInfo m;
    m.w = std::max(1u, w0 >> level);
    m.h = std::max(1u, h0 >> level);
    m.rowBytes = fi.block ? ((m.w + 3) / 4) * fi.bytes : m.w * fi.bytes;
    m.rows = fi.block ? (m.h + 3) / 4 : m.h;
    m.offset = offset;
    return m;
}

struct DdsInfo {
    uint32_t fmtCode = 0;
    uint32_t w = 0, h = 0;
    size_t dataOffset = 0;
    std::vector<MipInfo> mips;
};

#pragma pack(push, 4)
struct PixelFormat { uint32_t size, flags, fourCC, rgbBitCount, rMask, gMask, bMask, aMask; };
struct Header {
    uint32_t size, flags, height, width, pitchOrLinearSize, depth, mipMapCount, reserved1[11];
    PixelFormat ddspf;
    uint32_t caps, caps2, caps3, caps4, reserved2;
};
struct HeaderDx10 { uint32_t dxgiFormat, resourceDimension, miscFlag, arraySize, miscFlags2; };
#pragma pack(pop)

constexpr uint32_t kMagic = 0x20534444;
constexpr uint32_t kFourCcDx10 = 0x30315844;

inline bool ParseDds(const uint8_t* buf, size_t n, DdsInfo& out) {
    if (n < 4 + sizeof(Header)) return false;
    uint32_t magic; std::memcpy(&magic, buf, 4);
    Header hd; std::memcpy(&hd, buf + 4, sizeof(hd));
    if (magic != kMagic || hd.size != 124) return false;

    size_t off = 4 + sizeof(Header);
    uint32_t code = 0;
    if (hd.ddspf.flags & 0x4) {
        if (hd.ddspf.fourCC == kFourCcDx10) {
            if (n < off + sizeof(HeaderDx10)) return false;
            HeaderDx10 dx; std::memcpy(&dx, buf + off, sizeof(dx));
            if (dx.arraySize > 1) return false;
            code = dx.dxgiFormat;
            off += sizeof(HeaderDx10);
        } else {
            code = FormatFromFourCC(hd.ddspf.fourCC);
        }
    } else if ((hd.ddspf.flags & 0x40) && hd.ddspf.rgbBitCount == 32) {
        const auto& p = hd.ddspf;
        if (p.rMask == 0x00FF0000 && p.gMask == 0x0000FF00 && p.bMask == 0x000000FF) code = 87;
        else if (p.rMask == 0x000000FF && p.gMask == 0x0000FF00 && p.bMask == 0x00FF0000) code = 28;
    }
    FmtInfo fi;
    if (!code || !FmtFromCode(code, fi) || !hd.width || !hd.height) return false;

    out = DdsInfo{};
    out.fmtCode = code; out.w = hd.width; out.h = hd.height; out.dataOffset = off;
    uint32_t levels = (hd.flags & 0x20000) && hd.mipMapCount ? hd.mipMapCount : 1;
    size_t pos = 0;
    const size_t avail = n - off;
    for (uint32_t l = 0; l < levels && l < 16; ++l) {
        MipInfo m = MipGeometry(fi, hd.width, hd.height, l, pos);
        const size_t sz = (size_t)m.rowBytes * m.rows;
        if (pos + sz > avail) break;
        out.mips.push_back(m);
        pos += sz;
    }
    return !out.mips.empty();
}

}
