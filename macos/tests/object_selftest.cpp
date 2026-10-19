#include "vp_mac/object_probe.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

using namespace vp_mac;
static_assert(!std::is_copy_constructible_v<Database::Connection>);

namespace {
void require(bool value, const char* detail) {
    if (!value) { std::fprintf(stderr, "FAIL: %s\n", detail); std::exit(1); }
}
enum Failure { none, open, execute, bind_int, bind_text, step, reset, column,
               integer, text, localization, connection_guard, results_guard, text_guard };
struct Fixture {
    Failure failure = none;
    Database::Connection* connection = nullptr;
    Database::Results* results = nullptr;
    Localization::String* string = nullptr;
    bool prepared = false, int_bound = false, text_bound = false;
    int value = 0, result_destroys = 0, connection_destroys = 0, text_destroys = 0;
    std::string bound, literal;
    std::vector<std::pair<std::string, std::string>> events;
} fixture;
void record(const char* event, const char* detail) { fixture.events.emplace_back(event, detail); }
template<class T> void initialize(T* object) {
    // Exercise the entire reviewed extent without implementing native internals.
    std::memset(static_cast<void*>(object), 0xA5, sizeof(T));
}
template<class T> void overrun(T* object) {
    reinterpret_cast<unsigned char*>(object)[sizeof(T)] ^= 1;
}
void db_construct(Database::Connection* object) {
    require(!fixture.connection, "one private connection");
    fixture.connection = object; initialize(object);
    if (fixture.failure == connection_guard) overrun(object);
}
void db_destroy(Database::Connection* object) {
    require(object == fixture.connection && !fixture.results, "results destroyed before connection");
    fixture.connection = nullptr; ++fixture.connection_destroys;
}
bool db_open(Database::Connection* object, const char* path, int flags) {
    require(object == fixture.connection && std::strcmp(path, ":memory:") == 0 && flags == 6,
            "only private in-memory database is opened");
    return fixture.failure != open;
}
bool db_execute(const Database::Connection* object, Database::Results& results, const char* sql, int length) {
    require(object == fixture.connection && &results == fixture.results && length == -1 &&
            std::strcmp(sql, "SELECT ? AS value, ? AS text") == 0, "expected parameterized query");
    fixture.prepared = fixture.failure != execute;
    return fixture.prepared;
}
void results_construct(Database::Results* object, const char* columns) {
    require(fixture.connection && !fixture.results && !columns, "native results constructor arguments");
    fixture.results = object; initialize(object);
    if (fixture.failure == results_guard) overrun(object);
}
void results_destroy(Database::Results* object) {
    require(object == fixture.results && fixture.connection, "results owned by active connection");
    fixture.results = nullptr; ++fixture.result_destroys;
}
bool results_bind_int(Database::Results* object, int index, int value) {
    require(object == fixture.results && fixture.prepared && index == 1, "integer bind arguments");
    fixture.int_bound = true; fixture.value = value;
    return fixture.failure != bind_int;
}
bool results_bind_text(Database::Results* object, int index, const char* value, bool copy) {
    require(object == fixture.results && fixture.prepared && index == 2 && copy, "text bind copies UTF-8");
    fixture.text_bound = true; fixture.bound = value;
    return fixture.failure != bind_text;
}
bool results_step(Database::Results* object) {
    require(object == fixture.results && fixture.int_bound && fixture.text_bound, "both parameters bound before stepping");
    return fixture.failure != step;
}
bool results_reset(Database::Results* object) {
    require(object == fixture.results, "reset active statement");
    fixture.int_bound = fixture.text_bound = false;
    return fixture.failure != reset;
}
bool results_has_column(Database::Results* object, const char* name) {
    require(object == fixture.results, "column lookup uses native results");
    return fixture.failure != column && std::strcmp(name, "missing") != 0;
}
int results_get_int(Database::Results* object, const char* name) {
    require(object == fixture.results && std::strcmp(name, "value") == 0, "integer lookup by column name");
    return fixture.failure == integer ? -1 : fixture.value;
}
const char* results_get_text(Database::Results* object, const char* name) {
    require(object == fixture.results && std::strcmp(name, "text") == 0, "text lookup by column name");
    return fixture.failure == text ? nullptr : fixture.bound.c_str();
}
void text_construct(Localization::String* object, const char* value) {
    require(!fixture.string, "one private localization string");
    fixture.string = object; fixture.literal = value; initialize(object);
}
void text_destroy(Localization::String* object) {
    require(object == fixture.string, "destroy native localization string");
    if (fixture.failure == text_guard) overrun(object);
    fixture.string = nullptr; ++fixture.text_destroys;
}
const char* text_utf8(Localization::String* object) {
    require(object == fixture.string, "localization conversion uses native object");
    return fixture.failure == localization ? "wrong text" : fixture.literal.c_str();
}
ObjectFunctions host() {
    return {db_construct, db_destroy, db_open, db_execute, results_construct, results_destroy,
            results_bind_int, results_bind_text, results_step, results_reset, results_has_column,
            results_get_int, results_get_text, text_construct, text_destroy, text_utf8};
}
} // namespace

int main() {
    require(check_object_abi(host(), record), "healthy native objects pass");
    require(fixture.connection_destroys == 1 && fixture.result_destroys == 1 && fixture.text_destroys == 1,
            "all native objects destroyed exactly once");
    require(fixture.value == 99, "statement reset and rebinding reached second row");
    for (int failure = open; failure <= text_guard; ++failure) {
        fixture = Fixture{}; fixture.failure = static_cast<Failure>(failure);
        require(!check_object_abi(host(), record), "injected ABI/operation failure detected");
        require(!fixture.connection && !fixture.results && !fixture.string, "failure path cleans up native objects");
        require(fixture.connection_destroys == 1 && fixture.text_destroys == 1 &&
                fixture.result_destroys == (failure == open ? 0 : 1), "only constructed objects destroyed once");
        const bool database_failed = failure != localization && failure != text_guard;
        require(fixture.events.size() == 2 && fixture.events[0].first == "abi_database" &&
                fixture.events[0].second.rfind(database_failed ? "failed" : "passed", 0) == 0 &&
                fixture.events[1].second.rfind(database_failed ? "passed" : "failed", 0) == 0, "individual failure diagnostic");
    }
    fixture = Fixture{};
    auto missing = host(); missing.results_destroy = nullptr;
    require(!check_object_abi(missing, record), "missing destructor fails before constructing anything");
    require(!fixture.connection_destroys && !fixture.text_destroys && fixture.events.size() == 1,
            "incomplete imports cannot enter native object code");
    std::puts("15 native object scenarios passed (synthetic methods; real host validation remains separate).");
}
