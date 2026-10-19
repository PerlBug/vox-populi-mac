#include "vp_mac/win32_types.hpp"
#include "vp_mac/host_function_profile.hpp"
#include "vp_mac/save_format.hpp"
#include <FireWorks/FFireTypes.h>
#include <FireWorks/FCrc32.h>
#include <FireWorks/FCriticalSection.h>
#include <CvGameDatabase.h>
#include <hash_map>
#include <cstdio>
#include <type_traits>

// Include the original SDK by its normal path. The file overlay must suppress
// its non-Windows GUID fallback, which wrongly uses LP64 unsigned long.
static_assert(sizeof(GUID) == sizeof(vp_mac::Guid));
static_assert(sizeof(GUID::Data1) == 4);
static_assert(std::is_standard_layout_v<GUID> && std::is_trivially_copyable_v<GUID>);
static_assert(sizeof(qword) == 8);
static_assert(sizeof(dword) == 4);
static_assert(sizeof(FCRC) == 1032);
static_assert(sizeof(FCriticalSection) == 40 && alignof(FCriticalSection) == 8);
static_assert(sizeof(Database::Connection) == 184 && sizeof(Database::Results) == 112);

struct ReverseLess {
    // Deliberately collide: equality must use both directions of the binary
    // ordering predicate, rather than treating "less than" as equality.
    std::size_t operator()(int) const { return 0; }
    bool operator()(int a, int b) const { return a > b; }
};
int main() {
    auto header = vp_mac::sdk::kNativeSaveHeader;
    if (!vp_mac::save_header_matches(header.data(), header.size()) ||
        vp_mac::save_header_matches(header.data(), header.size() - 1)) return 1;
    for (std::size_t i = 0; i < header.size(); ++i) {
        header[i] ^= 1;
        if (vp_mac::save_header_matches(header.data(), header.size())) return 1;
        header[i] ^= 1;
    }
    // This test executable is not the reviewed game. The guard must stop
    // before reading any of the executable-relative native function addresses.
    if (vp_mac::sdk::host_functions_match()) return 1;
    const GUID a{0x83f34ff0, 0x3d60, 0x43e7, {0xae, 0xdb, 0x82, 0xc7, 0x98, 0x67, 0xee, 0x3f}};
    vp_mac::Guid view{};
    std::memcpy(&view, &a, sizeof(a));
    if (view.Data1 != a.Data1 || view.Data4[7] != a.Data4[7] || a != a) return 1;
    stdext::hash_map<int, int, ReverseLess> values;
    values[1] = 10; values[2] = 20; values[1] = 30;
    if (values.size() != 2 || values.at(1) != 30 || values.at(2) != 20 || values.find(3) != values.end()) return 1;
    stdext::hash_map<std::string, int> strings;
    strings["native"] = 42;
    if (strings.at("native") != 42) return 1;
    std::puts("Native platform widths, SDK isolation and hash-traits semantics passed.");
}
