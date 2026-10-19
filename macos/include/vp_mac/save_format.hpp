#pragma once
#include "vp_mac/win32_types.hpp"
#include "vp_mac/engine_identity.hpp"

class FDataStream;
namespace vp_mac {
inline GUID native_save_guid() {
    GUID result;
    static_assert(sizeof(result) == sizeof(sdk::kNativeSaveGuid), "Native core GUID layout");
    std::memcpy(&result, &sdk::kNativeSaveGuid, sizeof(result));
    return result;
}
inline bool save_header_matches(const void* bytes, std::size_t size) {
    return size == sdk::kNativeSaveHeader.size() &&
           std::memcmp(bytes, sdk::kNativeSaveHeader.data(), size) == 0;
}
void write_save_boundary(FDataStream& stream);
void read_save_boundary(FDataStream& stream);
}
