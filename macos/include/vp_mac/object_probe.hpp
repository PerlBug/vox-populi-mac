#pragma once
#include "vp_mac/abi_probe.hpp"
#include "vp_mac/engine_objects.hpp"

namespace vp_mac {
// Native non-static C++ methods use the explicit object pointer as their first
// argument on this x86_64 ABI. Keep resolution lazy so unknown hosts can skip.
struct ObjectFunctions {
    void (*db_construct)(Database::Connection*);
    void (*db_destroy)(Database::Connection*);
    bool (*db_open)(Database::Connection*, const char*, int);
    bool (*db_execute)(const Database::Connection*, Database::Results&, const char*, int);
    void (*results_construct)(Database::Results*, const char*);
    void (*results_destroy)(Database::Results*);
    bool (*results_bind_int)(Database::Results*, int, int);
    bool (*results_bind_text)(Database::Results*, int, const char*, bool);
    bool (*results_step)(Database::Results*);
    bool (*results_reset)(Database::Results*);
    bool (*results_has_column)(Database::Results*, const char*);
    int (*results_get_int)(Database::Results*, const char*);
    const char* (*results_get_text)(Database::Results*, const char*);
    void (*text_construct)(Localization::String*, const char*);
    void (*text_destroy)(Localization::String*);
    const char* (*text_utf8)(Localization::String*);
};

// Uses only newly constructed objects, an in-memory database, and a literal.
// Every successfully constructed object is destroyed by its native owner.
bool check_object_abi(const ObjectFunctions& host, ProbeLog log);
} // namespace vp_mac
