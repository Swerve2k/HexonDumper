#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <MinHook.h>

#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "hexon.h"
#include "hexon_dds.h"

namespace {
std::wstring g_dir, g_dumpDir, g_repDir;
FILE* g_log = nullptr;
std::mutex g_logMu;
}

void hexon::Log(const char* fmt, ...) {
    std::lock_guard<std::mutex> lk(g_logMu);
    if (!g_log) return;
    SYSTEMTIME t; GetLocalTime(&t);
    fprintf(g_log, "[%02d:%02d:%02d] ", t.wHour, t.wMinute, t.wSecond);
    va_list ap; va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

namespace {

const char kProxyMarker[] = "HEXON-PROXY-DLL:1.0.0";
const char* volatile g_keepMarker = kProxyMarker;

bool g_dump = true, g_replace = true, g_verbose = false, g_mips = true;
UINT g_minDim = 64;
UINT g_maxDumps = 20000;
uint64_t g_maxDumpBytes = 4096ull << 20, g_dumpBytes = 0;
bool g_capLogged = false;

using hexon_dds::FmtInfo;

bool GetFmt(DXGI_FORMAT f, FmtInfo& o) { return hexon_dds::FmtFromCode((uint32_t)f, o); }

bool SameFamily(DXGI_FORMAT a, DXGI_FORMAT b) {
    FmtInfo x, y;
    return GetFmt(a, x) && GetFmt(b, y) && strcmp(x.name, y.name) == 0;
}

DXGI_FORMAT DumpFormat(DXGI_FORMAT f) {
    switch (f) {
    case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
    case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
    case DXGI_FORMAT_R8_TYPELESS:       return DXGI_FORMAT_R8_UNORM;
    case DXGI_FORMAT_R8G8_TYPELESS:     return DXGI_FORMAT_R8G8_UNORM;
    case DXGI_FORMAT_BC1_TYPELESS:      return DXGI_FORMAT_BC1_UNORM;
    case DXGI_FORMAT_BC2_TYPELESS:      return DXGI_FORMAT_BC2_UNORM;
    case DXGI_FORMAT_BC3_TYPELESS:      return DXGI_FORMAT_BC3_UNORM;
    case DXGI_FORMAT_BC4_TYPELESS:      return DXGI_FORMAT_BC4_UNORM;
    case DXGI_FORMAT_BC5_TYPELESS:      return DXGI_FORMAT_BC5_UNORM;
    case DXGI_FORMAT_BC6H_TYPELESS:     return DXGI_FORMAT_BC6H_UF16;
    case DXGI_FORMAT_BC7_TYPELESS:      return DXGI_FORMAT_BC7_UNORM;
    case DXGI_FORMAT_R16G16B16A16_TYPELESS: return DXGI_FORMAT_R16G16B16A16_UNORM;
    case DXGI_FORMAT_R16G16_TYPELESS:   return DXGI_FORMAT_R16G16_UNORM;
    case DXGI_FORMAT_R16_TYPELESS:      return DXGI_FORMAT_R16_UNORM;
    case DXGI_FORMAT_R10G10B10A2_TYPELESS: return DXGI_FORMAT_R10G10B10A2_UNORM;
    default: return f;
    }
}

bool WriteDds(const std::wstring& path, DXGI_FORMAT fmt, UINT w, UINT h, const std::vector<uint8_t>& data) {
    FILE* f = _wfopen(path.c_str(), L"wb");
    if (!f) return false;
    hexon_dds::Header hd{};
    hd.size = 124;
    hd.flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000;
    hd.height = h; hd.width = w;
    hd.pitchOrLinearSize = (uint32_t)data.size();
    hd.depth = 1; hd.mipMapCount = 1;
    hd.ddspf.size = 32; hd.ddspf.flags = 0x4; hd.ddspf.fourCC = hexon_dds::kFourCcDx10;
    hd.caps = 0x1000;
    hexon_dds::HeaderDx10 dx{};
    dx.dxgiFormat = (uint32_t)DumpFormat(fmt);
    dx.resourceDimension = 3;
    dx.arraySize = 1;
    fwrite(&hexon_dds::kMagic, 4, 1, f);
    fwrite(&hd, sizeof(hd), 1, f);
    fwrite(&dx, sizeof(dx), 1, f);
    fwrite(data.data(), 1, data.size(), f);
    fclose(f);
    return true;
}

uint64_t Hash64(const uint8_t* p, size_t n, uint64_t h) {
    const uint64_t M = 0x9E3779B97F4A7C15ULL;
    while (n >= 8) { uint64_t k; memcpy(&k, p, 8); h ^= k; h *= M; h ^= h >> 32; p += 8; n -= 8; }
    while (n--) { h ^= *p++; h *= 0x100000001B3ULL; }
    return h ^ (h >> 29);
}

struct RepEntry {
    std::wstring path;
    FILETIME mt{};
    bool loaded = false, valid = false;
    uint32_t fmtCode = 0;
    UINT w = 0, h = 0;
    std::vector<uint8_t> data;
    std::vector<hexon_dds::MipInfo> mips;
};

std::unordered_map<uint64_t, RepEntry> g_rep;
std::atomic<ULONGLONG> g_lastScan{0};
bool g_anyMipRep = false;

std::mutex g_sigMu;
std::unordered_set<uint64_t> g_sigs;

uint64_t SigKey(UINT w, UINT h, const char* fam) {
    return Hash64((const uint8_t*)fam, strlen(fam), 0x9E37ull ^ ((uint64_t)w << 20) ^ ((uint64_t)h << 40));
}
bool SigKnown(UINT w, UINT h, const char* fam) {
    std::lock_guard<std::mutex> lk(g_sigMu);
    return g_sigs.count(SigKey(w, h, fam)) != 0;
}

bool ParseRepName(const wchar_t* n, uint64_t& hash, UINT& w, UINT& h, char* fam  ) {
    if (wcslen(n) < 24) return false;
    wchar_t* end = nullptr;
    hash = wcstoull(n, &end, 16);
    if (end != n + 16 || n[16] != L'_') return false;
    const wchar_t* p = n + 17;
    w = wcstoul(p, &end, 10);
    if (end == p || *end != L'x') return false;
    p = end + 1;
    h = wcstoul(p, &end, 10);
    if (end == p || *end != L'_') return false;
    p = end + 1;
    size_t i = 0;
    while (*p && *p != L'.' && i < 15) fam[i++] = (char)*p++;
    fam[i] = 0;
    return i > 0;
}

void LoadRep(RepEntry& e) {
    e.loaded = true; e.valid = false;
    FILE* f = _wfopen(e.path.c_str(), L"rb");
    if (!f) return;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    std::vector<uint8_t> buf(n > 0 ? (size_t)n : 0);
    if (n > 0 && fread(buf.data(), 1, buf.size(), f) != buf.size()) { fclose(f); return; }
    fclose(f);

    hexon_dds::DdsInfo info;
    if (!hexon_dds::ParseDds(buf.data(), buf.size(), info)) return;
    e.fmtCode = info.fmtCode; e.w = info.w; e.h = info.h;
    e.mips = info.mips;
    e.data.assign(buf.begin() + info.dataOffset, buf.end());
    e.valid = true;
    if (e.mips.size() > 1) g_anyMipRep = true;
}

void ScanReplacements() {
    std::unordered_set<uint64_t> present;
    std::unordered_set<uint64_t> sigs;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((g_repDir + L"\\*.dds").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            uint64_t key; UINT w, hgt; char fam[16];
            if (!ParseRepName(fd.cFileName, key, w, hgt, fam)) continue;
            present.insert(key);
            sigs.insert(SigKey(w, hgt, fam));
            RepEntry& e = g_rep[key];
            if (e.path.empty() || CompareFileTime(&e.mt, &fd.ftLastWriteTime) != 0) {
                e = RepEntry{};
                e.path = g_repDir + L"\\" + fd.cFileName;
                e.mt = fd.ftLastWriteTime;
            }
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    for (auto it = g_rep.begin(); it != g_rep.end();)
        it = present.count(it->first) ? std::next(it) : g_rep.erase(it);
    std::lock_guard<std::mutex> lk(g_sigMu);
    g_sigs.swap(sigs);
}

RepEntry* FindRep(uint64_t hash) {
    auto it = g_rep.find(hash);
    if (it == g_rep.end()) return nullptr;
    if (!it->second.loaded) LoadRep(it->second);
    return &it->second;
}

struct Pending {
    ID3D12Resource* src;
    ID3D12Resource* dst;
    UINT64 offset;
    DXGI_FORMAT fmt;
    UINT w, h, rowPitch;
    UINT subresource;
    bool small;
};

std::mutex g_pendMu, g_procMu;
std::unordered_map<void*, std::vector<Pending>> g_pending;
std::unordered_set<uint64_t> g_seen;
uint64_t g_nCopies = 0, g_nProcessed = 0, g_nDumped = 0, g_nReplaced = 0, g_nMip = 0;
bool g_warnedUnmatched = false;
int g_rejectLogs = 0;

std::atomic<uint64_t> d_copyTex{0}, d_nonPlaced{0}, d_box{0}, d_dim{0}, d_fmt{0}, d_queued{0},
    d_exec{0}, d_execWork{0}, d_notUpload{0}, d_notBuffer{0}, d_bounds{0}, d_mapFail{0},
    d_copyBuf{0}, d_copyRes{0}, d_mipPatched{0};
std::unordered_map<UINT, uint64_t> g_skipFmt;

using PFN_CopyTex = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*, const D3D12_TEXTURE_COPY_LOCATION*, UINT, UINT, UINT, const D3D12_TEXTURE_COPY_LOCATION*, const D3D12_BOX*);
using PFN_Reset   = HRESULT(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*, ID3D12CommandAllocator*, ID3D12PipelineState*);
using PFN_CopyBuf = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*, ID3D12Resource*, UINT64, ID3D12Resource*, UINT64, UINT64);
using PFN_CopyRes = void(STDMETHODCALLTYPE*)(ID3D12GraphicsCommandList*, ID3D12Resource*, ID3D12Resource*);
using PFN_Exec    = void(STDMETHODCALLTYPE*)(ID3D12CommandQueue*, UINT, ID3D12CommandList* const*);
using PFN_CreateDevice = HRESULT(WINAPI*)(IUnknown*, D3D_FEATURE_LEVEL, REFIID, void**);

PFN_CopyTex g_origCopy = nullptr;
PFN_Reset g_origReset = nullptr;
PFN_Exec g_origExec = nullptr;
PFN_CopyBuf g_origCopyBuf = nullptr;
PFN_CopyRes g_origCopyRes = nullptr;
PFN_CreateDevice g_origCreateDevice = nullptr;
bool g_vtableHooked = false;

void ReleasePending(std::vector<Pending>& v) {
    for (auto& p : v) { p.src->Release(); p.dst->Release(); }
    v.clear();
}

const GUID kMarkGuid = {0x9a3f5c2e, 0x6b1d, 0x4f0a, {0x8c, 0x77, 0x2e, 0x5d, 0x1b, 0x94, 0xa0, 0xc3}};
struct Mark { uint64_t key; uint32_t base; uint32_t pad; };

bool GetMark(ID3D12Resource* r, Mark& m) {
    UINT sz = sizeof(Mark);
    return SUCCEEDED(r->GetPrivateData(kMarkGuid, &sz, &m)) && sz == sizeof(Mark);
}
void SetMark(ID3D12Resource* r, const Mark& m) { r->SetPrivateData(kMarkGuid, sizeof(Mark), &m); }

bool IsPlainTexture2D(ID3D12Resource* r) {
    const D3D12_RESOURCE_DESC d = r->GetDesc();
    return d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && d.DepthOrArraySize == 1;
}

void STDMETHODCALLTYPE HkCopyBufferRegion(ID3D12GraphicsCommandList* self, ID3D12Resource* d, UINT64 dof, ID3D12Resource* s, UINT64 sof, UINT64 n) {
    ++d_copyBuf;
    g_origCopyBuf(self, d, dof, s, sof, n);
}

void STDMETHODCALLTYPE HkCopyResource(ID3D12GraphicsCommandList* self, ID3D12Resource* d, ID3D12Resource* s) {
    ++d_copyRes;
    g_origCopyRes(self, d, s);
}

void STDMETHODCALLTYPE HkCopyTextureRegion(ID3D12GraphicsCommandList* self,
        const D3D12_TEXTURE_COPY_LOCATION* dst, UINT x, UINT y, UINT z,
        const D3D12_TEXTURE_COPY_LOCATION* src, const D3D12_BOX* box) {
    ++d_copyTex;
    if (!dst || !src || !dst->pResource || dst->Type != D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX ||
        src->Type != D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT || !src->pResource) {
        ++d_nonPlaced;
    } else if (box || x || y || z) {
        ++d_box;
    } else {
        const auto& fp = src->PlacedFootprint;
        FmtInfo fi;
        if (fp.Footprint.Depth != 1) {
            ++d_dim;
        } else if (!GetFmt(fp.Footprint.Format, fi)) {
            ++d_fmt;
            std::lock_guard<std::mutex> lk(g_pendMu);
            if (g_skipFmt[(UINT)fp.Footprint.Format]++ == 0)
                hexon::Log("unsupported upload format %u (%ux%u)", (unsigned)fp.Footprint.Format, fp.Footprint.Width, fp.Footprint.Height);
        } else {

            const bool small = fp.Footprint.Width < g_minDim || fp.Footprint.Height < g_minDim;
            bool want = true;
            if (small) {
                Mark mk;
                want = g_replace && (SigKnown(fp.Footprint.Width, fp.Footprint.Height, fi.name) ||
                                     (g_mips && GetMark(dst->pResource, mk)));
            }
            if (!want) {
                ++d_dim;
            } else {
                src->pResource->AddRef();
                dst->pResource->AddRef();
                std::lock_guard<std::mutex> lk(g_pendMu);
                auto& v = g_pending[(void*)self];
                if (v.size() < 8192) {
                    v.push_back({src->pResource, dst->pResource, fp.Offset, fp.Footprint.Format, fp.Footprint.Width,
                                 fp.Footprint.Height, fp.Footprint.RowPitch, dst->SubresourceIndex, small});
                    ++g_nCopies; ++d_queued;
                } else {
                    src->pResource->Release();
                    dst->pResource->Release();
                }
            }
        }
    }
    g_origCopy(self, dst, x, y, z, src, box);
}

HRESULT STDMETHODCALLTYPE HkReset(ID3D12GraphicsCommandList* self, ID3D12CommandAllocator* a, ID3D12PipelineState* s) {
    {
        std::lock_guard<std::mutex> lk(g_pendMu);
        auto it = g_pending.find((void*)self);
        if (it != g_pending.end()) { ReleasePending(it->second); g_pending.erase(it); }
    }
    return g_origReset(self, a, s);
}

std::wstring HexName(uint64_t h, UINT w, UINT hgt, const char* fmt) {
    wchar_t buf[128];
    swprintf(buf, 128, L"%016llx_%ux%u_%hs.dds", (unsigned long long)h, w, hgt, fmt);
    return buf;
}

struct Geometry { FmtInfo fi; UINT rowBytes, rows; uint64_t need; };

bool SurfaceGeometry(const Pending& p, Geometry& g) {
    if (!GetFmt(p.fmt, g.fi)) return false;
    g.rowBytes = g.fi.block ? ((p.w + 3) / 4) * g.fi.bytes : p.w * g.fi.bytes;
    g.rows = g.fi.block ? (p.h + 3) / 4 : p.h;
    if (!g.rowBytes || !g.rows || g.rowBytes > p.rowPitch) return false;
    g.need = p.offset + (uint64_t)(g.rows - 1) * p.rowPitch + g.rowBytes;
    return true;
}

uint8_t* MapStaging(const Pending& p, const Geometry& g) {
    D3D12_HEAP_PROPERTIES hp{}; D3D12_HEAP_FLAGS hf{};
    if (FAILED(p.src->GetHeapProperties(&hp, &hf))) { ++d_notUpload; return nullptr; }

    const bool cpuVisible = hp.Type == D3D12_HEAP_TYPE_UPLOAD ||
        (hp.Type == D3D12_HEAP_TYPE_CUSTOM &&
         (hp.CPUPageProperty == D3D12_CPU_PAGE_PROPERTY_WRITE_COMBINE || hp.CPUPageProperty == D3D12_CPU_PAGE_PROPERTY_WRITE_BACK));
    if (!cpuVisible) {
        if (++d_notUpload <= 3) hexon::Log("upload source heap not CPU-writable (type %d, page prop %d, pool %d)", (int)hp.Type, (int)hp.CPUPageProperty, (int)hp.MemoryPoolPreference);
        return nullptr;
    }
    static bool loggedHeap = false;
    if (!loggedHeap) { loggedHeap = true; hexon::Log("staging heap: type %d, page prop %d, pool %d", (int)hp.Type, (int)hp.CPUPageProperty, (int)hp.MemoryPoolPreference); }
    const D3D12_RESOURCE_DESC rd = p.src->GetDesc();
    if (rd.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER) { ++d_notBuffer; return nullptr; }
    if (g.need > rd.Width) { ++d_bounds; return nullptr; }
    void* base = nullptr;
    if (FAILED(p.src->Map(0, nullptr, &base)) || !base) { ++d_mapFail; return nullptr; }
    return (uint8_t*)base + p.offset;
}

bool PatchFromRep(uint8_t* ptr, const Pending& p, const Geometry& g, const RepEntry& e, size_t level) {
    if (level >= e.mips.size()) return false;
    const auto& m = e.mips[level];
    if (m.rowBytes != g.rowBytes || m.rows != g.rows) return false;
    if (!g.fi.block && (m.w != p.w || m.h != p.h)) return false;
    if (!SameFamily((DXGI_FORMAT)e.fmtCode, p.fmt)) return false;
    const uint8_t* from = e.data.data() + m.offset;
    for (UINT r = 0; r < g.rows; ++r)
        memcpy(ptr + (size_t)r * p.rowPitch, from + (size_t)r * g.rowBytes, g.rowBytes);
    return true;
}

bool ApplyMarked(uint8_t* ptr, const Pending& p, const Geometry& g, const Mark& mk) {
    if (p.subresource < mk.base) return false;
    auto it = g_rep.find(mk.key);
    if (it == g_rep.end()) return false;
    RepEntry& e = it->second;
    if (!e.loaded) LoadRep(e);
    if (!e.valid || !PatchFromRep(ptr, p, g, e, p.subresource - mk.base)) return false;
    ++d_mipPatched;
    if (++g_nMip <= 10 || g_nMip % 500 == 0)
        hexon::Log("mip %u patched from %016llx (%ux%u %s, total %llu)", p.subresource - mk.base, (unsigned long long)mk.key, p.w, p.h, g.fi.name, (unsigned long long)g_nMip);
    return true;
}

void ProcessOne(const Pending& p, size_t idx, std::vector<size_t>& deferred) {
    Geometry g;
    if (!SurfaceGeometry(p, g)) return;
    uint8_t* ptr = MapStaging(p, g);
    if (!ptr) return;

    std::vector<uint8_t> tight((size_t)g.rowBytes * g.rows);
    for (UINT r = 0; r < g.rows; ++r)
        memcpy(tight.data() + (size_t)r * g.rowBytes, ptr + (size_t)r * p.rowPitch, g.rowBytes);

    const uint64_t seed = 0xcbf29ce484222325ULL ^ ((uint64_t)p.w | ((uint64_t)p.h << 16) | ((uint64_t)g.fi.bytes << 32) | ((uint64_t)g.fi.block << 40));
    const uint64_t hash = Hash64(tight.data(), tight.size(), seed);
    ++g_nProcessed;

    bool wrote = false;
    if (g_replace) {
        Mark mk{};
        const bool marked = g_mips && GetMark(p.dst, mk);
        if (RepEntry* e = FindRep(hash)) {
            if (e->valid && PatchFromRep(ptr, p, g, *e, 0)) {
                wrote = true;
                if (++g_nReplaced <= 20 || g_nReplaced % 200 == 0)
                    hexon::Log("replaced %016llx %ux%u %s (total %llu%s)", (unsigned long long)hash, p.w, p.h, g.fi.name,
                               (unsigned long long)g_nReplaced, e->mips.size() > 1 ? ", has mips" : "");
                if (g_mips && e->mips.size() > 1 && IsPlainTexture2D(p.dst))
                    SetMark(p.dst, Mark{hash, p.subresource, 0});
            } else if (g_rejectLogs++ < 10) {
                if (!e->valid) hexon::Log("replacement for %016llx is not a usable DDS (DX10 header, DXT1/3/5, BC4/5 or 32-bit RGBA/BGRA)", (unsigned long long)hash);
                else hexon::Log("replacement for %016llx rejected (needs %ux%u %s, file is %ux%u)", (unsigned long long)hash, p.w, p.h, g.fi.name, e->w, e->h);
            }
        } else if (marked) {
            wrote = ApplyMarked(ptr, p, g, mk);
        } else if (g_mips && g_anyMipRep) {
            deferred.push_back(idx);
        }
    }

    if (!p.small) {
        if (g_dump && g_dumpBytes >= g_maxDumpBytes && !g_capLogged) {
            g_capLogged = true;
            hexon::Log("dump size cap reached (%llu MB), no more dumps", (unsigned long long)(g_dumpBytes >> 20));
        }
        if (g_dump && g_seen.size() < g_maxDumps && g_dumpBytes < g_maxDumpBytes && g_seen.insert(hash).second) {
            const std::wstring path = g_dumpDir + L"\\" + HexName(hash, p.w, p.h, g.fi.name);
            if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES && WriteDds(path, p.fmt, p.w, p.h, tight)) {
                ++g_nDumped; g_dumpBytes += tight.size();
            }
        }
    }

    D3D12_RANGE wr = wrote ? D3D12_RANGE{p.offset, g.need} : D3D12_RANGE{0, 0};
    p.src->Unmap(0, &wr);

    if (g_verbose && g_nProcessed % 500 == 0)
        hexon::Log("stats: copies seen %llu, processed %llu, dumped %llu, replaced %llu, mips %llu",
                   (unsigned long long)g_nCopies, (unsigned long long)g_nProcessed,
                   (unsigned long long)g_nDumped, (unsigned long long)g_nReplaced, (unsigned long long)g_nMip);
}

void ProcessAll(std::vector<Pending>& work) {
    std::vector<size_t> deferred;
    for (size_t i = 0; i < work.size(); ++i) ProcessOne(work[i], i, deferred);

    for (size_t i : deferred) {
        const Pending& p = work[i];
        Mark mk;
        if (!GetMark(p.dst, mk)) continue;
        Geometry g;
        if (!SurfaceGeometry(p, g)) continue;
        uint8_t* ptr = MapStaging(p, g);
        if (!ptr) continue;
        const bool wrote = ApplyMarked(ptr, p, g, mk);
        D3D12_RANGE wr = wrote ? D3D12_RANGE{p.offset, g.need} : D3D12_RANGE{0, 0};
        p.src->Unmap(0, &wr);
    }
}

void STDMETHODCALLTYPE HkExecute(ID3D12CommandQueue* q, UINT n, ID3D12CommandList* const* lists) {
    ++d_exec;
    std::vector<Pending> work;
    size_t totalLists = 0;
    {
        std::lock_guard<std::mutex> lk(g_pendMu);
        for (UINT i = 0; i < n; ++i) {
            auto it = g_pending.find((void*)lists[i]);
            if (it != g_pending.end()) {
                work.insert(work.end(), it->second.begin(), it->second.end());
                g_pending.erase(it);
            }
        }
        totalLists = g_pending.size();
    }
    if (work.empty() && totalLists > 256 && !g_warnedUnmatched) {
        g_warnedUnmatched = true;
        hexon::Log("warning: %zu command lists hold texture uploads but none matched a submit; list pointers may differ", totalLists);
    }

    const ULONGLONG now = GetTickCount64();
    if (g_replace && now - g_lastScan.load() > 3000) {
        std::unique_lock<std::mutex> lk(g_procMu, std::try_to_lock);
        if (lk.owns_lock()) { g_lastScan = now; ScanReplacements(); }
    }

    if (!work.empty()) {
        ++d_execWork;
        std::lock_guard<std::mutex> lk(g_procMu);
        ProcessAll(work);
        ReleasePending(work);
    }
    g_origExec(q, n, lists);
}

DWORD WINAPI Heartbeat(LPVOID) {
    uint64_t last = 0;
    for (;;) {
        Sleep(5000);
        const uint64_t sig = d_copyTex + d_copyBuf + d_copyRes + d_exec + g_nProcessed + g_nDumped;
        if (sig == last) continue;
        last = sig;
        size_t pend;
        { std::lock_guard<std::mutex> lk(g_pendMu); pend = g_pending.size(); }
        hexon::Log("heartbeat: CopyTextureRegion=%llu (non-placed=%llu box=%llu small/vol=%llu badfmt=%llu queued=%llu) "
                   "CopyBufferRegion=%llu CopyResource=%llu | submits=%llu withUploads=%llu | processed=%llu dumped=%llu replaced=%llu "
                   "mipPatched=%llu | skips: notUpload=%llu notBuffer=%llu bounds=%llu mapFail=%llu | listsPending=%zu",
                   (unsigned long long)d_copyTex, (unsigned long long)d_nonPlaced, (unsigned long long)d_box,
                   (unsigned long long)d_dim, (unsigned long long)d_fmt, (unsigned long long)d_queued,
                   (unsigned long long)d_copyBuf, (unsigned long long)d_copyRes,
                   (unsigned long long)d_exec, (unsigned long long)d_execWork,
                   (unsigned long long)g_nProcessed, (unsigned long long)g_nDumped, (unsigned long long)g_nReplaced,
                   (unsigned long long)d_mipPatched, (unsigned long long)d_notUpload, (unsigned long long)d_notBuffer,
                   (unsigned long long)d_bounds, (unsigned long long)d_mapFail, pend);
    }
}

void InstallDeviceHooks(IUnknown* devUnk) {
    if (g_vtableHooked) return;
    ID3D12Device* dev = nullptr;
    if (FAILED(devUnk->QueryInterface(__uuidof(ID3D12Device), (void**)&dev)) || !dev) return;

    ID3D12CommandAllocator* alloc = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    ID3D12CommandQueue* queue = nullptr;
    D3D12_COMMAND_QUEUE_DESC qd{}; qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;

    bool ok = SUCCEEDED(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, __uuidof(ID3D12CommandAllocator), (void**)&alloc)) &&
              SUCCEEDED(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc, nullptr, __uuidof(ID3D12GraphicsCommandList), (void**)&list)) &&
              SUCCEEDED(dev->CreateCommandQueue(&qd, __uuidof(ID3D12CommandQueue), (void**)&queue));
    if (ok) {
        void** lv = *(void***)list;
        void** qv = *(void***)queue;
        MH_STATUS a = MH_CreateHook(lv[16], (void*)HkCopyTextureRegion, (void**)&g_origCopy);
        MH_STATUS b = MH_CreateHook(lv[10], (void*)HkReset,             (void**)&g_origReset);
        MH_STATUS c = MH_CreateHook(qv[10], (void*)HkExecute,           (void**)&g_origExec);
        MH_STATUS e1 = MH_CreateHook(lv[15], (void*)HkCopyBufferRegion, (void**)&g_origCopyBuf);
        MH_STATUS e2 = MH_CreateHook(lv[17], (void*)HkCopyResource,     (void**)&g_origCopyRes);
        if (e1 != MH_OK || e2 != MH_OK) hexon::Log("diagnostic hooks failed (%d, %d), continuing", e1, e2);
        MH_STATUS d = MH_EnableHook(MH_ALL_HOOKS);
        g_vtableHooked = (a == MH_OK && b == MH_OK && c == MH_OK && d == MH_OK);
        hexon::Log("D3D12 hooks %s (copy=%d reset=%d exec=%d enable=%d)", g_vtableHooked ? "installed" : "FAILED", a, b, c, d);
        if (list) list->Close();
        if (g_vtableHooked && g_verbose) CreateThread(nullptr, 0, Heartbeat, nullptr, 0, nullptr);
    } else {
        hexon::Log("could not create temporary D3D12 objects for hooking");
    }
    if (queue) queue->Release();
    if (list) list->Release();
    if (alloc) alloc->Release();
    dev->Release();
}

HRESULT WINAPI HkCreateDevice(IUnknown* adapter, D3D_FEATURE_LEVEL fl, REFIID riid, void** ppDevice) {
    HRESULT hr = g_origCreateDevice(adapter, fl, riid, ppDevice);
    if (SUCCEEDED(hr) && ppDevice && *ppDevice) {
        hexon::Log("D3D12CreateDevice (feature level 0x%x)%s", (unsigned)fl, g_vtableHooked ? " [already hooked]" : "");
        InstallDeviceHooks((IUnknown*)*ppDevice);
    }
    return hr;
}

uint64_t ScanDumpSize() {
    uint64_t total = 0;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((g_dumpDir + L"\\*.dds").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        total += ((uint64_t)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return total;
}

void Init() {
    wchar_t exe[MAX_PATH];
    GetModuleFileNameW(nullptr, exe, MAX_PATH);
    std::wstring dir = exe;
    dir = dir.substr(0, dir.find_last_of(L"\\/"));
    g_dir = dir + L"\\hexon";
    g_dumpDir = g_dir + L"\\dump";
    g_repDir = g_dir + L"\\replace";
    CreateDirectoryW(g_dir.c_str(), nullptr);
    CreateDirectoryW(g_dumpDir.c_str(), nullptr);
    CreateDirectoryW(g_repDir.c_str(), nullptr);

    const std::wstring logPath = g_dir + L"\\hexon.log";
    WIN32_FILE_ATTRIBUTE_DATA fad{};
    const bool bigLog = GetFileAttributesExW(logPath.c_str(), GetFileExInfoStandard, &fad) &&
                        (fad.nFileSizeHigh != 0 || fad.nFileSizeLow > (2u << 20));
    g_log = _wfopen(logPath.c_str(), bigLog ? L"w" : L"a");
    const std::wstring ini = g_dir + L"\\hexon.ini";
    g_dump      = GetPrivateProfileIntW(L"hexon", L"dump", 1, ini.c_str()) != 0;
    g_replace   = GetPrivateProfileIntW(L"hexon", L"replace", 1, ini.c_str()) != 0;
    g_minDim    = GetPrivateProfileIntW(L"hexon", L"min_dim", 64, ini.c_str());
    g_maxDumps  = GetPrivateProfileIntW(L"hexon", L"max_dumps", 20000, ini.c_str());
    g_maxDumpBytes = (uint64_t)GetPrivateProfileIntW(L"hexon", L"max_dump_mb", 4096, ini.c_str()) << 20;
    g_verbose   = GetPrivateProfileIntW(L"hexon", L"verbose", 0, ini.c_str()) != 0;
    g_mips      = GetPrivateProfileIntW(L"hexon", L"mips", 1, ini.c_str()) != 0;
    if (g_replace) ScanReplacements();
    g_dumpBytes = ScanDumpSize();
    hexon::Log("---- Hexon %s started (dump=%d replace=%d mips=%d min_dim=%u, dump folder %llu MB of %llu MB cap) ----", g_keepMarker + 16, g_dump, g_replace, g_mips, g_minDim, (unsigned long long)(g_dumpBytes >> 20), (unsigned long long)(g_maxDumpBytes >> 20));

    if (MH_Initialize() != MH_OK) { hexon::Log("MH_Initialize failed"); return; }
    LoadLibraryW(L"d3d12.dll");
    MH_STATUS s = MH_CreateHookApi(L"d3d12", "D3D12CreateDevice", (void*)HkCreateDevice, (void**)&g_origCreateDevice);
    if (s == MH_OK) s = MH_EnableHook(MH_ALL_HOOKS);
    hexon::Log("D3D12CreateDevice hook: %s", s == MH_OK ? "ok" : "FAILED");
}

}

void hexon::OnFactoryCreated() {
    static std::once_flag once;
    std::call_once(once, Init);
}
