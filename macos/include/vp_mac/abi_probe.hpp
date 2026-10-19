#pragma once
#include "vp_mac/sdk_contract.hpp"
#include <cstdint>
#include <string>

namespace vp_mac {
using ProbeLog = void (*)(const char* event, const char* detail);

// Exact x86_64 native signatures. No Windows SDK libraries are linked.
struct HostFunctions {
    std::int32_t (*create_guid)(Guid*);
    int (*counter)(std::int64_t*);
    int (*frequency)(std::int64_t*);
    void (*write_int)(sdk::StreamView*, const int&);
    void (*read_int)(sdk::StreamView*, int&);
    void (*write_string)(sdk::StreamView*, const std::string&);
    void (*read_string)(sdk::StreamView*, std::string&);
};

// Also exercised by synthetic native fixtures; does not own the context.
bool check_host_abi(sdk::ContextPrefix* context, const HostFunctions& host, ProbeLog log);

// Runs only when both loaded Mach-O UUIDs match the reviewed Aspyr profile.
void probe_runtime_abi(void* context, const void* original_entry, ProbeLog log);
} // namespace vp_mac
