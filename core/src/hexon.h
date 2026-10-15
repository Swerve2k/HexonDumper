#pragma once
namespace hexon {
void OnFactoryCreated();
#if defined(__GNUC__)
__attribute__((format(gnu_printf, 1, 2)))
#endif
void Log(const char* fmt, ...);
}
