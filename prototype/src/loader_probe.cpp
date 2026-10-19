// Stage 1: preserve the stock core's opaque context pointer and lifecycle.
// No Civ V C++ interface or shared object layout is assumed here.
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <dlfcn.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <unistd.h>
#ifdef VP_MAC_ABI_PROBES
#include "vp_mac/abi_probe.hpp"
#endif

namespace {
constexpr char kMarker[] = "VOX_POP_MAC_LOADER_PROBE_V1";
constexpr char kOriginal[] = "libCvGameCoreDLL_Expansion2_DLL.vp-original.dylib";
using GetContext = void* (*)();
pthread_once_t load_once = PTHREAD_ONCE_INIT;
void* original_handle = nullptr;
GetContext original_get_context = nullptr;
unsigned long long forward_count = 0;

void log_event(const char* event, const char* detail = "") {
    const int saved_errno = errno;
    if (!detail) detail = "no loader diagnostic available";
    char default_path[PATH_MAX];
    const char* path = std::getenv("VOX_POP_MAC_PROBE_LOG");
    if (!path || !*path) {
        const char* home = std::getenv("HOME");
        if (!home) home = "/tmp";
        const int length = std::snprintf(default_path, sizeof(default_path),
            "%s/Library/Application Support/Sid Meier's Civilization 5/Logs/"
            "VoxPopMacLoaderProbe.log", home);
        if (length < 0 || static_cast<size_t>(length) >= sizeof(default_path)) {
            errno = saved_errno;
            return;
        }
        path = default_path;
    }
    char timestamp[32] = "unknown-time";
    const time_t now = std::time(nullptr);
    struct tm utc;
    if (gmtime_r(&now, &utc))
        std::strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%SZ", &utc);
    char line[8192];
    const int length = std::snprintf(line, sizeof(line),
        "%s pid=%d event=%s %s\n", timestamp, getpid(), event, detail);
    const size_t count = length > 0 ? static_cast<size_t>(length) : 0;
    const int fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
    if (fd >= 0) {
        if (count && count < sizeof(line)) {
            // One append keeps separate processes' event lines together.
            ssize_t result;
            do { result = write(fd, line, count); } while (result < 0 && errno == EINTR);
        }
        close(fd);
    } else {
        std::fprintf(stderr, "[VoxPopMacProbe] %s %s (log unavailable: %s)\n",
                     event, detail, std::strerror(errno));
    }
    errno = saved_errno;
}

void inspect_host_exports() {
    const char* names[] = {
        "timeGetTime", "lua_gettop", "_ZN8Database7Results4StepEv",
        "_ZN12Localization6String6toUTF8Ev", "_ZN11FDataStream4ReadERi"
    };
    for (const char* name : names) {
        dlerror();
        void* address = dlsym(RTLD_DEFAULT, name);
        const char* error = dlerror();
        char detail[256];
        std::snprintf(detail, sizeof(detail), "symbol=%s available=%s",
                      name, address && !error ? "yes" : "no");
        log_event("host_symbol", detail);
    }
}

void load_original() {
    Dl_info self{};
    char resolved[PATH_MAX];
    if (!dladdr(reinterpret_cast<const void*>(&load_original), &self) ||
        !self.dli_fname || !realpath(self.dli_fname, resolved)) {
        log_event("original_path_failed", "cannot locate wrapper image");
        return;
    }
    char* slash = std::strrchr(resolved, '/');
    if (!slash) {
        log_event("original_path_failed", "wrapper has no directory");
        return;
    }
    slash[1] = '\0';
    char path[PATH_MAX];
    const int length = std::snprintf(path, sizeof(path), "%s%s", resolved, kOriginal);
    if (length < 0 || static_cast<size_t>(length) >= sizeof(path)) {
        log_event("original_path_failed", "original path is too long");
        return;
    }
    log_event("original_loading", path);
    original_handle = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!original_handle) {
        log_event("original_open_failed", dlerror());
        return;
    }
    dlerror();
    void* symbol = dlsym(original_handle, "DllGetGameContext");
    const char* error = dlerror();
    if (error || !symbol) {
        log_event("original_symbol_failed", error ? error : "null entry point");
        dlclose(original_handle);
        original_handle = nullptr;
        return;
    }
    // A misinstalled copy of this wrapper must never call itself recursively.
    Dl_info provider{};
    if (!dladdr(symbol, &provider) || provider.dli_fbase == self.dli_fbase) {
        log_event("original_recursion_refused", "entry point resolves to this wrapper");
        dlclose(original_handle);
        original_handle = nullptr;
        return;
    }
    original_get_context = reinterpret_cast<GetContext>(symbol);
    log_event("original_ready", path);
}

__attribute__((constructor)) void on_load() {
    log_event("wrapper_loaded", kMarker);
    inspect_host_exports();
    pthread_once(&load_once, load_original);
}

__attribute__((destructor)) void on_unload() {
    if (original_handle) {
        char detail[128];
        std::snprintf(detail, sizeof(detail), "forwarded_calls=%llu",
                      __atomic_load_n(&forward_count, __ATOMIC_RELAXED));
        log_event("original_unloading", detail);
        const int result = dlclose(original_handle);
        original_handle = nullptr;
        original_get_context = nullptr;
        log_event(result == 0 ? "original_unloaded" : "original_unload_failed");
    }
    log_event("wrapper_unloaded");
}
} // namespace

extern "C" __attribute__((visibility("default")))
void* DllGetGameContext() {
    pthread_once(&load_once, load_original);
    if (!original_get_context) {
        log_event("forward_failed", "original entry point unavailable");
        return nullptr;
    }
    void* context = original_get_context();
    const auto count = __atomic_add_fetch(&forward_count, 1, __ATOMIC_RELAXED);
#ifdef VP_MAC_ABI_PROBES
    if (count == 1 && context)
        vp_mac::probe_runtime_abi(context, reinterpret_cast<const void*>(original_get_context), log_event);
#endif
    // The engine calls this accessor millions of times during ordinary play.
    // Sample successful calls exponentially; keep the hot path free of file I/O.
    if (!context || count <= 3 || (count & (count - 1)) == 0) {
        char detail[128];
        std::snprintf(detail, sizeof(detail), "call=%llu context=%p", count, context);
        log_event(context ? "context_forwarded" : "original_returned_null", detail);
    }
    return context;
}
