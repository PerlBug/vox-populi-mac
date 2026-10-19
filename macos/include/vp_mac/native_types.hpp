#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <type_traits>

namespace vp_mac {
// Never use LP64 'unsigned long' for Windows GUID.Data1.
struct Guid {
    std::uint32_t Data1;
    std::uint16_t Data2;
    std::uint16_t Data3;
    std::uint8_t Data4[8];
};
inline bool operator==(const Guid& left, const Guid& right) {
    return std::memcmp(&left, &right, sizeof(Guid)) == 0;
}
inline bool operator!=(const Guid& left, const Guid& right) { return !(left == right); }

static_assert(sizeof(void*) == 8 && sizeof(long) == 8 && sizeof(wchar_t) == 4, "Native LP64 target");
static_assert(sizeof(Guid) == 16 && alignof(Guid) == 4, "Native GUID layout");
static_assert(offsetof(Guid, Data4) == 8 && std::is_trivially_copyable<Guid>::value,
              "Native GUID must retain its POD layout");
} // namespace vp_mac
