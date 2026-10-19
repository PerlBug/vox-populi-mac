cmake_minimum_required(VERSION 3.20)

# Set the target before project() performs compiler checks on Apple Silicon.
set(CMAKE_OSX_ARCHITECTURES "x86_64" CACHE STRING "Civ V's process architecture")
set(CMAKE_OSX_DEPLOYMENT_TARGET "10.15" CACHE STRING "Minimum macOS version")
project(VoxPopMacLoaderProbe VERSION 0.1.0 LANGUAGES CXX)

if(NOT APPLE OR NOT CMAKE_OSX_ARCHITECTURES STREQUAL "x86_64")
  message(FATAL_ERROR "This prototype requires macOS and CMAKE_OSX_ARCHITECTURES=x86_64")
endif()

add_library(loader_probe SHARED src/loader_probe.cpp)
target_compile_features(loader_probe PRIVATE cxx_std_17)
target_compile_options(loader_probe PRIVATE -Wall -Wextra -Werror -fno-exceptions -fno-rtti)
target_link_options(loader_probe PRIVATE
  "LINKER:-exported_symbols_list,${CMAKE_CURRENT_SOURCE_DIR}/exports.txt")
set_target_properties(loader_probe PROPERTIES
  OUTPUT_NAME CvGameCoreDLL_Expansion2_DLL
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_NAME_DIR YES
  INSTALL_NAME_DIR "@rpath"
  LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/exports.txt")
add_custom_command(TARGET loader_probe POST_BUILD
  COMMAND /usr/bin/codesign --force --sign - "$<TARGET_FILE:loader_probe>"
  VERBATIM)

include(CTest)
option(VP_MAC_ABI_PROBES "Enable reviewed native SDK ABI diagnostics" ON)
if(VP_MAC_ABI_PROBES)
  add_subdirectory("${CMAKE_CURRENT_SOURCE_DIR}/../macos" "macos")
  target_link_libraries(loader_probe PRIVATE vp_mac_abi_probe)
  target_compile_definitions(loader_probe PRIVATE VP_MAC_ABI_PROBES=1)
endif()
if(BUILD_TESTING)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_library(stock_fixture SHARED tests/stock_fixture.cpp)
  set_target_properties(stock_fixture PROPERTIES
    OUTPUT_NAME CvGameCoreDLL_Expansion2_DLL
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/fixtures"
    NO_SONAME YES)
  # Emulate the real stock core's imports from its host executable.
  target_link_options(stock_fixture PRIVATE
    "LINKER:-undefined,dynamic_lookup"
    "LINKER:-install_name,/libCvGameCoreDLL_Expansion2_DLL.dylib")
  add_library(no_entry_fixture SHARED tests/no_entry_fixture.cpp)
  add_executable(probe_host tests/probe_host.cpp)
  set_target_properties(probe_host PROPERTIES ENABLE_EXPORTS YES)
  target_compile_options(probe_host PRIVATE -Wall -Wextra -Werror)
  add_test(NAME loader_and_installer
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_probe.py"
      --wrapper "$<TARGET_FILE:loader_probe>"
      --host "$<TARGET_FILE:probe_host>"
      --stock "$<TARGET_FILE:stock_fixture>"
      --no-entry "$<TARGET_FILE:no_entry_fixture>")
endif()
