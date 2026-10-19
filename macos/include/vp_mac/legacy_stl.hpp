#pragma once
#include <array>
#include <unordered_map>
#include <unordered_set>

// Legacy names used by CP-owned containers. Native SDK private containers are
// opaque, so these aliases are never used to reconstruct an Aspyr object.
// This extension is confined to the reviewed libc++ native build profile.
#ifndef _LIBCPP_VERSION
#error The native Mac profile requires libc++
#endif
namespace std { namespace tr1 {
using std::array;
using std::hash;
using std::unordered_map;
using std::unordered_set;
} }
