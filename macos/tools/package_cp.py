#!/usr/bin/env python3
"""Build a CP or Vox Populi modpack without changing the game or upstream.

Uses the same full-database XML format as upstream's ModpackMaker.lua. SQLite
and the mod manifest supply the content; no gameplay tables or values are kept
in this tool. Optional runtime assets follow the mod's manifest and upstream
modpack addin declarations. Runtime gameplay still requires manual validation.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "VP_MAC_CP"
MANIFEST = "vp-mac-package.json"


def core_save_identity(core):
    profile = json.loads((ROOT / "macos/abi/aspyr-steam-1.4.2.json").read_text())
    save = profile["native_save"]
    data = core.read_bytes()
    header = save["magic"].encode() + save["format"].to_bytes(4, "little") + uuid.UUID(save["guid"]).bytes
    return save if save["guid"].encode() in data and header in data else None


class PackageError(RuntimeError):
    pass


def sha256(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def xml(path):
    # Firaxis accepts decorative comments containing '--'; ElementTree does not.
    return ET.fromstring(re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8-sig"), flags=re.S))


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def fields(node):
    result = dict(node.attrib)
    for child in node:
        if len(child) or child.attrib or child.tag in result:
            raise PackageError(f"Unsupported XML field: {ET.tostring(child, encoding='unicode')}")
        result[child.tag] = child.text or ""
    return result


def value(text, kind):
    if kind.lower() == "boolean" and text.lower() in {"true", "false"}:
        return int(text.lower() == "true")
    return text


def apply_xml(db, root):
    """Small, fail-closed subset used by the upstream CP manifest."""
    if root.tag != "GameData":
        raise PackageError(f"Expected GameData, found {root.tag}")
    for table in root:
        if table.tag == "Table":
            columns = []
            for col in table:
                allowed = {"name", "type", "primarykey", "autoincrement", "notnull", "unique", "default", "reference"}
                if col.tag != "Column" or set(col.attrib) - allowed or len(col):
                    raise PackageError(f"Unsupported column declaration: {col.attrib}")
                name, kind = col.attrib["name"], col.attrib["type"]
                if kind.lower() not in {"integer", "int", "text", "boolean", "real", "float", "string", "variant"}:
                    raise PackageError(f"Unsupported column type: {kind}")
                sql = identifier(name) + " " + kind
                for attr, clause in [("primarykey", " PRIMARY KEY"), ("autoincrement", " AUTOINCREMENT"),
                                     ("notnull", " NOT NULL"), ("unique", " UNIQUE")]:
                    if attr in col.attrib:
                        if col.attrib[attr] not in {"true", "false"}:
                            raise PackageError(f"Invalid column flag: {col.attrib}")
                        if col.attrib[attr] == "true":
                            sql += clause
                if "default" in col.attrib:
                    default = value(col.attrib["default"], kind)
                    sql += " DEFAULT " + db.execute("SELECT quote(?)", (default,)).fetchone()[0]
                # Like the engine, validation references do not enable SQLite
                # foreign-key enforcement during ordered mod actions.
                if "reference" in col.attrib:
                    match = re.fullmatch(r"(\w+)\((\w+)\)", col.attrib["reference"])
                    if not match:
                        raise PackageError(f"Unsupported reference: {col.attrib['reference']}")
                    sql += " REFERENCES " + identifier(match[1]) + "(" + identifier(match[2]) + ")"
                columns.append(sql)
            db.execute("CREATE TABLE " + identifier(table.attrib["name"]) + " (" + ",".join(columns) + ")")
            continue
        kinds = {r[1].casefold(): r[2] for r in db.execute("PRAGMA table_info(" + identifier(table.tag) + ")")}
        if not kinds:
            raise PackageError(f"No table for XML action: {table.tag}")
        for operation in table:
            if operation.tag in {"Row", "Replace"}:
                row = fields(operation)
                if {k.casefold() for k in row} - kinds.keys():
                    raise PackageError(f"Unknown columns in {table.tag}: {set(row) - kinds.keys()}")
                insert = "INSERT OR REPLACE INTO " if operation.tag == "Replace" else "INSERT INTO "
                db.execute(insert + identifier(table.tag) + " (" + ",".join(map(identifier, row)) + ") VALUES ("
                           + ",".join("?" for _ in row) + ")", [value(v, kinds[k.casefold()]) for k, v in row.items()])
            elif operation.tag == "Delete":
                row = fields(operation)
                if {k.casefold() for k in row} - kinds.keys():
                    raise PackageError(f"Unknown Delete columns in {table.tag}")
                condition = " AND ".join(identifier(k) + " = ?" for k in row)
                db.execute("DELETE FROM " + identifier(table.tag) + (" WHERE " + condition if row else ""), list(row.values()))
            else:
                raise PackageError(f"Unsupported XML operation: {table.tag}/{operation.tag}")


def xml_shape(node):
    return node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(), tuple(map(xml_shape, node))


def existing_stock_action(db, root, stock_documents):
    """Reuse a bundled row-only document only while every complete row matches.

    VP includes the Explorer map definitions also shipped by Aspyr. Do not turn
    duplicate-key errors into general INSERT OR IGNORE behavior.
    """
    source = stock_documents.get(xml_shape(root))
    if source is None or not len(root):
        return None
    for table in root:
        columns = list(db.execute("PRAGMA table_info(" + identifier(table.tag) + ")"))
        if not columns or not len(table):
            return None
        for operation in table:
            if operation.tag != "Row":
                return None
            row = {k.casefold(): v for k, v in fields(operation).items()}
            if row.keys() - {c[1].casefold() for c in columns}:
                return None
            values = []
            for _, name, kind, _, default, pk in columns:
                if name.casefold() in row:
                    values.append(value(row[name.casefold()], kind))
                elif pk:
                    return None  # An implicit key would allocate a different row.
                else:
                    values.append(db.execute("SELECT " + default).fetchone()[0] if default is not None else None)
            condition = " AND ".join(identifier(c[1]) + " IS ?" for c in columns)
            if db.execute("SELECT COUNT(*) FROM " + identifier(table.tag) + " WHERE " + condition, values).fetchone()[0] != 1:
                return None
    return source


def upstream_set(source, name):
    match = re.search(r"local " + re.escape(name) + r" = \{([^}]+)\};", source)
    if not match:
        raise PackageError(f"Upstream modpack contract changed: {name}")
    body = re.sub(r"--[^\n]*", "", match[1])
    names = re.findall(r"(\w+)\s*=\s*true\s*,", body)
    if re.sub(r"\w+\s*=\s*true\s*,", "", body).strip():
        raise PackageError(f"Unsupported upstream modpack list: {name}")
    return set(names)


def runtime_files(mod_dir, mod, maker, package, folder="CommunityPatch", register=True):
    """Use upstream's VFS manifest and modpack addin convention, without DLLs.

    Keep source paths under each mod's folder. Only the five upstream addin
    consumers gain a UI copy; generated registration lines modify those copies.
    """
    match = re.search(r"local ADDIN_FILES = \{(.*?)\n\};", maker, re.S)
    if not match:
        raise PackageError("Upstream modpack contract changed: ADDIN_FILES")
    body = re.sub(r"--[^\n]*", "", match[1])
    pattern = r'\{\s*File\s*=\s*"([\w.]+)"\s*,\s*AddinType\s*=\s*"(\w+)"\s*,\s*\}\s*,'
    consumers = re.findall(pattern, body)
    if not consumers or re.sub(pattern, "", body).strip() or len({v for _, v in consumers}) != len(consumers):
        raise PackageError("Unsupported upstream modpack addin declaration")
    by_type = {kind: name for name, kind in consumers}
    declared, selected, basenames = {}, {}, {}
    dlls = {n.text.replace("\\", "/") for n in mod.findall("./Actions/OnGetDLLPath/SetDllPath")}

    def source_path(value):
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or not path.parts or ".." in path.parts or ":" in str(path):
            raise PackageError(f"Unsafe runtime file path: {value}")
        source = mod_dir / str(path)
        if not source.resolve().is_relative_to(mod_dir.resolve()) or source.is_symlink() or not source.is_file():
            raise PackageError(f"Missing or unsafe runtime file: {value}")
        return str(path), source

    for node in mod.findall("./Files/File"):
        if node.get("import") not in {"0", "1"}:
            raise PackageError(f"Unsupported VFS import flag: {node.attrib}")
        name, source = source_path(node.text or "")
        if name in declared:
            raise PackageError(f"Duplicate runtime file declaration: {name}")
        declared[name] = source
        if node.get("import") == "1" and name not in dlls:
            selected[name] = source

    addins, maps = [], []
    for node in mod.findall("./EntryPoints/EntryPoint"):
        kind = node.get("type")
        if kind not in by_type and kind != "MapScript":
            raise PackageError(f"Unsupported runtime entry point: {kind}")
        name, source = source_path(node.get("file", ""))
        if name not in declared:
            raise PackageError(f"Undeclared runtime entry point: {name}")
        selected[name] = source
        if kind == "MapScript":
            maps.append(name)
            continue
        # An XML UI context and its Lua companion must both survive, including
        # companions marked import=0. Lua-only contexts remain valid.
        for extension in [".lua", ".xml"]:
            sibling = str(PurePosixPath(name).with_suffix(extension))
            if sibling in declared:
                selected[sibling] = declared[sibling]
        addins.append({"type": kind, "file": name, "context": PurePosixPath(name).stem,
                       "consumer": by_type[kind]})

    for name, source in selected.items():
        if source.suffix.lower() in {".dll", ".dylib", ".so", ".exe"}:
            raise PackageError(f"Unexpected executable in runtime assets: {name}")
        key = source.name.casefold()
        if key in basenames:
            raise PackageError(f"Ambiguous runtime VFS basename: {source.name}")
        basenames[key] = source
        target = package / "Mods" / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for filename, _ in consumers:
        source = basenames.get(filename.casefold())
        if source:
            shutil.copyfile(source, package / "UI" / filename)
    if register:
        register_addins(addins, package)
    return {"files_copied": len(selected), "source_files": {name: sha256(p) for name, p in sorted(selected.items())},
            "addins": addins, "map_scripts": maps, "folder": folder, "excluded_dll_paths": sorted(dlls),
            "mod_manifest_sha256": sha256(next(mod_dir.glob("*.modinfo"))),
            "modpack_maker_sha256": hashlib.sha256(maker.encode()).hexdigest()}


def register_addins(addins, package):
    for addin in addins:
        target = package / "UI" / addin["consumer"]
        text = target.read_text() if target.is_file() else ""
        if not re.search(r"local\s+g_uiAddins\s*=\s*\{\s*\}", text):
            raise PackageError(f"Upstream addin consumer changed: {addin['consumer']}")
        line = 'g_uiAddins[#g_uiAddins + 1] = ' + json.dumps(addin["context"], ensure_ascii=False) + ';'
        if line not in text:
            with target.open("a") as f:
                f.write('\n' + line + '\n')


def mod_layers(upstream, include_vp):
    names = [("(1) Community Patch", "d1b6328c-ff44-4b0d-aad7-c657f83610cd")]
    if include_vp:
        names.append(("(2) Vox Populi", "8411a7a8-dad3-4622-a18e-fcc18324c799"))
    layers, versions = [], {}
    for name, expected in names:
        directory = upstream / name
        manifests = list(directory.glob("*.modinfo"))
        if len(manifests) != 1:
            raise PackageError(f"Expected one mod manifest in {name}")
        manifest = manifests[0]
        mod = xml(manifest)
        if mod.get("id") != expected:
            raise PackageError(f"Unexpected mod identity in {name}")
        actions = mod.find("./Actions/OnModActivated")
        if actions is None or not len(actions) or any(n.tag != "UpdateDatabase" for n in actions):
            raise PackageError(f"Unsupported upstream activation action in {name}")
        for dep in mod.findall("./Dependencies/Mod"):
            version = versions.get(dep.get("id"))
            if version is None or not int(dep.get("minversion", "0")) <= version <= int(dep.get("maxversion", "2147483647")):
                raise PackageError(f"Missing or incompatible mod dependency in {name}: {dep.get('id')}")
        versions[expected] = int(mod.get("version", "0"))
        layers.append((directory, mod, manifest))
    return layers


def write_xml(root, path):
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def dump_database(db, destination, skipped_tables, skipped_schemas, language=False):
    root = ET.Element("GameData")
    count = 0
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if (name.startswith("Language_") != language) or name in skipped_tables:
            continue
        columns = list(db.execute("PRAGMA table_info(" + identifier(name) + ")"))
        if not language and name not in skipped_schemas:
            table = ET.SubElement(root, "Table", name=name)
            for _, colname, kind, notnull, default, pk in columns:
                attrs = {"name": colname, "type": kind}
                if pk:
                    attrs["primarykey"] = "true"
                if pk and colname == "ID":
                    attrs["autoincrement"] = "true"
                if pk and colname == "Type":
                    attrs["unique"] = "true"
                if notnull:
                    attrs["notnull"] = "true"
                if default is not None and default.upper() != "NULL":
                    # PRAGMA returns SQL literals; decode, preserving apostrophes.
                    decoded = db.execute("SELECT " + default).fetchone()[0]
                    attrs["default"] = ("true" if decoded else "false") if kind.lower() == "boolean" else str(decoded)
                ET.SubElement(table, "Column", attrs)
        data = ET.SubElement(root, name)
        ET.SubElement(data, "Delete")
        for row in db.execute("SELECT * FROM " + identifier(name)):
            item = ET.SubElement(data, "Row")
            for col, val in zip(columns, row):
                if val is not None:
                    if isinstance(val, bytes):
                        raise PackageError(f"Cannot serialize blob in {name}/{col[1]}")
                    ET.SubElement(item, col[1]).text = str(val)
        count += 1
    write_xml(root, destination)
    return count


def build(upstream, app, cache, core, output, include_runtime=False, include_vp=False):
    with closing(sqlite3.connect(":memory:")) as db:
        return _build(upstream, app, cache, core, output, include_runtime, include_vp, db)


def _build(upstream, app, cache, core, output, include_runtime, include_vp, db):
    if output.exists():
        raise PackageError(f"Output already exists; choose a new build directory: {output}")
    if output.resolve().is_relative_to(upstream.resolve()) or output.resolve().is_relative_to(app.resolve()):
        raise PackageError("Package output must be outside the game and upstream checkout")
    if include_vp and not include_runtime:
        raise PackageError("Vox Populi packaging requires --runtime-assets")
    layers = mod_layers(upstream, include_vp)
    actions = [(directory, action) for directory, mod, _ in layers
               for action in mod.findall("./Actions/OnModActivated/UpdateDatabase")]
    stock = cache / "Civ5DebugDatabase.db"
    localized = cache / "Localization-Merged.db"
    sources = [stock, localized, core] + [manifest for _, _, manifest in layers]
    for p in sources:
        if p.is_symlink() or not p.is_file():
            raise PackageError(f"Expected regular input: {p}")
    with closing(sqlite3.connect(stock.as_uri() + "?mode=ro", uri=True)) as original:
        if original.execute("SELECT 1 FROM sqlite_master WHERE name='CustomModOptions'").fetchone():
            raise PackageError("Input database is already modded; launch stock BNW and quit first")
        installed = {row[0].replace("-", "").upper() for row in original.execute("SELECT PackageID FROM DownloadableContent")}
        required = {n.attrib["id"].replace("-", "").upper() for _, mod, _ in layers for n in mod.findall("./Dependencies/Dlc")}
        if required - installed:
            raise PackageError(f"Stock database lacks required DLC: {sorted(required - installed)}")
        original.backup(db)
    with closing(sqlite3.connect(localized.as_uri() + "?mode=ro", uri=True)) as loc:
        db.execute("CREATE TABLE Language_en_US(Tag TEXT PRIMARY KEY, Text TEXT, Gender TEXT, Plurality TEXT)")
        db.executemany("INSERT INTO Language_en_US VALUES (?,?,?,?)", loc.execute("SELECT * FROM Language_en_US"))
    assets = app / "Contents/Assets/Assets"
    overridden, stock_documents = set(), {}
    # Match upstream OverrideGamePlayFiles: shadow GameData XML only. Index the
    # installed documents too, so identical bundled metadata can be recognized.
    for path in assets.rglob("*.xml"):
        if "<GameData>" in "\n".join(path.read_text(errors="replace").splitlines()[:50]):
            overridden.add(path.name)
            if include_vp:
                try:
                    stock_documents[xml_shape(xml(path))] = str(path.relative_to(assets))
                except ET.ParseError:
                    pass  # Not eligible for exact-document reuse.
    if not {"CIV5Units.xml", "CIV5Units_Mongol.xml"} <= overridden:
        raise PackageError("Expected upstream modpack anchor files in this game")
    # CP 5.4.8 names this one existing SQL file with an XML extension in its
    # action. Keep the narrow repair visible instead of skipping missing data.
    repairs = {"Database Changes/Text/en_US/CoreGameOptionTextChanges.xml":
               "Database Changes/Text/en_US/CoreGameOptionTextChanges.sql"}
    applied, corrections = [], []
    for mod_dir, action in actions:
        name = action.text.replace("\\", "/")
        path = mod_dir / name
        if mod_dir == layers[0][0] and not path.is_file() and name in repairs:
            corrections.append({"action": name, "source": repairs[name]})
            path = mod_dir / repairs[name]
        if not path.resolve().is_relative_to(mod_dir.resolve()) or not path.is_file() or path.is_symlink():
            raise PackageError(f"Missing or unsafe mod action: {name}")
        try:
            if path.suffix.lower() == ".sql":
                db.executescript(path.read_text(encoding="utf-8-sig"))
            elif path.suffix.lower() == ".xml":
                root = xml(path)
                bundled = existing_stock_action(db, root, stock_documents)
                if bundled:
                    corrections.append({"mod": mod_dir.name, "action": name, "stock_source": bundled,
                                        "reason": "identical bundled XML and complete existing rows"})
                else:
                    apply_xml(db, root)
            else:
                raise PackageError(f"Unsupported action file: {path}")
        except (sqlite3.Error, ET.ParseError, PackageError) as e:
            raise PackageError(f"{name}: {e}") from e
        applied.append({"mod": mod_dir.name, "file": name, "sha256": sha256(path)})
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise PackageError("Generated database failed integrity_check")
    maker = (upstream / "(5) Modpack Maker for VP/ModpackMaker.lua").read_text()
    skipped_tables = upstream_set(maker, "SKIPPED_TABLES")
    skipped_schemas = upstream_set(maker, "SKIPPED_SCHEMAS")
    with tempfile.TemporaryDirectory(prefix="vp-cp-package-", dir=output.parent) as temporary:
        package = Path(temporary) / PACKAGE_NAME
        override = package / "Override"
        override.mkdir(parents=True)
        for name in overridden:
            (override / name).write_bytes(b"")
        table_count = dump_database(db, override / "CIV5Units.xml", skipped_tables, skipped_schemas)
        dump_database(db, override / "CIV5Units_Mongol.xml", set(), set(), language=True)
        pkg = ET.Element("Civ5Package")
        # Match the official VP modpack package identity/entitlement.
        for key, val in [("GUID", "{b5932ae4-0f4f-498f-9333-e2d31b20e095}"), ("SteamApp", "235580"),
                         ("Version", "1"), ("Priority", "300"), ("Key", "bf6d34a0074b7ad4b1d1716475f7f7fe")]:
            ET.SubElement(pkg, key).text = val
        ET.SubElement(ET.SubElement(pkg, "PTags"), "Tag").text = "Version"
        for key in ["Name", "Description"]:
            ET.SubElement(ET.SubElement(pkg, key), "Value", language="en_US").text = "VP Mac Vox Populi data" if include_vp else "VP Mac CP startup data"
        skin = ET.SubElement(pkg, "UISkin", name="Expansion2Primary", set="Expansion2", platform="Common")
        gameplay = ET.SubElement(skin, "GameplaySkin")
        for directory in ["Mods", "UI"]:
            ET.SubElement(gameplay, "Directory").text = directory
            (package / directory).mkdir()
        runtime = None
        if include_runtime:
            if include_vp:
                parts = [runtime_files(directory, mod, maker, package,
                                       folder=f"{i:02d}_{directory.name}", register=False)
                         for i, (directory, mod, _) in enumerate(layers, 1)]
                addins = [a for part in parts for a in part["addins"]]
                register_addins(addins, package)
                runtime = {"layers": parts, "files_copied": sum(p["files_copied"] for p in parts),
                           "addins": addins, "map_scripts": [f for p in parts for f in p["map_scripts"]]}
            else:
                runtime = runtime_files(layers[0][0], layers[0][1], maker, package)
        write_xml(pkg, package / "VPMac.Civ5Pkg")
        inventory = {str(p.relative_to(package)): sha256(p) for p in sorted(package.rglob("*")) if p.is_file()}
        commit = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
        save = core_save_identity(core)
        report = {"schema": 1, "kind": "cp-startup-data", "upstream_commit": commit,
                  "native_core_sha256": sha256(core), "stock_database_sha256": sha256(stock),
                  "localization_sha256": sha256(localized), "actions": applied, "repairs": corrections,
                  "content": "vox-populi" if include_vp else "community-patch",
                  "mods": [{"directory": directory.name, "id": mod.get("id"), "version": mod.get("version"),
                            "manifest_sha256": sha256(manifest)} for directory, mod, manifest in layers],
                  "gameplay_tables": table_count, "overridden_xml_files": len(overridden),
                  "ui_assets_included": include_runtime, "runtime_assets": runtime,
                  "native_save": save, "gameplay_test_ready": include_runtime and save is not None,
                  "gameplay_validated": False, "files": inventory}
        (package / MANIFEST).write_text(json.dumps(report, indent=2) + "\n")
        package.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=ROOT / "Community-Patch-DLL")
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--core", type=Path, default=ROOT / "prototype/build-core/macos/libCvGameCoreDLL_Expansion2_DLL.dylib")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-assets", action="store_true",
                        help="Include manifest-declared CP UI/Lua/assets for packaging validation; gameplay remains unvalidated")
    parser.add_argument("--vox-populi", action="store_true",
                        help="Add the upstream Vox Populi balance/UI layer after CP; requires --runtime-assets")
    args = parser.parse_args()
    try:
        report = build(*(getattr(args, k).resolve() for k in ["upstream", "app", "cache", "core", "output"]),
                       include_runtime=args.runtime_assets, include_vp=args.vox_populi)
    except (OSError, ValueError, sqlite3.Error, PackageError) as e:
        parser.exit(1, f"Error: {e}\n")
    print(json.dumps({k: v for k, v in report.items() if k not in {"files", "actions", "runtime_assets"}}, indent=2))


if __name__ == "__main__":
    main()
