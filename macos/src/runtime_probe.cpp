#include "vp_mac/abi_probe.hpp"
#include "vp_mac/object_probe.hpp"
#include "vp_mac/macho_identity.hpp"
#include <dlfcn.h>

namespace vp_mac {
void probe_runtime_abi(void* context, const void* original_entry, ProbeLog log) {
    Dl_info core{};
    if (!host_is_reviewed() || !dladdr(original_entry, &core) ||
        !image_uuid_matches(core.dli_fbase, sdk::k_stock_core_uuid)) {
        log("abi_profile_skipped", "reason=unreviewed_host_or_core_uuid forwarding=stock");
        return;
    }
    log("abi_profile_matched", sdk::kProfileName);
    log("abi_probe_started", "checks=6");
    HostFunctions host{};
#define VP_MAC_RESOLVE(member) \
    host.member = reinterpret_cast<decltype(host.member)>(dlsym(RTLD_DEFAULT, sdk::k_symbol_##member)); \
    if (!host.member) log("abi_symbol_missing", sdk::k_symbol_##member)
    VP_MAC_RESOLVE(create_guid);
    VP_MAC_RESOLVE(counter);
    VP_MAC_RESOLVE(frequency);
    VP_MAC_RESOLVE(write_int);
    VP_MAC_RESOLVE(read_int);
    VP_MAC_RESOLVE(write_string);
    VP_MAC_RESOLVE(read_string);
#undef VP_MAC_RESOLVE
    const bool core_ok = check_host_abi(static_cast<sdk::ContextPrefix*>(context), host, log);
    if (!core_ok) {
        log("abi_probe_failed", "reason=core_checks_failed object_checks=skipped");
        return;
    }
    ObjectFunctions objects{};
#define VP_MAC_RESOLVE(member) \
    objects.member = reinterpret_cast<decltype(objects.member)>(dlsym(RTLD_DEFAULT, sdk::k_symbol_##member)); \
    if (!objects.member) log("abi_symbol_missing", sdk::k_symbol_##member)
    VP_MAC_RESOLVE(db_construct);
    VP_MAC_RESOLVE(db_destroy);
    VP_MAC_RESOLVE(db_open);
    VP_MAC_RESOLVE(db_execute);
    VP_MAC_RESOLVE(results_construct);
    VP_MAC_RESOLVE(results_destroy);
    VP_MAC_RESOLVE(results_bind_int);
    VP_MAC_RESOLVE(results_bind_text);
    VP_MAC_RESOLVE(results_step);
    VP_MAC_RESOLVE(results_reset);
    VP_MAC_RESOLVE(results_has_column);
    VP_MAC_RESOLVE(results_get_int);
    VP_MAC_RESOLVE(results_get_text);
    VP_MAC_RESOLVE(text_construct);
    VP_MAC_RESOLVE(text_destroy);
    VP_MAC_RESOLVE(text_utf8);
#undef VP_MAC_RESOLVE
    const bool objects_ok = check_object_abi(objects, log);
    log(objects_ok ? "abi_probe_passed" : "abi_probe_failed", "checks=6");
}
} // namespace vp_mac
