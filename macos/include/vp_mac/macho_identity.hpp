#pragma once
#include "vp_mac/engine_identity.hpp"
#include <cstring>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>

namespace vp_mac {
inline bool image_uuid_matches(const void* image, const std::array<unsigned char, 16>& expected) {
    const auto* header = static_cast<const mach_header_64*>(image);
    if (!header || header->magic != MH_MAGIC_64 || header->cputype != CPU_TYPE_X86_64 ||
        header->ncmds > 4096 || header->sizeofcmds > 16 * 1024 * 1024) return false;
    const auto* current = reinterpret_cast<const unsigned char*>(header + 1);
    const auto* end = current + header->sizeofcmds;
    for (unsigned i = 0; i < header->ncmds; ++i) {
        if (static_cast<size_t>(end - current) < sizeof(load_command)) return false;
        const auto* command = reinterpret_cast<const load_command*>(current);
        if (command->cmdsize < sizeof(load_command) || command->cmdsize > static_cast<size_t>(end - current)) return false;
        if (command->cmd == LC_UUID && command->cmdsize == sizeof(uuid_command)) {
            const auto* uuid = reinterpret_cast<const uuid_command*>(current);
            return std::memcmp(uuid->uuid, expected.data(), expected.size()) == 0;
        }
        current += command->cmdsize;
    }
    return false;
}
inline bool host_is_reviewed() { return image_uuid_matches(_dyld_get_image_header(0), sdk::k_host_uuid); }
} // namespace vp_mac
