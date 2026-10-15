cmake_minimum_required(VERSION 3.20)
project(Hexon CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(minhook
    GIT_REPOSITORY https://github.com/TsudaKageyu/minhook.git
    GIT_TAG        v1.3.4)
FetchContent_MakeAvailable(minhook)

add_library(hexon SHARED
    core/src/dxgi_proxy.cpp
    core/src/hexon.cpp
    core/hexon_dxgi.def)
set_target_properties(hexon PROPERTIES OUTPUT_NAME "dxgi" PREFIX "")
target_include_directories(hexon PRIVATE ${minhook_SOURCE_DIR}/include)
target_link_libraries(hexon PRIVATE minhook)
if(MSVC)
    set_property(TARGET hexon PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    set_property(TARGET minhook PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()
