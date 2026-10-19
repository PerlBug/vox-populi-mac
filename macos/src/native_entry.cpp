// Native counterpart of the Windows DLL entry/lifetime translation unit.
#include "CvGameCoreDLLPCH.h"
#include "CvDllContext.h"
#include "vp_mac/macho_identity.hpp"
#include "vp_mac/host_function_profile.hpp"
#include "vp_mac/bridge_checks.hpp"
#include "vp_mac/save_format.hpp"
#include <cstdio>
#include <cstdlib>
#include <sys/stat.h>
#include <unistd.h>

namespace {
void json_string(FILE* file, const char* text) {
    std::fputc('"', file);
    for (const unsigned char* p = reinterpret_cast<const unsigned char*>(text); *p; ++p) {
        if (*p == '"' || *p == '\\') std::fputc('\\', file);
        if (*p < 32) std::fprintf(file, "\\u%04x", *p);
        else std::fputc(*p, file);
    }
    std::fputc('"', file);
}
}

void vp_mac::native_log(const char* event, const char* detail) {
    const char* home = std::getenv("HOME");
    if (!home) return;
    char path[4096];
    int size = std::snprintf(path, sizeof(path), "%s/Library/Application Support/Sid Meier's Civilization 5/Logs", home);
    if (size < 0 || static_cast<std::size_t>(size) >= sizeof(path)) return;
    mkdir(path, 0700);
    size = std::snprintf(path, sizeof(path), "%s/Library/Application Support/Sid Meier's Civilization 5/Logs/VoxPopMacNativeCore.log", home);
    if (size < 0 || static_cast<std::size_t>(size) >= sizeof(path)) return;
    if (FILE* file = std::fopen(path, "a")) {
        std::fputs("{\"event\":", file);
        json_string(file, event);
        std::fprintf(file, ",\"pid\":%d", getpid());
        if (detail) {
            std::fputs(",\"detail\":", file);
            json_string(file, detail);
        }
        std::fputs("}\n", file);
        std::fclose(file);
    }
}

namespace {
class CoreLifetime {
public:
    CoreLifetime() {
        OutputDebugStringA("VOX_POP_MAC_NATIVE_CORE_V1: initialize Community Patch\n");
        if (!vp_mac::check_lock_bridge()) {
            vp_mac::native_log("native_lock_failed");
            std::abort();
        }
        vp_mac::native_log("native_lock_passed");
        if (!vp_mac::check_stream_bridge()) {
            vp_mac::native_log("native_stream_failed");
            std::abort();
        }
        vp_mac::native_log("native_stream_passed");
        if (!vp_mac::check_database_bridge()) {
            vp_mac::native_log("native_database_failed");
            std::abort();
        }
        vp_mac::native_log("native_database_passed");
        CvDllGameContext::InitializeSingleton();
        if (CvDllGameContext::GetSingleton()->GetDLLGUID() != vp_mac::native_save_guid()) {
            vp_mac::native_log("native_save_identity_failed");
            std::abort();
        }
        vp_mac::native_log("native_save_identity_passed", vp_mac::sdk::kNativeSaveGuidText);
        vp_mac::native_log("native_context_ready");
    }
    ~CoreLifetime() {
        CvDllGameContext::DestroySingleton();
        GC.setDLLIFace(nullptr);
        vp_mac::native_log("native_context_destroyed");
    }
};
}

extern "C" __attribute__((visibility("default"))) ICvGameContext1* DllGetGameContext() {
    static const bool ready = [] {
        vp_mac::native_log("native_loaded");
        const bool matched = vp_mac::sdk::host_functions_match();
        vp_mac::native_log(matched ? "native_profile_passed" : "native_profile_failed");
        return matched;
    }();
    if (!ready) {
        std::fputs("Vox Populi Mac: this Civ V executable does not match the reviewed native profile.\n", stderr);
        return nullptr;
    }
    // First entry occurs after the image's C++ globals have been initialized.
    // Local-static lifetime provides one initialization and balanced teardown.
    static CoreLifetime lifetime;
    return CvDllGameContext::GetSingleton();
}
