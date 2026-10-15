#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "hexon.h"

static HMODULE RealDxgi() {
    static HMODULE mod = [] {
        wchar_t path[MAX_PATH];
        GetSystemDirectoryW(path, MAX_PATH);
        lstrcatW(path, L"\\dxgi.dll");
        return LoadLibraryW(path);
    }();
    return mod;
}

template <typename F> static F Real(const char* name) {
    return reinterpret_cast<F>(reinterpret_cast<void*>(GetProcAddress(RealDxgi(), name)));
}

extern "C" {

HRESULT WINAPI hx_CreateDXGIFactory(REFIID riid, void** pp) {
    static auto fn = Real<HRESULT(WINAPI*)(REFIID, void**)>("CreateDXGIFactory");
    hexon::OnFactoryCreated();
    return fn ? fn(riid, pp) : E_FAIL;
}
HRESULT WINAPI hx_CreateDXGIFactory1(REFIID riid, void** pp) {
    static auto fn = Real<HRESULT(WINAPI*)(REFIID, void**)>("CreateDXGIFactory1");
    hexon::OnFactoryCreated();
    return fn ? fn(riid, pp) : E_FAIL;
}
HRESULT WINAPI hx_CreateDXGIFactory2(UINT flags, REFIID riid, void** pp) {
    static auto fn = Real<HRESULT(WINAPI*)(UINT, REFIID, void**)>("CreateDXGIFactory2");
    hexon::OnFactoryCreated();
    return fn ? fn(flags, riid, pp) : E_FAIL;
}
HRESULT WINAPI hx_DXGIGetDebugInterface1(UINT flags, REFIID riid, void** pp) {
    static auto fn = Real<HRESULT(WINAPI*)(UINT, REFIID, void**)>("DXGIGetDebugInterface1");
    return fn ? fn(flags, riid, pp) : E_NOINTERFACE;
}
HRESULT WINAPI hx_DXGIDeclareAdapterRemovalSupport() {
    static auto fn = Real<HRESULT(WINAPI*)()>("DXGIDeclareAdapterRemovalSupport");
    return fn ? fn() : S_OK;
}

}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(inst);
    return TRUE;
}
