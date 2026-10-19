#include "vp_mac/abi_probe.hpp"
#include <algorithm>
#include <array>
#include <cstdio>
#include <lua.h>

namespace vp_mac {
static_assert(sizeof(lua_Integer) == 8 && sizeof(lua_Number) == 8);
static_assert(std::is_same_v<lua_Integer, long>, "Review the native FLua integer specialization overlay");
static_assert(sizeof(std::string) == 24, "Review the host libc++ string ABI before proceeding");
#if _LIBCPP_ABI_VERSION != 1
#error This Aspyr profile requires libc++ ABI version 1.
#endif

namespace {
constexpr std::uint64_t kCanary = 0x414249434845434B;

class BufferStream final : public sdk::StreamView {
public:
    explicit BufferStream(sdk::FEndian::EEndianness endian) {
        m_bEnableCB = false;
        m_eEndianness = endian;
        m_uiBytesRead = m_uiPosition = 0;
    }
    unsigned ReadIt(unsigned count, void* output) override {
        if (m_uiPosition > used || count > used - m_uiPosition) { overflow = true; return 0; }
        std::memcpy(output, bytes.data() + m_uiPosition, count);
        m_uiPosition += count;
        m_uiBytesRead += count;
        return count;
    }
    unsigned WriteIt(unsigned count, const void* input) override {
        if (m_uiPosition > bytes.size() || count > bytes.size() - m_uiPosition) { overflow = true; return 0; }
        std::memcpy(bytes.data() + m_uiPosition, input, count);
        m_uiPosition += count;
        used = std::max(used, m_uiPosition);
        return count;
    }
    void Skip(unsigned count) override { SetPosition(m_uiPosition + count); }
    void Rewind() override { m_uiPosition = m_uiBytesRead = 0; }
    bool AtEnd() const override { return m_uiPosition >= used; }
    void FastFwd() override { m_uiPosition = used; }
    unsigned GetBytesUsed() const override { return used; }
    unsigned GetPosition() const override { return m_uiPosition; }
    void SetPosition(unsigned position) override {
        if (position > used) overflow = true;
        else m_uiPosition = position;
    }
    void Truncate() override { used = m_uiPosition; }
    void Flush() override {}
    unsigned GetEOF() const override { return used; }
    unsigned GetSizeLeft() const override { return m_uiPosition <= used ? used - m_uiPosition : 0; }
    void CopyToMem(void* output) override { std::memcpy(output, bytes.data(), used); }
    void RaiseException(std::exception&) const override { overflow = true; }
    unsigned endian_offset() const {
        return reinterpret_cast<const char*>(&m_eEndianness) - reinterpret_cast<const char*>(this);
    }
    std::array<unsigned char, 512> bytes{};
    unsigned used = 0;
    mutable bool overflow = false;
};

bool context_check(sdk::ContextPrefix* context) {
    const Guid unsupported{};
    const Guid supported[] = {sdk::guidICvUnknown, sdk::guidICvGameContext1,
                              sdk::guidICvGameContext2, sdk::guidICvGameContext3};
    for (const auto& id : supported)
        if (context->QueryInterface(id) != context) return false;
    if (context->QueryInterface(unsupported) != nullptr) return false;
    if (context->GetDLLGUID() != sdk::kStockDllGuid) return false;
    const char* version = context->GetDLLVersion();
    return version && std::strcmp(version, sdk::kStockDllVersion) == 0;
}

bool guid_check(const HostFunctions& host) {
    struct Guarded { std::uint64_t before = kCanary; Guid value{}; std::uint64_t after = kCanary; } a, b;
    if (host.create_guid(&a.value) != 0 || host.create_guid(&b.value) != 0) return false;
    return a.before == kCanary && a.after == kCanary && b.before == kCanary &&
           b.after == kCanary && a.value != Guid{} && b.value != Guid{} && a.value != b.value;
}

bool clock_check(const HostFunctions& host) {
    std::int64_t frequency = 0, before = 0, after = 0;
    return host.frequency(&frequency) && frequency > 0 && host.counter(&before) &&
           host.counter(&after) && after >= before;
}

bool stream_check(const HostFunctions& host, sdk::FEndian::EEndianness endian) {
    struct Guarded {
        std::uint64_t before = kCanary;
        BufferStream stream;
        std::uint64_t after = kCanary;
    } storage{kCanary, BufferStream(endian), kCanary};
    auto& stream = storage.stream;
    if (stream.endian_offset() != sdk::kStreamEndianOffset) return false;
    const int original = 0x12345678;
    const std::string text = "Vox Populi Mac ABI: a string long enough to cross the libc++ allocation boundary. \xc3\xa9";
    host.write_int(&stream, original);
    const std::array<unsigned char, 4> little{0x78, 0x56, 0x34, 0x12}, big{0x12, 0x34, 0x56, 0x78};
    const auto& expected = endian == sdk::FEndian::ENDIAN_LITTLE ? little : big;
    if (stream.used != 4 || !std::equal(expected.begin(), expected.end(), stream.bytes.begin())) return false;
    host.write_string(&stream, text);
    if (stream.overflow) return false;
    stream.Rewind();
    int value = 0;
    std::string restored;
    host.read_int(&stream, value);
    host.read_string(&stream, restored);
    return value == original && restored == text && !stream.overflow &&
           storage.before == kCanary && storage.after == kCanary;
}
} // namespace

bool check_host_abi(sdk::ContextPrefix* context, const HostFunctions& host, ProbeLog log) {
    if (!context || !host.create_guid || !host.counter || !host.frequency || !host.write_int ||
        !host.read_int || !host.write_string || !host.read_string) {
        log("abi_core_failed", "reason=missing_context_or_host_function");
        return false;
    }
    const bool context_ok = context_check(context);
    log("abi_context", context_ok ? "passed interfaces=4 guid_bytes=16 version=1.0.0" : "failed");
    const bool guid_ok = guid_check(host);
    log("abi_guid", guid_ok ? "passed bytes=16 guards=intact" : "failed");
    const bool clock_ok = clock_check(host);
    log("abi_clock", clock_ok ? "passed counter_bytes=8 monotonic=yes" : "failed");
    const bool stream_ok = stream_check(host, sdk::FEndian::ENDIAN_LITTLE) &&
                           stream_check(host, sdk::FEndian::ENDIAN_BIG);
    log("abi_stream", stream_ok ? "passed int32=both_endians libcxx_string=roundtrip" : "failed");
    return context_ok && guid_ok && clock_ok && stream_ok;
}
} // namespace vp_mac
