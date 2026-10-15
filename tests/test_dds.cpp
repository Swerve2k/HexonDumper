#include "../core/src/hexon_dds.h"
#include <cstdio>
#include <cstdlib>
using namespace hexon_dds;
static int fails = 0;
#define CHECK(c) do { if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); ++fails; } } while (0)

static std::vector<uint8_t> make(uint32_t w, uint32_t h, uint32_t flags, uint32_t mips, PixelFormat pf, bool dx10, uint32_t dxgi, size_t dataBytes, uint32_t arraySize = 1) {
    Header hd{}; hd.size = 124; hd.flags = flags; hd.width = w; hd.height = h; hd.mipMapCount = mips; hd.ddspf = pf;
    std::vector<uint8_t> b; auto put = [&](const void* p, size_t n) { auto* c = (const uint8_t*)p; b.insert(b.end(), c, c + n); };
    uint32_t magic = kMagic; put(&magic, 4); put(&hd, sizeof(hd));
    if (dx10) { HeaderDx10 dx{dxgi, 3, 0, arraySize, 0}; put(&dx, sizeof(dx)); }
    b.resize(b.size() + dataBytes);
    return b;
}
static PixelFormat fourcc(uint32_t cc) { PixelFormat p{}; p.size = 32; p.flags = 4; p.fourCC = cc; return p; }
static size_t chain(const FmtInfo& fi, uint32_t w, uint32_t h, uint32_t levels) { size_t t = 0; for (uint32_t l = 0; l < levels; ++l) { auto m = MipGeometry(fi, w, h, l, 0); t += (size_t)m.rowBytes * m.rows; } return t; }

int main() {
    DdsInfo d; FmtInfo fi;

    FmtFromCode(98, fi);
    size_t full = chain(fi, 1024, 1024, 11);
    printf("BC7 1024 full chain bytes = %zu (expect 1398128)\n", full);
    CHECK(full == 1398128);
    auto b = make(1024, 1024, 0x81007 | 0x20000, 11, fourcc(kFourCcDx10), true, 98, full);
    CHECK(ParseDds(b.data(), b.size(), d));
    CHECK(d.fmtCode == 98 && d.w == 1024 && d.dataOffset == 148 && d.mips.size() == 11);
    CHECK(d.mips[0].offset == 0 && d.mips[0].rowBytes == 256 * 16 && d.mips[0].rows == 256);
    CHECK(d.mips[1].offset == 1024 * 1024 && d.mips[1].w == 512 && d.mips[1].rows == 128);
    CHECK(d.mips[10].w == 1 && d.mips[10].h == 1 && d.mips[10].rowBytes == 16 && d.mips[10].rows == 1);
    CHECK(d.mips[9].w == 2 && d.mips[9].rows == 1);

    b = make(1024, 1024, 0x81007, 1, fourcc(kFourCcDx10), true, 98, 1024 * 1024);
    CHECK(ParseDds(b.data(), b.size(), d) && d.mips.size() == 1);

    b = make(1024, 1024, 0x81007 | 0x20000, 11, fourcc(kFourCcDx10), true, 98, 1024 * 1024 + 512 * 512 + 5);
    CHECK(ParseDds(b.data(), b.size(), d) && d.mips.size() == 2);

    FmtFromCode(71, fi); full = chain(fi, 512, 512, 10);
    printf("DXT1 512 full chain bytes = %zu (expect 174776)\n", full);
    b = make(512, 512, 0x81007 | 0x20000, 10, fourcc(0x31545844), false, 0, full);
    CHECK(ParseDds(b.data(), b.size(), d));
    CHECK(d.fmtCode == 71 && d.dataOffset == 128 && d.mips.size() == 10 && d.mips[0].rowBytes == 128 * 8);

    FmtFromCode(77, fi); full = chain(fi, 440, 144, 1);
    CHECK(full == 110 * 36 * 16 && full == 63360);
    b = make(440, 144, 0x81007, 1, fourcc(0x35545844), false, 0, full);
    CHECK(ParseDds(b.data(), b.size(), d) && d.fmtCode == 77 && d.mips[0].rowBytes == 110 * 16 && d.mips[0].rows == 36);

    PixelFormat bgra{}; bgra.size = 32; bgra.flags = 0x41; bgra.rgbBitCount = 32; bgra.rMask = 0xFF0000; bgra.gMask = 0xFF00; bgra.bMask = 0xFF; bgra.aMask = 0xFF000000;
    b = make(64, 64, 0x81007, 1, bgra, false, 0, 64 * 64 * 4);
    CHECK(ParseDds(b.data(), b.size(), d) && d.fmtCode == 87 && d.mips[0].rowBytes == 256);
    PixelFormat rgba = bgra; rgba.rMask = 0xFF; rgba.bMask = 0xFF0000;
    b = make(64, 64, 0x81007, 1, rgba, false, 0, 64 * 64 * 4);
    CHECK(ParseDds(b.data(), b.size(), d) && d.fmtCode == 28);

    b = make(64, 64, 0x81007, 1, fourcc(kFourCcDx10), true, 98, 64 * 64, 6);
    CHECK(!ParseDds(b.data(), b.size(), d));
    b = make(64, 64, 0x81007, 1, fourcc(0x12345678), false, 0, 4096);
    CHECK(!ParseDds(b.data(), b.size(), d));
    b = make(64, 64, 0x81007, 1, fourcc(kFourCcDx10), true, 98, 4096); b[0] = 'X';
    CHECK(!ParseDds(b.data(), b.size(), d));
    b = make(64, 64, 0x81007, 1, fourcc(kFourCcDx10), true, 98, 0);
    CHECK(!ParseDds(b.data(), b.size(), d));
    b = make(64, 64, 0x81007, 1, fourcc(kFourCcDx10), true, 98, 4096);
    CHECK(!ParseDds(b.data(), 100, d));
    CHECK(!ParseDds(b.data(), 0, d));
    PixelFormat rgb24 = bgra; rgb24.rgbBitCount = 24;
    b = make(64, 64, 0x81007, 1, rgb24, false, 0, 64 * 64 * 3);
    CHECK(!ParseDds(b.data(), b.size(), d));

    srand(7); int accepted = 0;
    for (int i = 0; i < 20000; ++i) {
        std::vector<uint8_t> r(rand() % 400); for (auto& c : r) c = (uint8_t)rand();
        if (r.size() > 8 && (i & 1)) { uint32_t m = kMagic; memcpy(r.data(), &m, 4); uint32_t s = 124; memcpy(r.data() + 4, &s, 4); }
        if (ParseDds(r.data(), r.size(), d)) ++accepted;
    }
    printf("fuzz done (accepted %d of 20000 random buffers)\n", accepted);
    printf(fails ? "\n%d FAILURES\n" : "\nALL PASSED\n", fails);
    return fails != 0;
}
