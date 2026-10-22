# Included by the loader today; reusable independently of the gameplay checkout.
find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
set(VP_UPSTREAM_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../Community-Patch-DLL" CACHE PATH
    "Untouched Community-Patch-DLL checkout")
get_filename_component(VP_UPSTREAM_DIR "${VP_UPSTREAM_DIR}" ABSOLUTE)
set(VP_MAC_PROFILE "${CMAKE_CURRENT_SOURCE_DIR}/abi/aspyr-steam-1.4.2.json" CACHE FILEPATH
    "Reviewed Aspyr native SDK ABI profile")
set(VP_MAC_GENERATOR "${CMAKE_CURRENT_SOURCE_DIR}/tools/sdk_contract.py")
set(VP_MAC_CONTRACT "${CMAKE_CURRENT_BINARY_DIR}/generated/vp_mac/sdk_contract.hpp")
set(VP_MAC_OVERLAY_RULES "${CMAKE_CURRENT_SOURCE_DIR}/overlays.json")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${VP_MAC_OVERLAY_RULES}" "${VP_MAC_PROFILE}")
file(READ "${VP_MAC_OVERLAY_RULES}" VP_MAC_OVERLAYS)
string(JSON VP_MAC_EDIT_COUNT LENGTH "${VP_MAC_OVERLAYS}" edits)
math(EXPR VP_MAC_EDIT_LAST "${VP_MAC_EDIT_COUNT} - 1")
set(VP_MAC_EDIT_OUTPUTS)
foreach(VP_MAC_INDEX RANGE 0 ${VP_MAC_EDIT_LAST})
  string(JSON VP_MAC_EDIT_OUTPUT GET "${VP_MAC_OVERLAYS}" edits ${VP_MAC_INDEX} output)
  string(JSON VP_MAC_EDIT_SOURCE GET "${VP_MAC_OVERLAYS}" edits ${VP_MAC_INDEX} source)
  list(APPEND VP_MAC_EDIT_OUTPUTS "${CMAKE_CURRENT_BINARY_DIR}/generated/${VP_MAC_EDIT_OUTPUT}")
  if(VP_MAC_EDIT_SOURCE MATCHES "\\.cpp$")
    set_property(SOURCE "${VP_UPSTREAM_DIR}/${VP_MAC_EDIT_SOURCE}" APPEND PROPERTY OBJECT_DEPENDS
      "${CMAKE_CURRENT_BINARY_DIR}/generated/${VP_MAC_EDIT_OUTPUT}")
  endif()
endforeach()
list(REMOVE_DUPLICATES VP_MAC_EDIT_OUTPUTS)

# Always re-check: a timestamp or a gameplay commit is not an ABI contract.
add_custom_target(vp_mac_sdk_contract
  COMMAND "${Python3_EXECUTABLE}" "${VP_MAC_GENERATOR}" prepare
    --upstream "${VP_UPSTREAM_DIR}" --profile "${VP_MAC_PROFILE}"
    --output "${CMAKE_CURRENT_BINARY_DIR}/generated"
  BYPRODUCTS "${VP_MAC_CONTRACT}" ${VP_MAC_EDIT_OUTPUTS}
    "${CMAKE_CURRENT_BINARY_DIR}/generated/vp_mac/engine_objects.hpp"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/vp_mac/engine_identity.hpp"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/vp_mac/host_function_profile.hpp"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/clang-overlay.json"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/vp_mac/overlay_revision.hpp"
    "${CMAKE_CURRENT_BINARY_DIR}/generated/vp_mac/commit_id.inc"
  VERBATIM)
add_library(vp_mac_generated INTERFACE)
add_dependencies(vp_mac_generated vp_mac_sdk_contract)
target_include_directories(vp_mac_generated INTERFACE
  "${CMAKE_CURRENT_SOURCE_DIR}/include" "${CMAKE_CURRENT_BINARY_DIR}/generated"
  "${VP_UPSTREAM_DIR}/ThirdPartyLibs/Lua51/include")
target_compile_options(vp_mac_generated INTERFACE
  -ivfsoverlay "${CMAKE_CURRENT_BINARY_DIR}/generated/clang-overlay.json"
  -include "${CMAKE_CURRENT_BINARY_DIR}/generated/vp_mac/overlay_revision.hpp")
add_library(vp_mac_sdk INTERFACE)
target_link_libraries(vp_mac_sdk INTERFACE vp_mac_generated)
target_compile_features(vp_mac_sdk INTERFACE cxx_std_17)

add_library(vp_mac_platform INTERFACE)
target_link_libraries(vp_mac_platform INTERFACE vp_mac_generated)
target_compile_features(vp_mac_platform INTERFACE cxx_std_14)
target_include_directories(vp_mac_platform INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/platform/include")
target_compile_definitions(vp_mac_platform INTERFACE VP_MAC_NATIVE=1
  _LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION
  _LIBCPP_ENABLE_CXX17_REMOVED_AUTO_PTR
  _LIBCPP_ENABLE_CXX17_REMOVED_RANDOM_SHUFFLE)
target_compile_options(vp_mac_platform INTERFACE
  -fms-extensions -fdeclspec -Wno-ignored-attributes -Wno-deprecated-declarations)

add_library(vp_mac_abi_probe STATIC src/probe_checks.cpp src/object_checks.cpp src/runtime_probe.cpp)
target_link_libraries(vp_mac_abi_probe PUBLIC vp_mac_sdk)
target_compile_options(vp_mac_abi_probe PRIVATE -Wall -Wextra -Werror -fno-exceptions -fno-rtti)
set_target_properties(vp_mac_abi_probe PROPERTIES CXX_VISIBILITY_PRESET hidden)

add_custom_target(vp_mac_upstream_inventory
  COMMAND "${Python3_EXECUTABLE}" "${VP_MAC_GENERATOR}" inventory
    --upstream "${VP_UPSTREAM_DIR}" --profile "${VP_MAC_PROFILE}"
    --output "${CMAKE_CURRENT_BINARY_DIR}/upstream-inventory.json"
  VERBATIM)

# Explicit development target: compile the real upstream files without copying
# the gameplay tree. Platform dependencies are still being ported, so this is
# excluded from normal builds and does not install anything in the game.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${VP_UPSTREAM_DIR}/CvGameCoreDLL_Expansion2/VoxPopuli.vcxproj"
  "${VP_UPSTREAM_DIR}/build_vp_clang.py" "${VP_MAC_GENERATOR}")
execute_process(COMMAND "${Python3_EXECUTABLE}" "${VP_MAC_GENERATOR}" inventory
  --upstream "${VP_UPSTREAM_DIR}" --profile "${VP_MAC_PROFILE}"
  --output "${CMAKE_CURRENT_BINARY_DIR}/upstream-inventory.json"
  RESULT_VARIABLE VP_MAC_INVENTORY_RESULT ERROR_VARIABLE VP_MAC_INVENTORY_ERROR)
if(NOT VP_MAC_INVENTORY_RESULT EQUAL 0)
  message(FATAL_ERROR "Upstream discovery failed: ${VP_MAC_INVENTORY_ERROR}")
endif()
file(READ "${CMAKE_CURRENT_BINARY_DIR}/upstream-inventory.json" VP_MAC_INVENTORY)
string(JSON VP_MAC_SOURCE_COUNT GET "${VP_MAC_INVENTORY}" upstream_source_count)
math(EXPR VP_MAC_SOURCE_LAST "${VP_MAC_SOURCE_COUNT} - 1")
set(VP_MAC_CORE_SOURCES)
foreach(VP_MAC_INDEX RANGE 0 ${VP_MAC_SOURCE_LAST})
  string(JSON VP_MAC_SOURCE GET "${VP_MAC_INVENTORY}" upstream_sources ${VP_MAC_INDEX})
  if(VP_MAC_SOURCE STREQUAL "CvGameCoreDLL.cpp")
    list(APPEND VP_MAC_CORE_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/src/native_entry.cpp")
  else()
    list(APPEND VP_MAC_CORE_SOURCES "${VP_UPSTREAM_DIR}/CvGameCoreDLL_Expansion2/${VP_MAC_SOURCE}")
  endif()
endforeach()
add_library(vp_mac_core_objects OBJECT EXCLUDE_FROM_ALL ${VP_MAC_CORE_SOURCES} src/platform_support.cpp src/host_bridge.cpp)
set_target_properties(vp_mac_core_objects PROPERTIES CXX_STANDARD 14 CXX_STANDARD_REQUIRED YES CXX_EXTENSIONS NO)
target_precompile_headers(vp_mac_core_objects PRIVATE
  "${VP_UPSTREAM_DIR}/CvGameCoreDLL_Expansion2/CvGameCoreDLLPCH.h")
target_link_libraries(vp_mac_core_objects PRIVATE vp_mac_platform)
string(JSON VP_MAC_INCLUDE_COUNT LENGTH "${VP_MAC_INVENTORY}" upstream_include_directories)
math(EXPR VP_MAC_INCLUDE_LAST "${VP_MAC_INCLUDE_COUNT} - 1")
foreach(VP_MAC_INDEX RANGE 0 ${VP_MAC_INCLUDE_LAST})
  string(JSON VP_MAC_INCLUDE GET "${VP_MAC_INVENTORY}" upstream_include_directories ${VP_MAC_INDEX})
  target_include_directories(vp_mac_core_objects PRIVATE "${VP_UPSTREAM_DIR}/${VP_MAC_INCLUDE}")
endforeach()
include(CheckCXXCompilerFlag)
string(JSON VP_MAC_WARNING_COUNT LENGTH "${VP_MAC_INVENTORY}" upstream_clang_suppressed_warnings)
if(VP_MAC_WARNING_COUNT GREATER 0)
  math(EXPR VP_MAC_WARNING_LAST "${VP_MAC_WARNING_COUNT} - 1")
  foreach(VP_MAC_INDEX RANGE 0 ${VP_MAC_WARNING_LAST})
    string(JSON VP_MAC_WARNING GET "${VP_MAC_INVENTORY}" upstream_clang_suppressed_warnings ${VP_MAC_INDEX})
    string(MAKE_C_IDENTIFIER "VP_MAC_HAS_WARNING_${VP_MAC_WARNING}" VP_MAC_WARNING_CHECK)
    check_cxx_compiler_flag("-Wno-${VP_MAC_WARNING}" ${VP_MAC_WARNING_CHECK})
    if(${VP_MAC_WARNING_CHECK})
      target_compile_options(vp_mac_core_objects PRIVATE "-Wno-${VP_MAC_WARNING}")
    endif()
  endforeach()
endif()
target_compile_definitions(vp_mac_core_objects PRIVATE
  # EXTERNAL_PAUSING is the optional Win32 "TurnByTurn" debugger mutex hook.
  FXS_IS_DLL CVGAMECOREDLL_EXPORTS FINAL_RELEASE NDEBUG)
target_compile_options(vp_mac_core_objects PRIVATE -ferror-limit=12
  # Match clang-cl's template parsing order used by the upstream FLua headers.
  -fdelayed-template-parsing)

set(VP_MAC_HOST_EXECUTABLE "$ENV{HOME}/Library/Application Support/Steam/steamapps/common/Sid Meier's Civilization V/Civilization V.app/Contents/MacOS/Civilization V"
  CACHE FILEPATH "Native Civ V executable whose SDK exports satisfy the gameplay core")
if(EXISTS "${VP_MAC_HOST_EXECUTABLE}")
  add_custom_target(vp_mac_host_contract
    COMMAND "${Python3_EXECUTABLE}" "${VP_MAC_GENERATOR}" verify-host
      --profile "${VP_MAC_PROFILE}" --binary "${VP_MAC_HOST_EXECUTABLE}" VERBATIM)
  # dlopen accepts Mach-O bundles. -bundle_loader validates every SDK import
  # against the real engine at link time; do not use unchecked dynamic_lookup.
  add_library(vp_mac_core MODULE EXCLUDE_FROM_ALL $<TARGET_OBJECTS:vp_mac_core_objects>)
  add_dependencies(vp_mac_core vp_mac_host_contract)
  set_target_properties(vp_mac_core PROPERTIES
    OUTPUT_NAME CvGameCoreDLL_Expansion2_DLL PREFIX lib SUFFIX .dylib
    LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/../prototype/exports.txt;${VP_MAC_HOST_EXECUTABLE};${VP_MAC_PROFILE};${VP_MAC_GENERATOR}")
  target_link_options(vp_mac_core PRIVATE
    "LINKER:-bundle_loader,${VP_MAC_HOST_EXECUTABLE}"
    "LINKER:-exported_symbols_list,${CMAKE_CURRENT_SOURCE_DIR}/../prototype/exports.txt")
  add_custom_command(TARGET vp_mac_core POST_BUILD
    COMMAND "${Python3_EXECUTABLE}" "${VP_MAC_GENERATOR}" verify-core
      --profile "${VP_MAC_PROFILE}" --binary "$<TARGET_FILE:vp_mac_core>"
    COMMAND /usr/bin/codesign --force --sign - "$<TARGET_FILE:vp_mac_core>" VERBATIM)
endif()
file(GENERATE OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/core-object-files.txt"
  CONTENT "$<JOIN:$<TARGET_OBJECTS:vp_mac_core_objects>,\n>\n")

if(BUILD_TESTING)
  add_executable(abi_selftest tests/abi_selftest.cpp)
  target_link_libraries(abi_selftest PRIVATE vp_mac_abi_probe)
  target_compile_options(abi_selftest PRIVATE -Wall -Wextra -Werror)
  add_test(NAME native_abi_checks COMMAND abi_selftest)
  add_executable(object_selftest tests/object_selftest.cpp)
  target_link_libraries(object_selftest PRIVATE vp_mac_abi_probe)
  target_compile_options(object_selftest PRIVATE -Wall -Wextra -Werror)
  add_test(NAME native_object_checks COMMAND object_selftest)
  add_executable(platform_selftest tests/platform_selftest.cpp)
  target_link_libraries(platform_selftest PRIVATE vp_mac_platform)
  target_compile_features(platform_selftest PRIVATE cxx_std_17)
  target_include_directories(platform_selftest PRIVATE
    "${VP_UPSTREAM_DIR}/FirePlace/include" "${VP_UPSTREAM_DIR}/CvGameDatabase/include")
  target_compile_options(platform_selftest PRIVATE -Wall -Wextra -Werror)
  add_test(NAME native_platform_types COMMAND platform_selftest)
  add_executable(crt_selftest tests/crt_selftest.cpp)
  target_link_libraries(crt_selftest PRIVATE vp_mac_platform)
  target_compile_options(crt_selftest PRIVATE -Wall -Wextra -Werror)
  add_test(NAME native_crt_support COMMAND crt_selftest)
  add_test(NAME upstream_contract
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_contract.py"
      --upstream "${VP_UPSTREAM_DIR}" --compiler "${CMAKE_CXX_COMPILER}")
  add_test(NAME cp_startup_packaging
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_package.py")
  add_test(NAME beta_release_tools
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/../tools/tests/test_beta.py")
  find_program(VP_MAC_LUA_EXECUTABLE NAMES lua5.1 lua51)
  if(VP_MAC_LUA_EXECUTABLE)
    add_test(NAME wasd_camera_input
      COMMAND "${VP_MAC_LUA_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/camera_selftest.lua"
        "${CMAKE_CURRENT_SOURCE_DIR}/runtime/VPMacCamera.lua")
  endif()
endif()
