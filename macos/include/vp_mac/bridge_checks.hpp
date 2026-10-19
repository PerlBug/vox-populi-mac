#pragma once
struct lua_State;
namespace vp_mac {
void native_log(const char* event, const char* detail = nullptr);
bool check_database_bridge();
bool check_stream_bridge();
bool check_lock_bridge();
void check_lua_bridge_once(lua_State* state);
}
