#include "vp_mac/abi_probe.hpp"
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <utility>
#include <vector>

using namespace vp_mac;
namespace {
std::vector<std::pair<std::string, std::string>> events;
unsigned guid_counter = 0;
bool wrong_stream_endian = false;

void record(const char* event, const char* detail) { events.emplace_back(event, detail); }
void require(bool value, const char* message) {
    if (!value) { std::fprintf(stderr, "ABI fixture failed: %s\n", message); std::exit(1); }
}
bool recorded(const char* event, const char* detail) {
    return std::find(events.begin(), events.end(), std::make_pair(std::string(event), std::string(detail))) != events.end();
}

class Context final : public sdk::ContextPrefix {
public:
    bool reject_interface = false;
    bool wrong_guid = false;
    bool wrong_version = false;
    void* QueryInterface(Guid id) override {
        if (reject_interface) return nullptr;
        return id == sdk::guidICvUnknown || id == sdk::guidICvGameContext1 ||
               id == sdk::guidICvGameContext2 || id == sdk::guidICvGameContext3 ? this : nullptr;
    }
    void Destroy() override { require(false, "probe must not destroy the engine context"); }
    Guid GetDLLGUID() override { return wrong_guid ? Guid{} : sdk::kStockDllGuid; }
    const char* GetDLLVersion() override { return wrong_version ? "different" : sdk::kStockDllVersion; }
};

std::int32_t create_guid(Guid* output) {
    *output = sdk::kStockDllGuid;
    output->Data1 += ++guid_counter;
    return 0;
}
int frequency(std::int64_t* output) { *output = 1000000; return 1; }
int counter(std::int64_t* output) { static std::int64_t value = 10; *output = ++value; return 1; }
bool big_endian(sdk::StreamView* stream) {
    unsigned endian;
    std::memcpy(&endian, reinterpret_cast<char*>(stream) + sdk::kStreamEndianOffset, sizeof(endian));
    return (endian == sdk::FEndian::ENDIAN_BIG) != wrong_stream_endian;
}
void write_int(sdk::StreamView* stream, const int& value) {
    unsigned char bytes[4]; std::memcpy(bytes, &value, 4);
    if (big_endian(stream)) std::reverse(std::begin(bytes), std::end(bytes));
    stream->WriteIt(4, bytes);
}
void read_int(sdk::StreamView* stream, int& value) {
    unsigned char bytes[4]{}; stream->ReadIt(4, bytes);
    if (big_endian(stream)) std::reverse(std::begin(bytes), std::end(bytes));
    std::memcpy(&value, bytes, 4);
}
void write_string(sdk::StreamView* stream, const std::string& value) {
    const int size = static_cast<int>(value.size());
    write_int(stream, size);
    stream->WriteIt(size, value.data());
}
void read_string(sdk::StreamView* stream, std::string& value) {
    int size = 0; read_int(stream, size);
    require(size >= 0 && static_cast<unsigned>(size) <= stream->GetSizeLeft(), "fixture read is bounded by the stream interface");
    value.resize(size);
    stream->ReadIt(size, value.data());
}

HostFunctions host() { return {create_guid, counter, frequency, write_int, read_int, write_string, read_string}; }
void reset() { events.clear(); guid_counter = 0; wrong_stream_endian = false; }
} // namespace

int main() {
    Context context;
    reset();
    require(check_host_abi(&context, host(), record), "healthy host must pass all four checks");
    require(events.size() == 4, "four core check diagnostics");

    reset(); context.reject_interface = true;
    require(!check_host_abi(&context, host(), record), "rejected interface must fail");
    require(recorded("abi_context", "failed"), "context failure diagnostic");
    context.reject_interface = false;

    reset(); context.wrong_guid = true;
    require(!check_host_abi(&context, host(), record), "wrong returned GUID must fail");
    context.wrong_guid = false;
    reset(); context.wrong_version = true;
    require(!check_host_abi(&context, host(), record), "wrong version must fail");
    context.wrong_version = false;

    reset(); auto missing = host(); missing.read_string = nullptr;
    require(!check_host_abi(&context, missing, record), "missing function must not be called");
    require(events.size() == 1 && events[0].first == "abi_core_failed", "missing function fails before dispatch");

    reset(); auto broken = host();
    broken.frequency = [](std::int64_t* value) { *value = 0; return 1; };
    require(!check_host_abi(&context, broken, record), "zero clock frequency must fail");
    require(recorded("abi_clock", "failed"), "clock failure diagnostic");

    reset(); broken = host();
    broken.create_guid = [](Guid* value) { *value = Guid{}; return 0; };
    require(!check_host_abi(&context, broken, record), "empty GUID must fail");
    require(recorded("abi_guid", "failed"), "GUID failure diagnostic");

    reset(); wrong_stream_endian = true;
    require(!check_host_abi(&context, host(), record), "incorrect serialization bytes must fail");
    require(recorded("abi_stream", "failed"), "stream failure diagnostic");

    reset();
    // The production guard must skip before dereferencing a fake context.
    probe_runtime_abi(reinterpret_cast<void*>(1), reinterpret_cast<const void*>(&create_guid), record);
    require(events.size() == 1 && events[0].first == "abi_profile_skipped", "unreviewed images must not be probed");

    std::puts("9 native ABI scenarios passed (synthetic functions; real host validation remains separate).");
}
