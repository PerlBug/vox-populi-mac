// Synthetic stock core. No proprietary game code or object layout is used.
#include <cstdint>
#include <cstdio>
#include <cstdlib>

extern "C" unsigned int timeGetTime(); // supplied by the fake game executable

extern "C" void* DllGetGameContext() {
    if (timeGetTime() != 1337) return nullptr;
    return reinterpret_cast<void*>(uintptr_t{0x51B00B1E});
}

__attribute__((destructor)) static void on_unload() {
    const char* path = std::getenv("VOX_POP_MAC_PROBE_LOG");
    if (!path) return;
    if (FILE* file = std::fopen(path, "a")) {
        std::fputs("fixture_unloaded\n", file);
        std::fclose(file);
    }
}
