#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <sys/sysctl.h>

#if !defined(__x86_64__)
#error This host must exercise the Intel process ABI used by Civ V.
#endif

extern "C" __attribute__((visibility("default")))
unsigned int timeGetTime() { return 1337; }

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    int translated = 0;
    size_t size = sizeof(translated);
    if (sysctlbyname("sysctl.proc_translated", &translated, &size, nullptr, 0) == 0)
        std::printf("architecture=x86_64 rosetta_translated=%d\n", translated);
    else
        std::printf("architecture=x86_64 rosetta_translated=unknown query_errno=%d\n", errno);
    const bool expect_failure = std::strcmp(argv[2], "failure") == 0;
    const int calls = std::strcmp(argv[2], "stress") == 0 ? 100000 : 3;
    for (int cycle = 0; cycle != 2; ++cycle) {
        void* library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
        if (!library) {
            std::fprintf(stderr, "wrapper dlopen: %s\n", dlerror());
            return 3;
        }
        auto get = reinterpret_cast<void* (*)()>(dlsym(library, "DllGetGameContext"));
        if (!get) return 4;
        for (int call = 0; call != calls; ++call) {
            void* context = get();
            void* expected = expect_failure ? nullptr :
                reinterpret_cast<void*>(uintptr_t{0x51B00B1E});
            if (context != expected) {
                std::fprintf(stderr, "unexpected context: %p\n", context);
                return 5;
            }
        }
        if (dlclose(library) != 0) return 6;
    }
    return 0;
}
