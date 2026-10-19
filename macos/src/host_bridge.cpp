#include "CvGameCoreDLLPCH.h"
#include "vp_mac/host_function_profile.hpp"
#include "vp_mac/bridge_checks.hpp"
#include "vp_mac/save_format.hpp"
#include "CvDllPreGame.h"
#include "CvPreGame.h"
#include <FireWorks/FMemoryStream.h>
#include <FireWorks/FCriticalSection.h>
#include <FireWorks/FStlContainerSerialization.h>

void vp_mac::write_save_boundary(FDataStream& stream) {
    const auto& header = sdk::kNativeSaveHeader;
    PRECONDITION(stream.WriteIt(header.size(), header.data()) == header.size(),
                 "Could not write the native Mac save header");
    native_log("native_save_header_written");
}

void vp_mac::read_save_boundary(FDataStream& stream) {
    std::array<unsigned char, sdk::kNativeSaveHeader.size()> bytes{};
    const auto count = stream.ReadIt(bytes.size(), bytes.data());
    PRECONDITION(save_header_matches(bytes.data(), count),
                 "This save does not match the native Mac save format; stock and Windows CP saves cannot be loaded");
    native_log("native_save_header_read");
}

bool vp_mac::check_lock_bridge() {
    static_assert(sizeof(FCriticalSection) == 40, "Reviewed native critical-section size");
    static_assert(alignof(FCriticalSection) == 8, "Reviewed native critical-section alignment");
    alignas(FCriticalSection) unsigned char storage[sizeof(FCriticalSection) + 16];
    std::memset(storage, 0xA5, sizeof(storage));
    auto* lock = ::new (storage + 8) FCriticalSection;
    // The host lock is recursive. Exercise the exported operations and their
    // complete lifetime before constructing CP objects that embed this type.
    lock->Enter();
    lock->Enter();
    lock->Leave();
    lock->Leave();
    lock->~FCriticalSection();
    for (unsigned i = 0; i < 8; ++i)
        if (storage[i] != 0xA5 || storage[sizeof(storage) - 8 + i] != 0xA5) return false;
    return true;
}

// Aspyr inserted a by-value Eras.Type getter after ICvPreGame1::era().
// Reuse CP's current era/info objects; keep the extra ABI slot out of upstream.
CvString CvDllPreGame::vpMacEraType() {
    const CvEraInfo* info = GC.getEraInfo(CvPreGame::era());
    PRECONDITION(info, "Mac pregame era-type getter requires a valid current era");
    return CvString(info->GetType());
}

// Aspyr ships these public SDK routines without exporting their names. Use
// reviewed entry points in its existing Lua/SQLite runtime; do not create a
// second VM, reinterpret private container layouts, or patch engine code.
extern "C" {
void lua_replace(lua_State* state, int index) {
    static const auto call = vp_mac::host_function<decltype(&lua_replace)>(vp_mac::sdk::k_lua_replace);
    call(state, index);
}
lua_Number lua_tonumber(lua_State* state, int index) {
    static const auto call = vp_mac::host_function<decltype(&lua_tonumber)>(vp_mac::sdk::k_lua_tonumber);
    return call(state, index);
}
size_t lua_objlen(lua_State* state, int index) {
    static const auto call = vp_mac::host_function<decltype(&lua_objlen)>(vp_mac::sdk::k_lua_objlen);
    return call(state, index);
}
void lua_gettable(lua_State* state, int index) {
    static const auto call = vp_mac::host_function<decltype(&lua_gettable)>(vp_mac::sdk::k_lua_gettable);
    call(state, index);
}
void lua_settable(lua_State* state, int index) {
    static const auto call = vp_mac::host_function<decltype(&lua_settable)>(vp_mac::sdk::k_lua_settable);
    call(state, index);
}
int lua_pcall(lua_State* state, int arguments, int results, int error_function) {
    static const auto call = vp_mac::host_function<decltype(&lua_pcall)>(vp_mac::sdk::k_lua_pcall);
    return call(state, arguments, results, error_function);
}
int luaL_loadstring(lua_State* state, const char* source) {
    static const auto call = vp_mac::host_function<decltype(&luaL_loadstring)>(vp_mac::sdk::k_lua_loadstring);
    return call(state, source);
}
}

void Database::Connection::Close() {
    static const auto call = vp_mac::host_function<void(*)(Connection*)>(vp_mac::sdk::k_db_close);
    call(this);
}
void Database::Connection::CommitTransaction() {
    static const auto call = vp_mac::host_function<void(*)(Connection*)>(vp_mac::sdk::k_db_commit);
    call(this);
}
void Database::Connection::Analyze() const {
    static const auto call = vp_mac::host_function<void(*)(const Connection*)>(vp_mac::sdk::k_db_analyze);
    call(this);
}
bool Database::Results::Bind(int index, double value) {
    static const auto call = vp_mac::host_function<bool(*)(Results*, int, double)>(vp_mac::sdk::k_db_bind_double);
    return call(this, index, value);
}
bool Database::Results::Bind(int index, float value) {
    static const auto call = vp_mac::host_function<bool(*)(Results*, int, float)>(vp_mac::sdk::k_db_bind_float);
    return call(this, index, value);
}

// Aspyr's unsigned-long writer intentionally emits four bytes, and its
// exported uint64 reader omits the byte swap. Keep eight-byte scalar encoding
// explicit, using the same desired-endian convention as its int32 writer.
void FDataStream::Write(const UINT64& value) {
    unsigned char bytes[8];
    const bool little = GetDesiredEndianNess() == FEndian::ENDIAN_LITTLE;
    for (unsigned i = 0; i < 8; ++i) bytes[i] = static_cast<unsigned char>(value >> ((little ? i : 7 - i) * 8));
    WriteIt(sizeof(bytes), bytes);
}
void FDataStream::Read(UINT64& value) {
    unsigned char bytes[8]{};
    ReadIt(sizeof(bytes), bytes);
    value = 0;
    const bool little = GetDesiredEndianNess() == FEndian::ENDIAN_LITTLE;
    for (unsigned i = 0; i < 8; ++i) value |= static_cast<UINT64>(bytes[i]) << ((little ? i : 7 - i) * 8);
}
void FDataStream::Write(const INT64& value) { Write(static_cast<UINT64>(value)); }
void FDataStream::Read(INT64& value) { UINT64 bits; Read(bits); std::memcpy(&value, &bits, sizeof(value)); }
void FDataStream::Write(const GUID& value) {
    *this << value.Data1 << value.Data2 << value.Data3;
    WriteIt(sizeof(value.Data4), value.Data4);
}
void FDataStream::Read(GUID& value) {
    *this >> value.Data1 >> value.Data2 >> value.Data3;
    ReadIt(sizeof(value.Data4), value.Data4);
}
std::string FSerialization::toString(const unsigned char& value) {
    const unsigned int number = value;
    return toString(number);
}

bool vp_mac::check_database_bridge() {
    Database::Connection database;
    if (!database.Open(":memory:", Database::OPEN_READWRITE | Database::OPEN_CREATE) || !database.Execute("BEGIN")) return false;
    {
        Database::Results result;
        // 2^24 + 1 is exact in double and cannot survive a float conversion.
        if (!database.Execute(result, "SELECT ? = 16777217 AS d, ? = 2.5 AS f") ||
            !result.Bind(1, 16777217.0) || !result.Bind(2, 2.5f) || !result.Step() ||
            result.GetInt(0) != 1 || result.GetInt(1) != 1) return false;
    }
    database.CommitTransaction();
    // BEGIN must succeed again: RELEASE of the SDK's named savepoint would
    // not be equivalent to COMMIT of this explicit transaction.
    if (!database.Execute("BEGIN") || !database.Execute("ROLLBACK")) return false;
    database.Analyze();
    database.Close();
    if (!database.Open(":memory:", Database::OPEN_READWRITE | Database::OPEN_CREATE)) return false;
    database.Close();
    return true;
}

bool vp_mac::check_stream_bridge() {
    static_assert(sizeof(FMemoryStream) == 72, "Reviewed native memory-stream layout");
    const unsigned char little_bytes[32] = {
        0x10,0x32,0x54,0x76,0x98,0xba,0xdc,0xfe, 0,0,0,0,0,0,0,0x80,
        0x78,0x56,0x34,0x12,0xbc,0x9a,0xf0,0xde, 1,2,3,4,5,6,7,8};
    const unsigned char big_bytes[32] = {
        0xfe,0xdc,0xba,0x98,0x76,0x54,0x32,0x10, 0x80,0,0,0,0,0,0,0,
        0x12,0x34,0x56,0x78,0x9a,0xbc,0xde,0xf0, 1,2,3,4,5,6,7,8};
    for (auto endian : {FEndian::ENDIAN_LITTLE, FEndian::ENDIAN_BIG}) {
        alignas(FMemoryStream) unsigned char storage[sizeof(FMemoryStream) + 16];
        std::memset(storage, 0xA5, sizeof(storage));
        auto* stream = ::new (storage + 8) FMemoryStream;
        stream->SetDesiredEndianNess(endian);
        const UINT64 unsigned_value = 0xfedcba9876543210ULL;
        const INT64 signed_value = std::numeric_limits<INT64>::min();
        const GUID guid = {0x12345678,0x9abc,0xdef0,{1,2,3,4,5,6,7,8}};
        *stream << unsigned_value << signed_value << guid;
        const auto* expected = endian == FEndian::ENDIAN_LITTLE ? little_bytes : big_bytes;
        unsigned char actual[32]{};
        bool passed = stream->GetEOF() == sizeof(actual);
        if (passed) {
            stream->Rewind();
            stream->CopyToMem(actual);
            passed = std::memcmp(actual, expected, sizeof(actual)) == 0;
        }
        if (passed) {
            stream->Rewind();
            UINT64 read_unsigned = 0; INT64 read_signed = 0; GUID read_guid{};
            *stream >> read_unsigned >> read_signed >> read_guid;
            passed = read_unsigned == unsigned_value && read_signed == signed_value && read_guid == guid;
        }
        if (passed) {
            stream->Rewind();
            stream->Truncate();
            const auto& header = sdk::kNativeSaveHeader;
            const unsigned long counter = 0xfedcba98UL;
            const std::vector<UINT64> seeds{unsigned_value, std::numeric_limits<UINT64>::max()};
            const std::string name = "Mac \xc3\xa9";
            passed = stream->WriteIt(header.size(), header.data()) == header.size();
            *stream << counter << seeds << name;
            // Native unsigned long/size_t writes are four bytes even on LP64.
            passed = passed && stream->GetEOF() == header.size() + 4 + 4 + 16 + 4 + name.size();
            if (passed) {
                stream->Rewind();
                std::array<unsigned char, sdk::kNativeSaveHeader.size()> read_header{};
                const auto count = stream->ReadIt(read_header.size(), read_header.data());
                passed = save_header_matches(read_header.data(), count);
            }
            if (passed) {
                unsigned long read_counter = ~0UL; // Native reader must clear its upper half.
                std::vector<UINT64> read_seeds{0};
                std::string read_name = "old";
                *stream >> read_counter >> read_seeds >> read_name;
                passed = read_counter == counter && read_seeds == seeds && read_name == name && stream->AtEnd();
            }
        }
        stream->~FMemoryStream();
        for (unsigned i = 0; i < 8; ++i)
            passed = passed && storage[i] == 0xA5 && storage[sizeof(storage) - 8 + i] == 0xA5;
        if (!passed) return false;
    }
    return true;
}

namespace {
struct LuaCheckResult { bool passed = false; bool new_index = false; };
int check_index(lua_State* state) { lua_pushinteger(state, 77); return 1; }
int check_new_index(lua_State* state) {
    auto* result = static_cast<LuaCheckResult*>(lua_touserdata(state, lua_upvalueindex(1)));
    result->new_index = lua_tonumber(state, 3) == 4.5;
    return 0;
}
int check_lua(lua_State* state) {
    auto* result = static_cast<LuaCheckResult*>(lua_touserdata(state, 1));
    lua_newtable(state);
    lua_pushstring(state, "value"); lua_pushnumber(state, 1.25); lua_settable(state, -3);
    lua_pushstring(state, "value"); lua_gettable(state, -2);
    if (lua_tonumber(state, -1) != 1.25) return 0;
    lua_pop(state, 1);
    lua_pushinteger(state, 10); lua_rawseti(state, -2, 1);
    lua_pushinteger(state, 20); lua_rawseti(state, -2, 2);
    if (lua_objlen(state, -1) != 2) return 0;
    lua_pushstring(state, "abc");
    if (lua_objlen(state, -1) != 3) return 0;
    lua_pop(state, 1);
    lua_pushinteger(state, 7); lua_pushinteger(state, 9); lua_replace(state, -2);
    if (lua_tonumber(state, -1) != 9) return 0;
    lua_pop(state, 1);
    lua_newtable(state);
    lua_pushcfunction(state, check_index); lua_setfield(state, -2, "__index");
    lua_pushlightuserdata(state, result); lua_pushcclosure(state, check_new_index, 1);
    lua_setfield(state, -2, "__newindex"); lua_setmetatable(state, -2);
    lua_pushstring(state, "missing"); lua_gettable(state, -2);
    if (lua_tonumber(state, -1) != 77) return 0;
    lua_pop(state, 1);
    lua_pushstring(state, "missing"); lua_pushnumber(state, 4.5); lua_settable(state, -3);
    if (!result->new_index) return 0;
    if (luaL_loadstring(state, "return function(x) return x + 0.5 end") || lua_pcall(state, 0, 1, 0)) return 0;
    lua_pushnumber(state, 2.0);
    if (lua_pcall(state, 1, 1, 0) || lua_tonumber(state, -1) != 2.5) return 0;
    lua_pop(state, 1);
    if (luaL_loadstring(state, "return nil + 1") || lua_pcall(state, 0, 1, 0) != LUA_ERRRUN) return 0;
    lua_pop(state, 1);
    if (luaL_loadstring(state, "function(") != LUA_ERRSYNTAX) return 0;
    lua_pop(state, 1);
    result->passed = true;
    return 0;
}
}
void vp_mac::check_lua_bridge_once(lua_State* state) {
    static bool checked = false;
    if (checked) return;
    const int top = lua_gettop(state);
    LuaCheckResult result;
    const int status = lua_cpcall(state, check_lua, &result);
    lua_settop(state, top);
    if (status || !result.passed) {
        native_log("native_lua_failed");
        std::abort();
    }
    checked = true;
    native_log("native_lua_passed");
}
