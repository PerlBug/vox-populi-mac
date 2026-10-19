#include "vp_mac/object_probe.hpp"
#include <cstring>

namespace vp_mac {
namespace {
constexpr std::uint64_t kCanary = 0x764d61634f626a31ULL;
constexpr char kText[] = "Vox Populi Mac: private native object, UTF-8 \xc3\xa9.";

template<class T> struct Storage {
    std::uint64_t before = kCanary;
    alignas(T) unsigned char bytes[sizeof(T)]{};
    std::uint64_t after = kCanary;
    T* pointer() { return reinterpret_cast<T*>(bytes); }
    bool intact() const { return before == kCanary && after == kCanary; }
};

template<class T> class Lifetime {
public:
    Lifetime(T* object, void (*destroy)(T*)) : object_(object), destroy_(destroy) {}
    ~Lifetime() { destroy_(object_); }
    Lifetime(const Lifetime&) = delete;
    Lifetime& operator=(const Lifetime&) = delete;
private:
    T* object_;
    void (*destroy_)(T*);
};

bool database_check(const ObjectFunctions& host) {
    Storage<Database::Connection> connection;
    Storage<Database::Results> results;
    bool passed = false;
    {
        host.db_construct(connection.pointer());
        Lifetime<Database::Connection> own_connection(connection.pointer(), host.db_destroy);
        if (host.db_open(connection.pointer(), ":memory:", Database::OPEN_READWRITE | Database::OPEN_CREATE)) {
            host.results_construct(results.pointer(), nullptr);
            Lifetime<Database::Results> own_results(results.pointer(), host.results_destroy);
            auto* row = results.pointer();
            passed = host.db_execute(connection.pointer(), *row, "SELECT ? AS value, ? AS text", -1) &&
                host.results_bind_int(row, 1, 42) && host.results_bind_text(row, 2, kText, true) &&
                host.results_step(row) && host.results_has_column(row, "value") &&
                host.results_has_column(row, "text") && !host.results_has_column(row, "missing") &&
                host.results_get_int(row, "value") == 42;
            if (passed) {
                const char* text = host.results_get_text(row, "text");
                passed = text && std::strcmp(text, kText) == 0;
            }
            if (passed) {
                // Exercise statement reset, rebinding and cached column lookup.
                passed = host.results_reset(row) && host.results_bind_int(row, 1, 99) &&
                    host.results_bind_text(row, 2, kText, true) && host.results_step(row) &&
                    host.results_get_int(row, "value") == 99;
            }
        }
    } // Results must release its statement before the connection is destroyed.
    return passed && connection.intact() && results.intact();
}

bool localization_check(const ObjectFunctions& host) {
    Storage<Localization::String> storage;
    bool passed;
    {
        host.text_construct(storage.pointer(), kText);
        Lifetime<Localization::String> own_text(storage.pointer(), host.text_destroy);
        const char* text = host.text_utf8(storage.pointer());
        passed = text && std::strcmp(text, kText) == 0;
    }
    return passed && storage.intact();
}
} // namespace

bool check_object_abi(const ObjectFunctions& host, ProbeLog log) {
    if (!host.db_construct || !host.db_destroy || !host.db_open || !host.db_execute ||
        !host.results_construct || !host.results_destroy || !host.results_bind_int ||
        !host.results_bind_text || !host.results_step || !host.results_reset ||
        !host.results_has_column || !host.results_get_int || !host.results_get_text ||
        !host.text_construct || !host.text_destroy || !host.text_utf8) {
        log("abi_objects_failed", "reason=missing_host_function");
        return false;
    }
    const bool database_ok = database_check(host);
    log("abi_database", database_ok ? "passed connection=184 results=112 bind_reset=roundtrip guards=intact" : "failed");
    const bool text_ok = localization_check(host);
    log("abi_localization", text_ok ? "passed string=144 utf8=roundtrip guards=intact" : "failed");
    return database_ok && text_ok;
}
} // namespace vp_mac
