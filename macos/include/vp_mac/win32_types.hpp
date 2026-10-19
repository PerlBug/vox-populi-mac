#pragma once
#include "vp_mac/native_types.hpp"

// The native core still uses Windows API spelling in public SDK declarations.
// LLP64 scalar widths must remain explicit when compiling with macOS LP64.
using BYTE = std::uint8_t;
using WORD = std::uint16_t;
using USHORT = std::uint16_t;
using UINT8 = std::uint8_t;
using UINT16 = std::uint16_t;
using UINT32 = std::uint32_t;
using UINT64 = std::uint64_t;
using INT8 = std::int8_t;
using INT16 = std::int16_t;
using INT32 = std::int32_t;
using INT64 = std::int64_t;
using UINT = unsigned int;
using INT = int;
using CHAR = char;
using WCHAR = wchar_t;
using DWORD = std::uint32_t;
using LONG = std::int32_t;
using ULONG = std::uint32_t;
using BOOL = int;
using HRESULT = std::int32_t;
using SIZE_T = std::size_t;
using HANDLE = void*;
using HMODULE = void*;
using HWND = void*;
using LPVOID = void*;
using LPSTR = char*;
using LPCSTR = const char*;
using LPWSTR = wchar_t*;
using LPCWSTR = const wchar_t*;

// Keep GUID's global SDK name as well as its verified 16-byte representation.
// A namespace type alias would change any C++ method's mangled parameter name.
struct GUID {
    std::uint32_t Data1;
    std::uint16_t Data2, Data3;
    std::uint8_t Data4[8];
};
inline bool operator==(const GUID& a, const GUID& b) { return std::memcmp(&a, &b, sizeof(GUID)) == 0; }
inline bool operator!=(const GUID& a, const GUID& b) { return !(a == b); }
union LARGE_INTEGER { std::int64_t QuadPart; };
struct POINT { LONG x, y; };

static_assert(sizeof(DWORD) == 4 && sizeof(LONG) == 4 && sizeof(ULONG) == 4, "Windows scalar widths");
static_assert(sizeof(GUID) == 16 && alignof(GUID) == 4 && offsetof(GUID, Data4) == 8, "Native GUID layout");
static_assert(sizeof(LARGE_INTEGER) == 8 && alignof(LARGE_INTEGER) == 8, "Native counter layout");
static_assert(sizeof(POINT) == 8, "Windows integer point layout");

#define WINAPI
#define APIENTRY
#define _CRTIMP
#define DECLSPEC_DEPRECATED __attribute__((deprecated))
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define S_OK 0
#define UNREFERENCED_PARAMETER(value) static_cast<void>(value)
#define INVALID_HANDLE_VALUE reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-1))

// These two host entry points have passed the native runtime ABI probe.
extern "C" int QueryPerformanceCounter(LARGE_INTEGER*);
extern "C" int QueryPerformanceFrequency(LARGE_INTEGER*);
enum HEAP_INFORMATION_CLASS { HeapCompatibilityInformation = 0 };
extern "C" HANDLE HeapCreate(DWORD options, SIZE_T initial_size, SIZE_T maximum_size);
extern "C" BOOL HeapDestroy(HANDLE heap);
extern "C" LPVOID HeapAlloc(HANDLE heap, DWORD flags, SIZE_T bytes);
extern "C" BOOL HeapFree(HANDLE heap, DWORD flags, LPVOID memory);
extern "C" BOOL HeapSetInformation(HANDLE heap, HEAP_INFORMATION_CLASS information, LPVOID value, SIZE_T bytes);
extern "C" BOOL DeleteFileW(LPCWSTR path);
extern "C" DWORD GetLastError();
extern "C" BOOL CloseHandle(HANDLE handle);
// Aspyr exports the file APIs used by save-game database serialization.
// The reviewed native attribute writer uses packed DWORD pairs for FILETIME.
struct FILETIME { DWORD dwLowDateTime, dwHighDateTime; };
struct WIN32_FILE_ATTRIBUTE_DATA {
    DWORD dwFileAttributes;
    FILETIME ftCreationTime, ftLastAccessTime, ftLastWriteTime;
    DWORD nFileSizeHigh, nFileSizeLow;
};
static_assert(sizeof(FILETIME) == 8 && alignof(FILETIME) == 4, "Native file timestamp layout");
static_assert(sizeof(WIN32_FILE_ATTRIBUTE_DATA) == 36 &&
              offsetof(WIN32_FILE_ATTRIBUTE_DATA, nFileSizeHigh) == 28, "Native file attribute layout");
enum GET_FILEEX_INFO_LEVELS { GetFileExInfoStandard = 0 };
extern "C" int MultiByteToWideChar(UINT code_page, DWORD flags, LPCSTR text, int length, LPWSTR wide, int capacity);
extern "C" HANDLE CreateFileW(LPCWSTR path, DWORD access, DWORD sharing, LPVOID security, DWORD disposition, DWORD flags, HANDLE template_file);
extern "C" DWORD GetFileSize(HANDLE file, DWORD* high);
extern "C" BOOL ReadFile(HANDLE file, LPVOID buffer, DWORD bytes, DWORD* read, LPVOID overlapped);
extern "C" BOOL GetFileAttributesExW(LPCWSTR path, GET_FILEEX_INFO_LEVELS level, LPVOID attributes);
constexpr UINT CP_UTF8 = 65001;
constexpr DWORD GENERIC_READ = 0x80000000u;
constexpr DWORD FILE_SHARE_READ = 1;
constexpr DWORD FILE_SHARE_WRITE = 2;
constexpr DWORD OPEN_EXISTING = 3;
constexpr DWORD FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000u;
constexpr DWORD INVALID_FILE_SIZE = 0xFFFFFFFFu;
constexpr DWORD INVALID_FILE_ATTRIBUTES = 0xFFFFFFFFu;
constexpr DWORD ERROR_FILE_NOT_FOUND = 2;
constexpr DWORD ERROR_PATH_NOT_FOUND = 3;
constexpr DWORD ERROR_ACCESS_DENIED = 5;
constexpr DWORD ERROR_SHARING_VIOLATION = 32;
constexpr DWORD ERROR_LOCK_VIOLATION = 33;
extern "C" void OutputDebugStringA(const char*);
#define OutputDebugString OutputDebugStringA
inline void ZeroMemory(void* memory, std::size_t bytes) { std::memset(memory, 0, bytes); }
