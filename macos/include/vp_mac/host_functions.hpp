#pragma once
#include "vp_mac/macho_identity.hpp"
#include <cstdint>
#include <cstdio>
#include <cstdlib>

namespace vp_mac {
struct HostFunction {
    const char* name;
    std::uintptr_t rva;
    unsigned char code_prefix[32];
};
inline const unsigned char* host_function_address(const HostFunction& function) {
    return reinterpret_cast<const unsigned char*>(_dyld_get_image_header(0)) + function.rva;
}
inline bool host_function_matches(const HostFunction& function) {
    return std::memcmp(host_function_address(function), function.code_prefix, sizeof(function.code_prefix)) == 0;
}
template<class Function> Function host_function(const HostFunction& function) {
    // Cache the resulting pointer at each call site. These checks run before
    // the first call, never by reading the internals of a Lua/SQLite object.
    if (!host_is_reviewed() || !host_function_matches(function)) {
        std::fprintf(stderr, "Vox Populi Mac: unreviewed native entry point: %s\n", function.name);
        std::abort();
    }
    return reinterpret_cast<Function>(const_cast<unsigned char*>(host_function_address(function)));
}
}
