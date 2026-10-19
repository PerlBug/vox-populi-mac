#pragma once
#include <cstdarg>
#include <cstdio>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <cwchar>
#include <cctype>
#include <cwctype>
#include <cstdlib>
#include <string>

// Exported by Aspyr with these native C++ signatures. Reuse its checked CRT
// implementation.
int sprintf_s(char* buffer, std::size_t capacity, const char* format, ...);
int vsprintf_s(char* buffer, std::size_t capacity, const char* format, va_list arguments);
int strcpy_s(char* buffer, std::size_t capacity, const char* source);
int wcscpy_s(wchar_t* buffer, std::size_t capacity, const wchar_t* source);
int _itoa_s(int value, char* buffer, std::size_t capacity, int radix);
template<std::size_t N> int _itoa_s(int value, char (&buffer)[N], int radix) {
    return _itoa_s(value, buffer, N, radix);
}
template<std::size_t N> int vsprintf_s(char (&buffer)[N], const char* format, va_list arguments) {
    return vsprintf_s(buffer, N, format, arguments);
}
template<std::size_t N> int strcpy_s(char (&buffer)[N], const char* source) {
    return strcpy_s(buffer, N, source);
}
extern "C" int _stricmp(const char*, const char*);
extern "C" int _strnicmp(const char*, const char*, std::size_t);
extern "C" int _vsnprintf(char*, std::size_t, const char*, va_list);
extern "C" char* _strdup(const char*);

// CP's temporary buffers stay within the core. Use the heap for both small
// and large allocations; returning alloca storage from a helper is invalid.
inline void* _malloca(std::size_t bytes) { return std::malloc(bytes); }
inline void _freea(void* buffer) { std::free(buffer); }
inline int _wcsicmp(const wchar_t* a, const wchar_t* b) { return wcscasecmp(a, b); }
inline int _wcsnicmp(const wchar_t* a, const wchar_t* b, std::size_t count) { return wcsncasecmp(a, b, count); }
inline char* _strnset(char* value, int ch, std::size_t count) {
    for (std::size_t i = 0; i < count && value[i]; ++i) value[i] = static_cast<char>(ch);
    return value;
}
inline wchar_t* _wcsnset(wchar_t* value, wchar_t ch, std::size_t count) {
    for (std::size_t i = 0; i < count && value[i]; ++i) value[i] = ch;
    return value;
}
inline char* _strupr(char* value) {
    for (char* p = value; *p; ++p) *p = static_cast<char>(std::toupper(static_cast<unsigned char>(*p)));
    return value;
}
inline char* _strlwr(char* value) {
    for (char* p = value; *p; ++p) *p = static_cast<char>(std::tolower(static_cast<unsigned char>(*p)));
    return value;
}
inline wchar_t* _wcsupr(wchar_t* value) {
    for (wchar_t* p = value; *p; ++p) *p = static_cast<wchar_t>(std::towupper(*p));
    return value;
}
inline wchar_t* _wcslwr(wchar_t* value) {
    for (wchar_t* p = value; *p; ++p) *p = static_cast<wchar_t>(std::towlower(*p));
    return value;
}
inline char* _strrev(char* value) {
    const std::size_t length = std::strlen(value);
    for (std::size_t i = 0; i < length / 2; ++i) std::swap(value[i], value[length - i - 1]);
    return value;
}
inline wchar_t* _wcsrev(wchar_t* value) {
    const std::size_t length = std::wcslen(value);
    for (std::size_t i = 0; i < length / 2; ++i) std::swap(value[i], value[length - i - 1]);
    return value;
}
inline int _stricoll(const char* a, const char* b) {
    std::string first(a), second(b);
    _strlwr(&first[0]); _strlwr(&second[0]);
    return std::strcoll(first.c_str(), second.c_str());
}
inline int _wcsicoll(const wchar_t* a, const wchar_t* b) {
    std::wstring first(a), second(b);
    _wcslwr(&first[0]); _wcslwr(&second[0]);
    return std::wcscoll(first.c_str(), second.c_str());
}
template<std::size_t N> int sprintf_s(char (&buffer)[N], const char* format, ...) {
    va_list arguments;
    va_start(arguments, format);
    const int result = vsprintf_s(buffer, N, format, arguments);
    va_end(arguments);
    return result;
}

// Aspyr exports the 32-bit converter but not the signed 64-bit variant.
inline int _i64toa_s(std::int64_t value, char* buffer, std::size_t capacity, int radix) {
    if (!buffer || !capacity || radix < 2 || radix > 36) {
        if (buffer && capacity) buffer[0] = '\0';
        errno = EINVAL;
        return EINVAL;
    }
    const bool negative = value < 0 && radix == 10;
    std::uint64_t magnitude = static_cast<std::uint64_t>(value);
    if (negative) magnitude = 0 - magnitude; // Also handles INT64_MIN.
    char reversed[64];
    std::size_t count = 0;
    do {
        reversed[count++] = "0123456789abcdefghijklmnopqrstuvwxyz"[magnitude % radix];
        magnitude /= radix;
    } while (magnitude);
    if (count + negative + 1 > capacity) {
        buffer[0] = '\0';
        errno = ERANGE;
        return ERANGE;
    }
    std::size_t position = 0;
    if (negative) buffer[position++] = '-';
    while (count) buffer[position++] = reversed[--count];
    buffer[position] = '\0';
    return 0;
}
