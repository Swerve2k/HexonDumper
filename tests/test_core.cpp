#include "../core/src/hexon.cpp"

#include <dxgi1_4.h>
#include <functional>

static int fails = 0, checks = 0;
#define CHECK(c) do { ++checks; if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); ++fails; } } while (0)

static std::wstring g_root;

static bool WaitFor(const std::function<bool()>& f, DWORD ms = 8000) {
    const ULONGLONG end = GetTickCount64() + ms;
    while (GetTickCount64() < end) {
        if (f()) return true;
        Sleep(20);
    }
    return f();
}

static std::vector<uint8_t> Pattern(size_t n, uint8_t seed) {
    std::vector<uint8_t> v(n);
    for (size_t i = 0; i < n; ++i) v[i] = (uint8_t)(i * 13 + seed * 31 + (i >> 8));
    return v;
}

static std::vector<uint8_t> DdsFile(UINT w, UINT h, const std::vector<std::vector<uint8_t>>& levels) {
    hexon_dds::Header hd{};
    hd.size = 124;
    hd.flags = 0x1 | 0x2 | 0x4 | 0x1000 | (levels.size() > 1 ? 0x20000u : 0u);
    hd.height = h;
    hd.width = w;
    hd.depth = 1;
    hd.mipMapCount = (uint32_t)levels.size();
    hd.ddspf.size = 32;
    hd.ddspf.flags = 0x4;
    hd.ddspf.fourCC = hexon_dds::kFourCcDx10;
    hd.caps = 0x1000;
    hexon_dds::HeaderDx10 dx{};
    dx.dxgiFormat = DXGI_FORMAT_R8G8B8A8_UNORM;
    dx.resourceDimension = 3;
    dx.arraySize = 1;
    std::vector<uint8_t> out(4 + sizeof hd + sizeof dx);
    memcpy(out.data(), &hexon_dds::kMagic, 4);
    memcpy(out.data() + 4, &hd, sizeof hd);
    memcpy(out.data() + 4 + sizeof hd, &dx, sizeof dx);
    for (const auto& l : levels) out.insert(out.end(), l.begin(), l.end());
    return out;
}

static void WriteFileBytes(const std::wstring& path, const std::vector<uint8_t>& data) {
    FILE* f = _wfopen(path.c_str(), L"wb");
    fwrite(data.data(), 1, data.size(), f);
    fclose(f);
}

static void WriteAtomic(const std::wstring& path, const std::vector<uint8_t>& data) {
    const std::wstring part = path + L".part";
    WriteFileBytes(part, data);
    MoveFileExW(part.c_str(), path.c_str(), MOVEFILE_REPLACE_EXISTING);
}

static uint64_t ExpectedHash(UINT w, UINT h, const std::vector<uint8_t>& tight) {
    const uint64_t seed = 0xcbf29ce484222325ULL ^ ((uint64_t)w | ((uint64_t)h << 16) | (4ull << 32));
    return Hash64(tight.data(), tight.size(), seed);
}

static std::string ReadText(const std::wstring& path) {
    std::vector<uint8_t> b;
    ReadWholeFile(path, b);
    return std::string(b.begin(), b.end());
}

static size_t CountLinesStarting(const std::string& text, const std::string& prefix) {
    size_t n = 0, pos = 0;
    while (pos < text.size()) {
        size_t end = text.find('\n', pos);
        if (end == std::string::npos) end = text.size();
        if (text.compare(pos, prefix.size(), prefix) == 0) ++n;
        pos = end + 1;
    }
    return n;
}

static std::vector<std::string> Fields(const std::string& text, const std::string& prefix) {
    size_t pos = text.find("\n" + prefix);
    std::vector<std::string> out;
    if (pos == std::string::npos) return out;
    ++pos;
    const size_t end = text.find('\n', pos);
    std::string line = text.substr(pos, end - pos);
    size_t a = 0;
    while (true) {
        const size_t b = line.find('\t', a);
        out.push_back(line.substr(a, b == std::string::npos ? std::string::npos : b - a));
        if (b == std::string::npos) break;
        a = b + 1;
    }
    return out;
}

static std::string Hex(uint64_t v) {
    char b[17];
    snprintf(b, sizeof b, "%016llx", (unsigned long long)v);
    return b;
}

struct Gpu {
    ID3D12Device* dev = nullptr;
    ID3D12CommandQueue* q = nullptr;
    ID3D12CommandAllocator* alloc = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    ID3D12Fence* fence = nullptr;
    HANDLE ev = nullptr;
    UINT64 val = 0;

    bool Init() {
        IDXGIFactory4* f = nullptr;
        IDXGIAdapter* warp = nullptr;
        if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory4), (void**)&f))) return false;
        const bool ok = SUCCEEDED(f->EnumWarpAdapter(__uuidof(IDXGIAdapter), (void**)&warp)) &&
                        SUCCEEDED(D3D12CreateDevice(warp, D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device), (void**)&dev));
        if (warp) warp->Release();
        f->Release();
        if (!ok) return false;
        InstallDeviceHooks(dev);
        D3D12_COMMAND_QUEUE_DESC qd{};
        qd.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        return SUCCEEDED(dev->CreateCommandQueue(&qd, __uuidof(ID3D12CommandQueue), (void**)&q)) &&
               SUCCEEDED(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, __uuidof(ID3D12CommandAllocator), (void**)&alloc)) &&
               SUCCEEDED(dev->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc, nullptr, __uuidof(ID3D12GraphicsCommandList), (void**)&list)) &&
               SUCCEEDED(list->Close()) &&
               SUCCEEDED(dev->CreateFence(0, D3D12_FENCE_FLAG_NONE, __uuidof(ID3D12Fence), (void**)&fence)) &&
               (ev = CreateEventW(nullptr, FALSE, FALSE, nullptr)) != nullptr;
    }

    void Begin() {
        alloc->Reset();
        list->Reset(alloc, nullptr);
    }

    void Submit() {
        list->Close();
        ID3D12CommandList* l = list;
        q->ExecuteCommandLists(1, &l);
        q->Signal(fence, ++val);
        fence->SetEventOnCompletion(val, ev);
        WaitForSingleObject(ev, 10000);
    }

    ID3D12Resource* Buffer(UINT64 size, D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
        D3D12_HEAP_PROPERTIES hp{};
        hp.Type = type;
        D3D12_RESOURCE_DESC d{};
        d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        d.Width = size;
        d.Height = 1;
        d.DepthOrArraySize = 1;
        d.MipLevels = 1;
        d.SampleDesc.Count = 1;
        d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ID3D12Resource* r = nullptr;
        dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, state, nullptr, __uuidof(ID3D12Resource), (void**)&r);
        return r;
    }

    ID3D12Resource* Texture(UINT w, UINT h, UINT mips) {
        D3D12_HEAP_PROPERTIES hp{};
        hp.Type = D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC d{};
        d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        d.Width = w;
        d.Height = h;
        d.DepthOrArraySize = 1;
        d.MipLevels = (UINT16)mips;
        d.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        d.SampleDesc.Count = 1;
        ID3D12Resource* r = nullptr;
        dev->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                     __uuidof(ID3D12Resource), (void**)&r);
        return r;
    }

    void Footprint(ID3D12Resource* tex, UINT sub, D3D12_PLACED_SUBRESOURCE_FOOTPRINT& fp, UINT& rows, UINT64& total) {
        const D3D12_RESOURCE_DESC d = tex->GetDesc();
        UINT64 rowSize = 0;
        dev->GetCopyableFootprints(&d, sub, 1, 0, &fp, &rows, &rowSize, &total);
    }

    void Upload(ID3D12Resource* tex, UINT sub, const std::vector<uint8_t>& tight) {
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};
        UINT rows = 0;
        UINT64 total = 0;
        Footprint(tex, sub, fp, rows, total);
        ID3D12Resource* up = Buffer(total, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
        uint8_t* p = nullptr;
        up->Map(0, nullptr, (void**)&p);
        const UINT rowBytes = fp.Footprint.Width * 4;
        for (UINT r = 0; r < rows; ++r) memcpy(p + fp.Offset + (size_t)r * fp.Footprint.RowPitch, tight.data() + (size_t)r * rowBytes, rowBytes);
        up->Unmap(0, nullptr);
        Begin();
        D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
        dst.pResource = tex;
        dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.SubresourceIndex = sub;
        src.pResource = up;
        src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        src.PlacedFootprint = fp;
        list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        Submit();
        up->Release();
    }

    std::vector<uint8_t> Read(ID3D12Resource* tex, UINT sub) {
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};
        UINT rows = 0;
        UINT64 total = 0;
        Footprint(tex, sub, fp, rows, total);
        ID3D12Resource* rb = Buffer(total, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
        Begin();
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition.pResource = tex;
        b.Transition.Subresource = sub;
        b.Transition.StateBefore = D3D12_RESOURCE_STATE_COPY_DEST;
        b.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
        list->ResourceBarrier(1, &b);
        D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
        dst.pResource = rb;
        dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint = fp;
        src.pResource = tex;
        src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.SubresourceIndex = sub;
        list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        std::swap(b.Transition.StateBefore, b.Transition.StateAfter);
        list->ResourceBarrier(1, &b);
        Submit();
        std::vector<uint8_t> out((size_t)fp.Footprint.Width * 4 * rows);
        uint8_t* p = nullptr;
        rb->Map(0, nullptr, (void**)&p);
        const UINT rowBytes = fp.Footprint.Width * 4;
        for (UINT r = 0; r < rows; ++r) memcpy(out.data() + (size_t)r * rowBytes, p + fp.Offset + (size_t)r * fp.Footprint.RowPitch, rowBytes);
        rb->Unmap(0, nullptr);
        rb->Release();
        return out;
    }
};

static void TestPureHelpers() {
    const std::string line = IndexLine(0xabcull, 64, 32, "BC7", 1, 3, 0, 128, 64, 7, 0xffull, 1700000000000ull);
    CHECK(line == "0000000000000abc\t64\t32\tBC7\t1\t3\t0\t128\t64\t0000000000000007\t00000000000000ff\t1700000000000\n");
    std::string text = std::string(kIndexHeader) + line + "zzzz\n0000000000000def\tx\n00000000000001\tshort\n";
    std::vector<uint8_t> buf(text.begin(), text.end());
    std::unordered_set<uint64_t> got;
    CHECK(LoadIndexedHashes(buf, got) == 2 && got.count(0xabc) && got.count(0xdef));
    std::vector<uint8_t> headerOnly(kIndexHeader, kIndexHeader + strlen(kIndexHeader));
    got.clear();
    CHECK(LoadIndexedHashes(headerOnly, got) == 0);
    CHECK(UnixMillis() > 1700000000000ull && NewSessionId() != NewSessionId());
}

static void TestWatcherAlone() {
    const std::wstring a = g_repDir + L"\\00000000000000aa_8x8_RGBA8.dds";
    WriteAtomic(a, DdsFile(8, 8, {Pattern(256, 1)}));
    CHECK(WaitFor([] {
        auto t = CurrentTable();
        auto it = t->byHash.find(0xaa);
        if (it == t->byHash.end()) return false;
        std::lock_guard<std::mutex> lk(it->second->mu);
        return it->second->loaded && it->second->valid;
    }));
    CHECK(SigKnown(*CurrentTable(), 8, 8, "RGBA8") && !SigKnown(*CurrentTable(), 8, 8, "BC7"));
    RepEntry* first = FindRep(*CurrentTable(), 0xaa);
    CHECK(first && first->data == Pattern(256, 1));
    WriteAtomic(a, DdsFile(8, 8, {Pattern(256, 2)}));
    CHECK(WaitFor([&] { RepEntry* e = FindRep(*CurrentTable(), 0xaa); return e && e != first && e->data == Pattern(256, 2); }));
    WriteFileBytes(g_repDir + L"\\00000000000000bb_8x8_RGBA8.dds", std::vector<uint8_t>(40, 7));
    WriteFileBytes(g_repDir + L"\\notes.txt", std::vector<uint8_t>(4, 1));
    WriteFileBytes(g_repDir + L"\\00000000000000cc_8x8_RGBA8.ddsx", DdsFile(8, 8, {Pattern(256, 3)}));
    CHECK(WaitFor([] { auto t = CurrentTable(); return t->byHash.count(0xbb) == 1; }));
    RepEntry* junk = FindRep(*CurrentTable(), 0xbb);
    CHECK(junk && !junk->valid);
    CHECK(CurrentTable()->byHash.count(0xcc) == 0);
    DeleteFileW(a.c_str());
    DeleteFileW((g_repDir + L"\\00000000000000bb_8x8_RGBA8.dds").c_str());
    DeleteFileW((g_repDir + L"\\00000000000000cc_8x8_RGBA8.ddsx").c_str());
    DeleteFileW((g_repDir + L"\\notes.txt").c_str());
    CHECK(WaitFor([] { return CurrentTable()->byHash.empty(); }));
    CHECK(!SigKnown(*CurrentTable(), 8, 8, "RGBA8"));
}

static void TestEndToEnd() {
    Gpu gpu;
    if (!gpu.Init()) {
        printf("SKIP: could not create a WARP D3D12 device\n");
        return;
    }
    CHECK(g_vtableHooked);

    const UINT W = 64, H = 64;
    ID3D12Resource* texA = gpu.Texture(W, H, 1);
    const std::vector<uint8_t> a1 = Pattern(W * H * 4, 11);
    const uint64_t hashA = ExpectedHash(W, H, a1);
    gpu.Upload(texA, 0, a1);
    CHECK(gpu.Read(texA, 0) == a1);
    const std::wstring dumpA = g_dumpDir + L"\\" + HexName(hashA, W, H, "RGBA8");
    CHECK(GetFileAttributesW(dumpA.c_str()) != INVALID_FILE_ATTRIBUTES);
    std::string index = ReadText(g_dumpDir + L"\\index.tsv");
    CHECK(index.compare(0, strlen(kIndexHeader), kIndexHeader) == 0);
    auto fa = Fields(index, Hex(hashA));
    CHECK(fa.size() == 12 && fa[1] == "64" && fa[2] == "64" && fa[3] == "RGBA8" && fa[4] == "0" && fa[5] == "1" &&
          fa[7] == "64" && fa[8] == "64" && fa[10] == Hex(g_session));
    gpu.Upload(texA, 0, a1);
    CHECK(CountLinesStarting(ReadText(g_dumpDir + L"\\index.tsv"), Hex(hashA)) == 1);

    ID3D12Resource* texB = gpu.Texture(W, H, 3);
    std::vector<std::vector<uint8_t>> bLevels = {Pattern(64 * 64 * 4, 21), Pattern(32 * 32 * 4, 22), Pattern(16 * 16 * 4, 23)};
    for (UINT m = 0; m < 3; ++m) gpu.Upload(texB, m, bLevels[m]);
    index = ReadText(g_dumpDir + L"\\index.tsv");
    auto b0 = Fields(index, Hex(ExpectedHash(64, 64, bLevels[0])));
    auto b1 = Fields(index, Hex(ExpectedHash(32, 32, bLevels[1])));
    auto b2 = Fields(index, Hex(ExpectedHash(16, 16, bLevels[2])));
    CHECK(b0.size() == 12 && b1.size() == 12 && b2.size() == 12);
    if (b0.size() == 12 && b1.size() == 12 && b2.size() == 12) {
        CHECK(b0[4] == "0" && b1[4] == "1" && b2[4] == "2");
        CHECK(b0[5] == "3" && b1[5] == "3" && b2[5] == "3");
        CHECK(b1[7] == "64" && b2[8] == "64");
        CHECK(b0[9] == b1[9] && b1[9] == b2[9] && b0[9] != fa[9]);
    }

    const std::wstring repA = g_repDir + L"\\" + HexName(hashA, W, H, "RGBA8");
    const std::vector<uint8_t> a2 = Pattern(W * H * 4, 12), a3 = Pattern(W * H * 4, 13);
    WriteAtomic(repA, DdsFile(W, H, {a2}));
    CHECK(WaitFor([&] { RepEntry* e = FindRep(*CurrentTable(), hashA); return e && e->valid && e->data == a2; }));
    gpu.Upload(texA, 0, a1);
    CHECK(gpu.Read(texA, 0) == a2);
    WriteAtomic(repA, DdsFile(W, H, {a3}));
    CHECK(WaitFor([&] { RepEntry* e = FindRep(*CurrentTable(), hashA); return e && e->valid && e->data == a3; }));
    gpu.Upload(texA, 0, a1);
    CHECK(gpu.Read(texA, 0) == a3);
    WriteAtomic(repA, std::vector<uint8_t>(64, 9));
    CHECK(WaitFor([&] { RepEntry* e = FindRep(*CurrentTable(), hashA); return e && !e->valid; }));
    gpu.Upload(texA, 0, a1);
    CHECK(gpu.Read(texA, 0) == a1);
    DeleteFileW(repA.c_str());
    CHECK(WaitFor([&] { return CurrentTable()->byHash.count(hashA) == 0; }));
    gpu.Upload(texA, 0, a1);
    CHECK(gpu.Read(texA, 0) == a1);

    g_minDim = 32;
    const uint64_t hashB = ExpectedHash(64, 64, bLevels[0]);
    std::vector<std::vector<uint8_t>> rLevels = {Pattern(64 * 64 * 4, 31), Pattern(32 * 32 * 4, 32), Pattern(16 * 16 * 4, 33)};
    const std::wstring repB = g_repDir + L"\\" + HexName(hashB, 64, 64, "RGBA8");
    WriteAtomic(repB, DdsFile(64, 64, rLevels));
    CHECK(WaitFor([&] { RepEntry* e = FindRep(*CurrentTable(), hashB); return e && e->valid && e->mips.size() == 3; }));
    for (UINT m = 0; m < 3; ++m) gpu.Upload(texB, m, bLevels[m]);
    for (UINT m = 0; m < 3; ++m) CHECK(gpu.Read(texB, m) == rLevels[m]);
    DeleteFileW(repB.c_str());
    CHECK(WaitFor([&] { return CurrentTable()->byHash.count(hashB) == 0; }));
    g_minDim = 4;

    fclose(g_index);
    g_index = nullptr;
    OpenIndex();
    CHECK(g_indexed.count(hashA) && g_indexed.count(hashB) && g_indexed.size() == 4);
    gpu.Upload(texA, 0, a1);
    CHECK(CountLinesStarting(ReadText(g_dumpDir + L"\\index.tsv"), Hex(hashA)) == 1);

    texA->Release();
    texB->Release();
    gpu.list->Release();
    gpu.alloc->Release();
    gpu.q->Release();
    gpu.fence->Release();
    CloseHandle(gpu.ev);
    gpu.dev->Release();
}

static void RemoveTree(const std::wstring& dir) {
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((dir + L"\\*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            const std::wstring n = fd.cFileName;
            if (n == L"." || n == L"..") continue;
            const std::wstring p = dir + L"\\" + n;
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) RemoveTree(p);
            else DeleteFileW(p.c_str());
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    RemoveDirectoryW(dir.c_str());
}

int main() {
    wchar_t tmp[MAX_PATH];
    GetTempPathW(MAX_PATH, tmp);
    g_root = std::wstring(tmp) + L"hexon_core_" + std::to_wstring(GetCurrentProcessId());
    g_dir = g_root + L"\\hexon";
    g_dumpDir = g_dir + L"\\dump";
    g_repDir = g_dir + L"\\replace";
    CreateDirectoryW(g_root.c_str(), nullptr);
    CreateDirectoryW(g_dir.c_str(), nullptr);
    CreateDirectoryW(g_dumpDir.c_str(), nullptr);
    CreateDirectoryW(g_repDir.c_str(), nullptr);
    g_log = _wfopen((g_dir + L"\\hexon.log").c_str(), L"w");
    g_dump = g_replace = g_mips = true;
    g_minDim = 4;
    g_maxDumps = 100000;
    g_maxDumpBytes = 1ull << 30;
    g_session = NewSessionId();
    OpenIndex();
    RescanReplacements(false, false);
    StartWatcher();
    CHECK(MH_Initialize() == MH_OK);

    TestPureHelpers();
    TestWatcherAlone();
    TestEndToEnd();

    StopWatcher();
    if (g_index) fclose(g_index);
    if (g_log) fclose(g_log);
    g_index = nullptr;
    g_log = nullptr;
    MH_Uninitialize();
    RemoveTree(g_root);
    printf("%d checks, %d failures\n", checks, fails);
    printf(fails ? "SOME FAILED\n" : "ALL PASSED\n");
    return fails != 0;
}
