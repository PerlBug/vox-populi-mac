#!/usr/bin/env python3
"""Generate native ABI views and checked overlays from an untouched SDK.

Reviewed boundary declarations and layouts are checked. Gameplay revisions,
comments and formatting do not invalidate the native engine ABI profile.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import struct
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "abi/aspyr-steam-1.4.2.json"
OVERLAYS = ROOT / "overlays.json"


class ContractError(RuntimeError):
    pass


def without_comments(text):
    pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/'
    return re.sub(pattern, lambda m: " " if m[0].startswith(("//", "/*")) else m[0],
                  text, flags=re.S)


def tokens(text):
    return re.findall(r"[A-Za-z_]\w*|0[xX][\da-fA-F]+|\d+|::|\S", without_comments(text))


def class_body(text, name):
    text = without_comments(text)
    matches = list(re.finditer(r"\bclass\s+" + re.escape(name) + r"\b(?:\s*:[^{;]+)?\s*\{", text))
    if len(matches) != 1:
        raise ContractError(f"Expected one declaration of {name}; found {len(matches)}")
    start = matches[0].end()
    depth = 1
    for end in range(start, len(text)):
        depth += (text[end] == "{") - (text[end] == "}")
        if depth == 0:
            return text[start:end]
    raise ContractError(f"Unclosed class declaration: {name}")


def virtuals(text, name):
    return re.findall(r"\bvirtual\b[^;{}]+;", class_body(text, name))


def read_sdk(path):
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Legacy Windows comments; all checked declarations are ASCII.
        return raw.decode("latin-1")


def enum_declaration(text, name):
    match = re.search(r"\benum\s+" + re.escape(name) + r"\s*\{[^}]+\}\s*;",
                      without_comments(text), flags=re.S)
    if not match:
        raise ContractError(f"Enum declaration not found: {name}")
    return match[0]


def object_contract(source, item):
    body = class_body(source, item["name"])
    parts = re.split(r"\bprivate\s*:", body)
    if len(parts) != 2:
        raise ContractError(f"Expected one private section in {item['name']}")
    public, private = parts
    if tokens(private) != tokens(item["private_declarations"]):
        raise ContractError(f"SDK opaque layout changed: {item['namespace']}::{item['name']}")
    if [tokens(v) for v in virtuals(source, item["name"])] != [tokens(v) for v in item["virtuals"]]:
        raise ContractError(f"SDK opaque vtable changed: {item['namespace']}::{item['name']}")
    declarations = [tokens(d + ";") for d in public.split(";")]
    for method in item["checked_methods"]:
        # Access labels can precede the first declaration in a section.
        if not any(tokens(method) == d[-len(tokens(method)):] for d in declarations):
            raise ContractError(f"SDK native method changed: {item['name']}: {method}")
    return public


def read_guid(text, name):
    match = re.search(r"\bstatic\s+const\s+GUID\s+" + re.escape(name) + r"\s*=\s*\{(.*?)\};",
                      without_comments(text), flags=re.S)
    if not match:
        raise ContractError(f"GUID declaration not found: {name}")
    values = [int(value, 16) for value in re.findall(r"0[xX]([\da-fA-F]+)", match[1])]
    if len(values) != 11:
        raise ContractError(f"Unrecognized GUID initializer: {name}")
    a, b, c, *tail = values
    return f"{a:08X}-{b:04X}-{c:04X}-{tail[0]:02X}{tail[1]:02X}-" + "".join(f"{v:02X}" for v in tail[2:])


def check(upstream, profile):
    source = {key: read_sdk(upstream / relative) for key, relative in profile["upstream"].items()}
    body = class_body(source["stream"], "FDataStream")
    members = [field.strip() + ";" for field in body.rsplit("protected:", 1)[-1].split(";") if field.strip()]
    endian = re.search(r"\benum\s+EEndianness\s*\{([^}]+)\}",
                       without_comments(source["endian"]), flags=re.S)
    if not endian:
        raise ContractError("EEndianness declaration not found")
    actual = {
        "unknown_virtuals": virtuals(source["interfaces"], "ICvUnknown"),
        "context_prefix": virtuals(source["interfaces"], "ICvGameContext1")[:2],
        "stream_virtuals": virtuals(source["stream"], "FDataStream"),
        "stream_members": members,
        "endianness": [value.strip() for value in endian[1].split(",") if value.strip()],
    }
    for key, expected in profile["declarations"].items():
        observed = actual[key]
        if [tokens(v) for v in observed] != [tokens(v) for v in expected]:
            raise ContractError(f"SDK ABI contract changed: {key}\nExpected: {expected}\nObserved: {observed}")
    for item in profile.get("interface_contracts", []):
        text = source[item["source"]]
        observed = virtuals(text, item["name"])
        if [tokens(v) for v in observed] != [tokens(v) for v in item["virtuals"]]:
            raise ContractError(f"SDK interface slots changed: {item['name']}")
        inheritance = re.search(r"\bclass\s+" + item["name"] + r"\s*:\s*public\s+(\w+)\s*\{", without_comments(text))
        if not inheritance or inheritance[1] != item["base"]:
            raise ContractError(f"SDK interface base changed: {item['name']}")
        actual[f"interface_{item['name']}"] = observed
    for item in profile.get("class_contracts", []):
        observed = class_body(source[item["source"]], item["name"])
        if tokens(observed) != tokens(item["body"]):
            raise ContractError(f"SDK native class changed: {item['name']}")
        actual[f"class_{item['name']}"] = [observed]
    for name, expected in profile["interface_guids"].items():
        declarations = [text for key, text in source.items() if key.startswith("interfaces")
                        and re.search(r"\b" + re.escape(name) + r"\s*=", text)]
        if len(declarations) != 1:
            raise ContractError(f"Expected one SDK GUID declaration: {name}")
        observed = read_guid(declarations[0], name)
        if observed != expected:
            raise ContractError(f"SDK GUID changed: {name}: {observed} (expected {expected})")
    for item in profile.get("opaque_classes", []):
        object_contract(source[item["source"]], item)
        actual[f"opaque_{item['namespace']}_{item['name']}"] = [item["private_declarations"]] + item["virtuals"] + item["checked_methods"]
    for item in profile.get("native_enums", []):
        observed = enum_declaration(source[item["source"]], item["name"])
        if tokens(observed) != tokens(item["declaration"]):
            raise ContractError(f"SDK native enum changed: {item['name']}")
        actual[f"enum_{item['name']}"] = [observed]
    for item in profile.get("derived_classes", []):
        text = without_comments(source[item["source"]])
        inheritance = re.search(r"\bclass\s+" + item["name"] + r"\s*(:[^;{]+)\{", text)
        if not inheritance or tokens(inheritance[1]) != tokens(": public " + item["base"]) or tokens(class_body(text, item["name"])) != tokens(item["body"]):
            raise ContractError(f"SDK derived layout changed: {item['name']}")
        actual[f"derived_{item['name']}"] = [item["base"], item["body"]]
    for item in profile.get("native_functions", []):
        if tokens(item["declaration"]) not in [tokens(d + ";")[-len(tokens(item["declaration"])):]
                                               for d in without_comments(source[item["source"]]).split(";")]:
            raise ContractError(f"SDK native function changed: {item['declaration']}")
        actual[f"function_{item['name']}"] = [item["declaration"]]
    return actual


def guid_initializer(value):
    parsed = uuid.UUID(value)
    a, b, c = parsed.fields[:3]
    tail = parsed.bytes[8:]
    return "{0x%08x, 0x%04x, 0x%04x, {%s}}" % (a, b, c, ", ".join(f"0x{v:02x}" for v in tail))


def generate(upstream, profile):
    actual = check(upstream, profile)
    lines = ["// Generated from the upstream SDK; do not edit.", "#pragma once",
             '#include "vp_mac/native_types.hpp"', '#include "vp_mac/engine_identity.hpp"', "#include <array>", "#include <exception>", "namespace vp_mac::sdk {",
             "using GUID = Guid;"]
    for name, value in profile["interface_guids"].items():
        lines.append(f"inline constexpr Guid {name} = {guid_initializer(value)};")
    lines += ["// The four leading slots only; never delete or own this view.", "class ContextPrefix {", "public:"]
    for declaration in actual["unknown_virtuals"] + actual["context_prefix"]:
        lines.append(declaration.replace("DLLCALL", ""))
    lines += ["};", "class FEndian { public: enum EEndianness {" + ", ".join(actual["endianness"]) + "}; };",
              "// Complete base stream vtable/data layout; behavior is supplied by the probe.",
              "class StreamView {", "public:"]
    lines.append(actual["stream_virtuals"][0].replace("~FDataStream", "~StreamView").replace(";", " = default;"))
    for declaration in actual["stream_virtuals"][1:]:
        lines.append(declaration if re.search(r"=\s*0\s*;", declaration) else declaration[:-1] + " = 0;")
    lines += ["protected:"] + actual["stream_members"] + ["};"]
    layout = profile["stream_layout"]
    lines += [f"static_assert(sizeof(StreamView) == {layout['size']});",
              f"static_assert(alignof(StreamView) == {layout['alignment']});",
              f"inline constexpr unsigned kStreamEndianOffset = {layout['endianness_offset']};"]
    lines += [f"inline constexpr Guid kStockDllGuid = {guid_initializer(profile['stock_dll_guid'])};",
              f"inline constexpr char kStockDllVersion[] = {json.dumps(profile['stock_dll_version'])};"]
    for name, value in profile["symbols"].items():
        lines.append(f"inline constexpr char k_symbol_{name}[] = {json.dumps(value)};")
    lines.append("} // namespace vp_mac::sdk")
    return "\n".join(lines) + "\n"


def native_save_header(profile):
    save = profile["native_save"]
    guid = uuid.UUID(save["guid"])
    if guid.int == 0 or guid == uuid.UUID(profile["stock_dll_guid"]):
        raise ContractError("Native save GUID must differ from the stock core")
    if type(save["format"]) is not int or not 0 < save["format"] < 2**32 or save["magic"] != "VPMACSAV":
        raise ContractError("Invalid native save format descriptor")
    return save["magic"].encode("ascii") + struct.pack("<I", save["format"]) + guid.bytes


def generate_identity(profile):
    save = profile["native_save"]
    header = native_save_header(profile)
    lines = ["// Generated native image/save identities; C++14 compatible.", "#pragma once", "#include <array>",
             '#include "vp_mac/native_types.hpp"',
             "namespace vp_mac { namespace sdk {"]
    for name in ["host_uuid", "stock_core_uuid"]:
        data = ", ".join(f"0x{v:02x}" for v in uuid.UUID(profile[name]).bytes)
        lines.append(f"static constexpr std::array<unsigned char, 16> k_{name} = {{{{{data}}}}};")
    lines += [f"static constexpr Guid kNativeSaveGuid = {guid_initializer(save['guid'])};",
              f"static constexpr char kNativeSaveGuidText[] = {json.dumps(save['guid'])};",
              f"static constexpr unsigned kNativeSaveFormat = {save['format']};",
              f"static constexpr std::array<unsigned char, {len(header)}> kNativeSaveHeader = {{{{" +
              ", ".join(f"0x{v:02x}" for v in header) + "}};",
              f"static constexpr char kProfileName[] = {json.dumps(profile['name'])};", "} }"]
    return "\n".join(lines) + "\n"


def generate_host_functions(profile):
    lines = ['// Reviewed native entry points; no engine code is patched.', '#pragma once',
             '#include "vp_mac/host_functions.hpp"', 'namespace vp_mac { namespace sdk {']
    names = []
    for name, item in profile.get("internal_functions", {}).items():
        code = bytes.fromhex(item["code_prefix"])
        if not re.fullmatch(r"[a-z_]+", name) or len(code) != 32 or not 0 < item["rva"] < 32 * 1024 * 1024:
            raise ContractError(f"Invalid reviewed native function: {name}")
        data = ", ".join(f"0x{byte:02x}" for byte in code)
        lines.append(f'static constexpr HostFunction k_{name} = {{"{name}", 0x{item["rva"]:x}, {{{data}}}}};')
        names.append(name)
    lines += ['inline bool host_functions_match() {', '    return host_is_reviewed()' +
              ''.join(f' && host_function_matches(k_{name})' for name in names) + ';', '}', '} }']
    return '\n'.join(lines) + '\n'


def verify_host(binary, profile):
    data = binary.read_bytes()
    if hashlib.sha256(data).hexdigest() != profile["host_sha256"]:
        raise ContractError("Native host executable differs from the reviewed SHA-256; review its ABI before linking.")
    for name, item in profile["internal_functions"].items():
        code = bytes.fromhex(item["code_prefix"])
        if data[item["rva"]:item["rva"] + len(code)] != code:
            raise ContractError(f"Reviewed native function bytes differ: {name}")


def verify_core(binary, profile):
    """Check every reviewed slot in the actual linked core's Itanium vtable."""
    data = binary.read_bytes()
    if len(data) < 32 or struct.unpack_from("<I", data)[0] != 0xfeedfacf:
        raise ContractError("Expected a thin 64-bit Mach-O core")
    segments, offset = [], 32
    for _ in range(struct.unpack_from("<I", data, 16)[0]):
        command, size = struct.unpack_from("<II", data, offset)
        if size < 8 or offset + size > len(data):
            raise ContractError("Invalid Mach-O load command")
        if command == 0x19:
            vm, _, file_offset, file_size = struct.unpack_from("<QQQQ", data, offset + 24)
            segments.append((vm, file_offset, file_size))
        offset += size
    def read_pointer(address):
        for vm, file_offset, size in segments:
            if vm <= address and address + 8 <= vm + size:
                return struct.unpack_from("<Q", data, file_offset + address - vm)[0]
        raise ContractError(f"Vtable address outside Mach-O file: {address:#x}")
    result = subprocess.run(["nm", "-n", str(binary)], capture_output=True, text=True, check=True)
    names, addresses = {}, {}
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+\w\s+(\S+)", line)
        if match:
            address, name = int(match[1], 16), match[2]
            names[name] = address
            addresses.setdefault(address, set()).add(name)
    reports = []
    for table in profile.get("core_vtables", []):
        if table["symbol"] not in names:
            raise ContractError(f"Missing core vtable: {table['symbol']}")
        start = names[table["symbol"]] + 16  # offset-to-top and RTTI
        for slot, expected in enumerate(table["slot_symbols"]):
            actual = addresses.get(read_pointer(start + slot * 8), set())
            if expected not in actual:
                raise ContractError(f"Core ABI mismatch: {table['class']} slot {slot} ({slot * 8:#x}): expected {expected}, observed {sorted(actual)}")
        reports.append({"class": table["class"], "slots_checked": len(table["slot_symbols"])})
    if "native_save" in profile:
        if native_save_header(profile) not in data or profile["native_save"]["guid"].encode() not in data:
            raise ContractError("Core is missing the reviewed native save identity/header")
    return {"core_vtables": reports, "native_save": profile.get("native_save"), "result": "passed"}


def generate_objects(upstream, profile):
    """Keep upstream public declarations; native code owns all private storage.

    No Windows STL type is substituted with a differently sized libc++ type.
    These class names/signatures retain the native host's C++ symbol names.
    """
    check(upstream, profile)
    source = {key: read_sdk(upstream / relative) for key, relative in profile["upstream"].items()}
    lines = ["// Generated from upstream declarations; do not edit.", "#pragma once",
             "#include <cstddef>", "#include <ostream>", "#include <fstream>", "#include <string>",
             "#ifndef CvGameDatabaseAPI", "#define CvGameDatabaseAPI", "#endif",
             'static_assert(sizeof(long) == 8, "Native LP64 profile");',
             'static_assert(sizeof(std::string) == 24, "Native libc++ string layout");',
             "struct sqlite3; struct sqlite3_stmt;",
             "namespace Database { class Command; class IDatabaseLogger; class Results; }",
             "namespace Localization { class Language; class ParameterArgument; }"]
    for item in profile["native_enums"]:
        lines += [f"namespace {item['namespace']} {{", enum_declaration(source[item["source"]], item["name"]), "}"]
    for item in profile["opaque_classes"]:
        public = object_contract(source[item["source"]], item)
        public = re.sub(r"\b(?:CvGameDatabaseAPI|CvLocalizationAPI|_In_z_)\b", "", public)
        public = re.sub(r"\b_In_bytecount_\s*\([^()]*\)", "", public)
        public = re.sub(r"\b__int64\b", profile["native_integer64_type"], public)
        lines += [f"namespace {item['namespace']} {{", f"class {item['name']} {{", public, "private:"]
        if item.get("noncopyable"):
            # Preserve the upstream inaccessible copy/assignment declarations.
            private = item["private_declarations"]
            lines += re.findall(r"\b" + item["name"] + r"(?:&\s*operator\s*=)?\s*\([^;]+;", private)
        private_bytes = item["size"] - item["vptr_bytes"]
        lines += [f"alignas({item['alignment']}) unsigned char native_private_[{private_bytes}];", "};",
                  f'static_assert(sizeof({item["name"]}) == {item["size"]}, "Native SDK object size");',
                  f'static_assert(alignof({item["name"]}) == {item["alignment"]}, "Native SDK object alignment");', "}"]
    for item in profile.get("derived_classes", []):
        body = re.sub(r"\bCvGameDatabaseAPI\b", "", class_body(source[item["source"]], item["name"]))
        lines += [f"namespace {item['namespace']} {{", f"class {item['name']} : public {item['base']} {{",
                  body, "};", f'static_assert(sizeof({item["name"]}) == {item["size"]}, "Native SDK derived size");', "}"]
    for item in profile.get("native_functions", []):
        lines += [f"namespace {item['namespace']} {{",
                  item["declaration"].replace("CvLocalizationAPI", ""), "}"]
    if profile.get("string_helpers"):
        text = source["localization"]
        matches = list(re.finditer(r"std::ostream\s*&\s*operator\s*<<\s*\(", text))
        if len(matches) != 1 or not re.search(r"#endif\s*//_CVLOCALIZATION_H\s*$", text):
            raise ContractError("Review upstream localization template helper section")
        lines.append(text[matches[0].start():text.rfind("#endif")])
    return "\n".join(lines) + "\n"


def inventory(upstream, profile):
    checked = check(upstream, profile)
    project = upstream / "CvGameCoreDLL_Expansion2/VoxPopuli.vcxproj"
    tree = ET.parse(project)
    ns = {"ms": "http://schemas.microsoft.com/developer/msbuild/2003"}
    sources = sorted({item.attrib["Include"].replace("\\", "/")
                      for item in tree.findall(".//ms:ClCompile[@Include]", ns)})
    include_directories = set()
    for item in tree.findall(".//ms:ClCompile/ms:AdditionalIncludeDirectories", ns):
        for value in (item.text or "").split(";"):
            value = value.strip()
            if not value or value.startswith("%("):
                continue  # Inherited MSBuild settings, not source directories.
            value = value.replace("$(SolutionDir)", "").replace("\\", "/").rstrip("/")
            if "$" in value or "%" in value or Path(value).is_absolute() or ".." in Path(value).parts:
                raise ContractError(f"Review upstream include-directory expression: {value}")
            include_directories.add(value)
    commit = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip() or None
    # Read literal data without importing/executing the Windows build script.
    warnings = []
    for statement in ast.parse((upstream / "build_vp_clang.py").read_text()).body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CL_SUPPRESS" for t in statement.targets):
            warnings = ast.literal_eval(statement.value)
    if not all(isinstance(w, str) and re.fullmatch(r"[a-z0-9-]+", w) for w in warnings):
        raise ContractError("Review upstream Clang warning options")
    return {"schema": 1, "upstream_commit": commit, "upstream_root": str(upstream),
            "abi_profile": profile["name"], "contract_passed": True,
            "declaration_fingerprint": hashlib.sha256(json.dumps(
                {k: [tokens(v) for v in values] for k, values in checked.items()}, sort_keys=True).encode()).hexdigest(),
            "upstream_source_count": len(sources), "upstream_sources": sources,
            "upstream_include_directories": sorted(include_directories),
            "upstream_clang_suppressed_warnings": warnings,
            "upstream_files_modified_by_mac_layer": 0,
            "scope": "Native SDK contract and upstream source inventory; runtime gameplay validation is separate"}


def compiler_overlay(upstream, output, mappings, external_names=()):
    """Redirect only edited files, including quoted/absolute SDK includes.

    Preserve their logical upstream names so sibling includes still resolve
    against the original SDK. This avoids a copied or symlinked source tree.
    """
    root = {"type": "directory", "contents": []}
    for source, destination in mappings:
        directory = root
        parts = Path(source).parts
        for part in parts[:-1]:
            child = next((item for item in directory["contents"] if item["name"] == part), None)
            if child is None:
                child = {"type": "directory", "name": part, "contents": []}
                directory["contents"].append(child)
            directory = child
        entry = {"type": "file", "name": parts[-1], "external-contents": str((output / destination).resolve())}
        if source in external_names:
            entry["use-external-name"] = True
        directory["contents"].append(entry)
    # macOS exposes /var through /private/var; builds may also select a checkout
    # through a symlink. Clang can encounter either spelling before realpath().
    roots = [{**root, "name": name} for name in sorted({str(upstream.absolute()), str(upstream.resolve())})]
    return {"version": 0, "use-external-names": False, "roots": roots}


def prepare(upstream, profile, output):
    writable_output(upstream, output)
    # Validate every edit before writing any generated artifact.
    files = {"vp_mac/sdk_contract.hpp": generate(upstream, profile).encode(),
             "vp_mac/engine_objects.hpp": generate_objects(upstream, profile).encode(),
             "vp_mac/engine_identity.hpp": generate_identity(profile).encode(),
             "vp_mac/host_function_profile.hpp": generate_host_functions(profile).encode()}
    applied = []
    mappings = {}
    owners = {}
    for edit in json.loads(OVERLAYS.read_text())["edits"]:
        source = (upstream / edit["source"]).read_bytes()
        if edit["output"] in owners and owners[edit["output"]] != edit["source"]:
            raise ContractError(f"Overlay output collision: {edit['output']}")
        if edit["source"] in mappings and mappings[edit["source"]] != edit["output"]:
            raise ContractError(f"Overlay source has multiple destinations: {edit['source']}")
        owners[edit["output"]] = edit["source"]
        current = files.get(edit["output"], source)
        if "qualified_functions" in edit:
            regions = re.findall(edit["pattern"], current.decode("latin-1"))
            qualifiers = {name.rsplit("::", 1)[0] for name in edit["qualified_functions"]}
            pattern = r"\b((?:" + "|".join(re.escape(name) for name in sorted(qualifiers)) + r")::\w+)\s*\("
            functions = re.findall(pattern, "\n".join(regions))
            if functions != edit["qualified_functions"]:
                raise ContractError(f"Portability overlay region changed: {edit['name']}: review its function boundaries.")
        rewritten, count = re.subn(edit["pattern"], edit["replacement"], current.decode("latin-1"))
        if count != edit["matches"]:
            raise ContractError(f"Portability overlay changed: {edit['name']}: expected {edit['matches']} matches, found {count}. Review the upstream change.")
        files[edit["output"]] = rewritten.encode("latin-1")
        mappings[edit["source"]] = edit["output"]
        applied.append({"name": edit["name"], "source": edit["source"], "matches": count,
                        "source_sha256": hashlib.sha256(source).hexdigest()})
    for relative in profile.get("sdk_projection_headers", []):
        if not (upstream / relative).is_file():
            raise ContractError(f"Native SDK projection source missing: {relative}")
        mappings[relative] = "vp_mac/engine_objects.hpp"
    version = subprocess.run(["git", "-C", str(upstream), "describe", "--tags", "--long", "--always", "--dirty"],
                             capture_output=True, text=True).stdout.strip() or "Unknown upstream revision"
    files["vp_mac/commit_id.inc"] = ('// Generated outside the upstream checkout.\nconst char CURRENT_GAMECORE_VERSION[] = ' +
                                    json.dumps(version + " Mac", ensure_ascii=False) + ';\n').encode()
    mappings["commit_id.inc"] = "vp_mac/commit_id.inc"
    files["clang-overlay.json"] = (json.dumps(compiler_overlay(upstream, output, mappings.items(), {"commit_id.inc"}), indent=2) + "\n").encode()
    # With logical upstream paths in depfiles, the compiler cannot otherwise
    # notice changed external contents. Force-include this stable revision file
    # so every consumer rebuilds after an effective overlay change.
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        if name in {"vp_mac/commit_id.inc", "clang-overlay.json"} or name.endswith(".cpp"):
            continue  # Per-source physical dependencies handle these inputs.
        digest.update(name.encode() + b"\0" + data + b"\0")
    header_mappings = [(source, destination) for source, destination in mappings.items()
                       if not source.endswith(".cpp") and source != "commit_id.inc"]
    digest.update(json.dumps(header_mappings, sort_keys=True).encode())
    files["vp_mac/overlay_revision.hpp"] = ("#pragma once\n// Generated overlay revision: " + digest.hexdigest() + "\n").encode()
    files["overlay-report.json"] = (json.dumps({"applied": applied, "upstream_files_written": 0}, indent=2) + "\n").encode()
    for relative, data in files.items():
        path = output / relative
        writable_output(upstream, path)
        if path.is_symlink():
            raise ContractError(f"Refusing a symlink in generated output: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    return {"generated_directory": str(output), "portability_edits": len(applied), "upstream_files_written": 0}


def writable_output(upstream, output):
    if output.resolve().is_relative_to(upstream.resolve()):
        raise ContractError("Generated output must be outside the upstream checkout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "generate", "prepare", "inventory", "verify-host", "verify-core"])
    parser.add_argument("--upstream", type=Path, default=ROOT.parent / "Community-Patch-DLL")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text())
        if args.command == "verify-core":
            if not args.binary:
                raise ContractError("verify-core requires --binary")
            print(json.dumps(verify_core(args.binary, profile), indent=2))
            return
        if args.command == "verify-host":
            if not args.binary:
                raise ContractError("verify-host requires --binary")
            verify_host(args.binary, profile)
            print("Reviewed host executable and native entry-point bytes match.")
            return
        if args.output:
            writable_output(args.upstream, args.output)
        if args.command == "prepare":
            if not args.output:
                raise ContractError("prepare requires --output pointing to a build directory")
            print(json.dumps(prepare(args.upstream, profile, args.output), indent=2))
            return
        if args.command == "generate":
            output = generate(args.upstream, profile)
        elif args.command == "inventory":
            output = json.dumps(inventory(args.upstream, profile), indent=2) + "\n"
        else:
            check(args.upstream, profile)
            output = f"SDK ABI contract matches {profile['name']}. Upstream gameplay files were not modified.\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if not args.output.exists() or args.output.read_text() != output:
                args.output.write_text(output)
        else:
            print(output, end="")
    except (ContractError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
