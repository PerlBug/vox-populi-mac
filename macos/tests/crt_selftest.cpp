#include "vp_mac/crt.hpp"
#include "vp_mac/platform_services.hpp"
#include <array>
#include <cstring>
#include <cstdlib>
#include <limits>

namespace {
void require(bool result) { if (!result) std::exit(1); }
void converts(std::int64_t input, int radix, const char* expected) {
    char buffer[66]{};
    require(_i64toa_s(input, buffer, sizeof(buffer), radix) == 0 && std::strcmp(buffer, expected) == 0);
}
}
int main() {
    converts(0, 10, "0");
    converts(std::numeric_limits<std::int64_t>::min(), 10, "-9223372036854775808");
    converts(std::numeric_limits<std::int64_t>::max(), 10, "9223372036854775807");
    converts(-1, 16, "ffffffffffffffff");
    converts(35, 36, "z");
    converts(10, 2, "1010");
    std::array<unsigned char, 12> guarded;
    guarded.fill(0xA5);
    auto* buffer = reinterpret_cast<char*>(guarded.data() + 4);
    require(_i64toa_s(12345, buffer, 3, 10) == ERANGE && buffer[0] == '\0');
    for (unsigned i = 0; i < guarded.size(); ++i) if (i != 4) require(guarded[i] == 0xA5);
    require(_i64toa_s(1, buffer, 3, 1) == EINVAL && buffer[0] == '\0');
    require(_i64toa_s(1, nullptr, 3, 10) == EINVAL);
    guarded[4] = 0xA5;
    require(_i64toa_s(1, buffer, 0, 10) == EINVAL && guarded[4] == 0xA5);
    char path[4096];
    const DWORD length = GetModuleFileName(nullptr, path, sizeof(path));
    require(length > 0 && length == std::strlen(path));
    char shortened[4]{};
    require(GetModuleFileName(nullptr, shortened, sizeof(shortened)) == sizeof(shortened) && shortened[3] == '\0');
    require(GetModuleFileName(reinterpret_cast<HMODULE>(1), path, sizeof(path)) == 0);
    char text[] = "aBcD";
    require(_strlwr(text) == text && std::strcmp(text, "abcd") == 0);
    require(_strupr(text) == text && std::strcmp(text, "ABCD") == 0);
    require(_strrev(text) == text && std::strcmp(text, "DCBA") == 0);
    require(_strnset(text, 'x', 2) == text && std::strcmp(text, "xxBA") == 0);
    char short_text[] = {'a', '\0', 'Z'};
    _strnset(short_text, 'x', 20);
    require(short_text[0] == 'x' && short_text[1] == '\0' && short_text[2] == 'Z');
    wchar_t wide[] = L"A\U0001F600b";
    require(_wcsrev(wide) == wide && std::wcscmp(wide, L"b\U0001F600A") == 0);
    _wcsnset(wide, L'x', 1);
    require(std::wcscmp(wide, L"x\U0001F600A") == 0);
    wchar_t mixed[] = L"aBc";
    require(_wcsupr(mixed) == mixed && std::wcscmp(mixed, L"ABC") == 0);
    require(_wcslwr(mixed) == mixed && std::wcscmp(mixed, L"abc") == 0);
    require(_wcsicmp(L"ABC", L"abc") == 0 && _wcsnicmp(L"ABCx", L"abcy", 3) == 0);
    require(_stricoll("AbC", "aBc") == 0 && _wcsicoll(L"AbC", L"aBc") == 0);
    require(_stricoll("", "") == 0 && _wcsicoll(L"", L"") == 0);
    char empty[] = ""; wchar_t wide_empty[] = L"";
    require(_strrev(empty) == empty && _wcsrev(wide_empty) == wide_empty);
    for (std::size_t bytes : {std::size_t(1), std::size_t(8192)}) {
        void* allocation = _malloca(bytes);
        require(allocation != nullptr && reinterpret_cast<std::uintptr_t>(allocation) % 16 == 0);
        std::memset(allocation, 0xA5, bytes);
        _freea(allocation);
    }
    require(GetCurrentThreadId() != 0);
    std::puts("Native CRT conversions, string boundaries, wide characters and temporary allocation passed.");
}
