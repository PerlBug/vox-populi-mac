#pragma once
#include "vp_mac/win32_types.hpp"

// Native GUID creation passed the real-game ABI probe, including a canary.
extern "C" HRESULT CoCreateGuid(GUID* guid);
