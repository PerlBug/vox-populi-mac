#pragma once
#include "vp_mac/win32_types.hpp"
#include <cerrno>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <pthread.h>
#include <chrono>
#include <thread>

extern "C" DWORD timeGetTime();
inline DWORD GetTickCount() { return timeGetTime(); }
inline DWORD GetCurrentThreadId() {
    std::uint64_t thread_id = 0;
    pthread_threadid_np(nullptr, &thread_id);
    return static_cast<DWORD>(thread_id);
}
inline void Sleep(DWORD milliseconds) {
    if (milliseconds) std::this_thread::sleep_for(std::chrono::milliseconds(milliseconds));
    else std::this_thread::yield();
}

inline DWORD GetModuleFileName(HMODULE module, char* buffer, DWORD capacity) {
    if (!buffer || !capacity) { errno = EINVAL; return 0; }
    Dl_info info{};
    const char* path = module ? (dladdr(module, &info) ? info.dli_fname : nullptr) : _dyld_get_image_name(0);
    if (!path) { buffer[0] = '\0'; errno = EINVAL; return 0; }
    const std::size_t length = std::strlen(path);
    const std::size_t copied = length < capacity ? length : capacity - 1;
    std::memcpy(buffer, path, copied);
    buffer[copied] = '\0';
    if (length >= capacity) { errno = ERANGE; return capacity; }
    return static_cast<DWORD>(length);
}
