"""Offline wheel transactions for the existing Python package/extension owners.

Pip owns installed files. Gateway control_operations/schema_meta own intents,
progress and receipts; external artifact files retain recoverable wheels. No
plugin import, index access, dependency installation, new runtime or hot unload.
"""

from __future__ import annotations
import base64
import configparser
from contextlib import contextmanager
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import time
import zipfile
from email.parser import BytesParser
from . import startup

MAX_WHEEL = 25 * 1024 * 1024
PROTECTED = {
    "jaeger-ai",
    "jaeger-agent",
    "jaeger-os",
    "pip",
    "setuptools",
    "wheel",
    "packaging",
}
GROUP = "jaeger_ai.plugins"


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def version(raw):
    from packaging.version import Version

    try:
        return Version(raw)
    except ValueError:
        raise ValueError("Invalid installed package version metadata") from None


def requirement(raw):
    from packaging.requirements import Requirement

    try:
        return Requirement(raw)
    except ValueError:
        raise ValueError("Invalid local dependency metadata") from None


def wheel_info(path):
    """Inspect data only. Deliberately support portable pure wheels, no hooks/.pth/scripts."""
    from packaging.utils import parse_wheel_filename

    try:
        name, version, _, tags = parse_wheel_filename(path.name)
        if not tags or any(
            str(tag) not in {"py3-none-any", "py2.py3-none-any"} for tag in tags
        ):
            raise ValueError()
        if path.stat().st_size > MAX_WHEEL:
            raise ValueError()
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 2048 or sum(m.file_size for m in members) > MAX_WHEEL * 4:
                raise ValueError()
            files = {}
            for member in members:
                if member.is_dir():
                    continue
                part = PurePosixPath(member.filename)
                if (
                    ":" in part.parts[0]
                    or part.is_absolute()
                    or any(p in {"..", "."} or p.startswith(".") for p in part.parts)
                    or "\\" in member.filename
                    or str(part) != member.filename
                    or member.filename.casefold() in {p.casefold() for p in files}
                ):
                    raise ValueError()
                mode = member.external_attr >> 16
                if (
                    stat.S_ISLNK(mode)
                    or member.flag_bits & 1
                    or any(p.endswith(".data") for p in part.parts)
                ):
                    raise ValueError()
                if part.suffix.casefold() in {
                    ".pth",
                    ".so",
                    ".dylib",
                    ".dll",
                    ".exe",
                    ".pyc",
                } or part.name.casefold() in {"sitecustomize.py", "usercustomize.py"}:
                    raise ValueError()
                files[member.filename] = archive.read(member)
            metadata = [p for p in files if p.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError()
            info_dir = metadata[0].rsplit("/", 1)[0]
            if any(
                ".dist-info" in p and not p.startswith(info_dir + "/") for p in files
            ):
                raise ValueError()
            if len(files[metadata[0]]) > 65536:
                raise ValueError()
            meta = BytesParser().parsebytes(files[metadata[0]])
            if canonical(meta["Name"] or "") != canonical(str(name)) or str(
                meta["Version"]
            ) != str(version):
                raise ValueError()
            records = list(
                csv.reader(io.StringIO(files[info_dir + "/RECORD"].decode()))
            )
            if (
                any(len(record) != 3 for record in records)
                or len({r[0] for r in records}) != len(records)
                or {r[0] for r in records} != set(files)
            ):
                raise ValueError()
            for filename, recorded, size in records:
                if filename == info_dir + "/RECORD":
                    if recorded or size:
                        raise ValueError()
                    continue
                algorithm, separator, expected = recorded.partition("=")
                if (
                    not separator
                    or algorithm not in {"sha256", "sha384", "sha512"}
                    or not size.isdecimal()
                    or int(size) != len(files[filename])
                ):
                    raise ValueError()
                if (
                    base64.urlsafe_b64encode(
                        hashlib.new(algorithm, files[filename]).digest()
                    )
                    .decode()
                    .rstrip("=")
                    != expected
                ):
                    raise ValueError()
            wheel = BytesParser().parsebytes(files[info_dir + "/WHEEL"])
            if str(wheel.get("Root-Is-Purelib", "")).lower() != "true":
                raise ValueError()
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read_string(files.get(info_dir + "/entry_points.txt", b"").decode())
            if (
                parser.sections() != [GROUP]
                or not parser.items(GROUP)
                or len(parser.items(GROUP)) > 64
            ):
                raise ValueError()
            roots = {
                PurePosixPath(p).parts[0].removesuffix(".py")
                for p in files
                if not p.startswith(info_dir + "/")
            }
            if (
                not roots
                or {r.casefold() for r in roots}
                & {
                    "jaeger_ai",
                    "jaeger_agent",
                    "jaeger_os",
                    "pip",
                    "setuptools",
                    "packaging",
                    "sitecustomize",
                    "usercustomize",
                }
                or {r.casefold() for r in roots} & sys.stdlib_module_names
            ):
                raise ValueError()
            entries = []
            for entry, value in parser.items(GROUP):
                if (
                    not re.fullmatch(r"[A-Za-z_][\w.]*(?::[A-Za-z_][\w.]*)", value)
                    or value.split(":")[0].split(".")[0] not in roots
                ):
                    raise ValueError()
                entries.append(
                    {
                        "name": entry,
                        "value": value,
                        "slot_id": startup.slot(GROUP, entry, str(name)),
                    }
                )
            return {
                "package": canonical(str(name)),
                "version": str(version),
                "entries": entries,
                "requires": meta.get_all("Requires-Dist", []),
                "roots": sorted(roots),
                "files": files,
                "sha256": digest(path.read_bytes()),
                "filename": path.name,
            }
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        configparser.Error,
        UnicodeError,
    ):
        raise ValueError(
            "Unsupported or unsafe wheel: portable pure Python, one Jaeger entry-point group, no scripts/hooks/native files required"
        ) from None


# Fixed interpreter program: import metadata, never import or register a plugin.
_PROBE = """import sys
sys.prefix=sys.exec_prefix=sys.argv[1]
import importlib.metadata as m,json,sysconfig
rows=[]
for d in m.distributions(path=[sysconfig.get_path('purelib')]):
 name=d.metadata.get('Name',''); files=list(d.files or [])
 rows.append({'name':name,'version':d.version,'requires':d.requires or [],'entries':[{'name':e.name,'value':e.value,'group':e.group} for e in d.entry_points], 'files':[{'relative':str(f),'path':str(d.locate_file(f))} for f in files]})
print(json.dumps({'prefix':sys.prefix,'tag':sys.implementation.cache_tag,'purelib':sysconfig.get_path('purelib'),'distributions':rows}))"""


class PackageOwner:
    def __init__(self, store, *, prefix=None, guard=lambda: None):
        self.store = store
        self.prefix = Path(prefix or sys.prefix).resolve()
        self.python = self.prefix / "bin/python"
        self.environment = startup.environment_id(self.prefix)
        self.guard = guard
        self.artifacts = (
            store.path.parent / "artifacts" / "plugin-packages" / self.environment
        )

    def probe(self):
        if not (self.prefix / "pyvenv.cfg").is_file():
            raise ValueError(
                "Managed virtual environment required; system Python cannot be modified"
            )
        result = subprocess.run(
            [str(self.python), "-I", "-S", "-B", "-c", _PROBE, str(self.prefix)],
            capture_output=True,
            timeout=15,
        )
        if result.returncode:
            raise ValueError("Package metadata inspection unavailable")
        snapshot = json.loads(result.stdout)
        if (
            Path(snapshot["prefix"]).resolve() != self.prefix
            or snapshot["tag"] != sys.implementation.cache_tag
        ):
            raise ValueError("Package environment identity mismatch")
        purelib = Path(snapshot["purelib"]).resolve()
        if not purelib.is_relative_to(self.prefix):
            raise ValueError("Package path escapes managed environment")
        return snapshot

    def directory(self, oid):
        if not isinstance(oid, str) or not oid.strip() or len(oid) > 128:
            raise ValueError("Stable package operation required")
        return self.artifacts / digest(oid.encode())

    @contextmanager
    def locked(self):
        import fcntl

        self.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.artifacts / ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(
                    "Package operation active; inspect without replay"
                ) from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def progress(self, oid):
        conn = self.store._get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key=?",
                ("plugin_package:" + self.environment + ":" + digest(oid.encode()),),
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None

    def checkpoint(self, oid, value):
        with self.store._immediate() as conn:
            conn.execute(
                "INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (
                    "plugin_package:" + self.environment + ":" + digest(oid.encode()),
                    json.dumps(value),
                ),
            )

    def current(self, snapshot, name):
        rows = [
            row for row in snapshot["distributions"] if canonical(row["name"]) == name
        ]
        if len(rows) > 1:
            raise ValueError(
                "Ambiguous installed distribution; no package changes permitted"
            )
        return rows[0] if rows else None

    def files(self, snapshot, row):
        if row is None:
            return {}
        base = Path(snapshot["purelib"]).resolve()
        result = {}
        if not row["files"]:
            raise ValueError("Installed package has no recoverable RECORD")
        for f in row["files"]:
            path = Path(f["path"])
            if path.suffix == ".pyc":
                continue
            if (
                path.is_symlink()
                or path.absolute() != path.resolve()
                or not path.resolve().is_relative_to(base)
            ):
                raise ValueError(
                    "Editable/shared/script package cannot be changed by this control"
                )
            relative = path.resolve().relative_to(base).as_posix()
            if not path.is_file():
                raise ValueError(
                    "Installed package file missing; recovery snapshot incomplete"
                )
            if path.is_file():
                if path.stat().st_size > MAX_WHEEL:
                    raise ValueError("Installed package exceeds recovery bound")
                result[relative] = {
                    "sha256": digest(path.read_bytes()),
                    "mode": stat.S_IMODE(path.stat().st_mode),
                }
        if (
            sum((base / p).stat().st_size for p in result) > MAX_WHEEL * 4
            or len(result) > 2048
            or not result
        ):
            raise ValueError("Package snapshot unavailable")
        return result

    def admissible(self, snapshot, name, info=None):
        row = self.current(snapshot, name)
        if (
            name in PROTECTED
            or row
            and (not row["entries"] or any(e["group"] != GROUP for e in row["entries"]))
        ):
            raise ValueError(
                "Core/non-plugin or mixed-entry-point package is protected"
            )
        if row and self.prefix == Path(sys.prefix).resolve():
            from . import registry
            from types import ModuleType

            if any(
                canonical(loaded["package"]) == name
                for loaded in registry._LOADED.values()
            ):
                raise ValueError(
                    "Loaded plugin code is retained. Disable future startup and coordinate a restart before changing its package files"
                )
            installed = {str(Path(f["path"]).resolve()) for f in row["files"]}
            for module in list(sys.modules.values()):
                if isinstance(module, ModuleType):
                    filename = ModuleType.__getattribute__(module, "__dict__").get(
                        "__file__"
                    )
                    if (
                        isinstance(filename, str)
                        and str(Path(filename).resolve()) in installed
                    ):
                        raise ValueError(
                            "Package module is in use; coordinate restart before package file changes"
                        )
        versions = {
            canonical(r["name"]): r["version"] for r in snapshot["distributions"]
        }
        for other in snapshot["distributions"]:
            if canonical(other["name"]) == name:
                continue
            for raw in other["requires"]:
                dependency = requirement(raw)
                if dependency.marker and not dependency.marker.evaluate({"extra": ""}):
                    continue
                if canonical(dependency.name) == name:
                    if (
                        info is None
                        or version(info["version"]) not in dependency.specifier
                    ):
                        raise ValueError(
                            "Another installed package depends on this distribution; removal/incompatible update refused"
                        )
        if info:
            for raw in info["requires"]:
                dependency = requirement(raw)
                if dependency.marker and not dependency.marker.evaluate({"extra": ""}):
                    continue
                installed = versions.get(canonical(dependency.name))
                if (
                    dependency.url
                    or not installed
                    or version(installed) not in dependency.specifier
                ):
                    raise ValueError(
                        "Dependencies must already be satisfied locally; no fetch or dependency changes supported"
                    )
            own = set(self.files(snapshot, row))
            base = Path(snapshot["purelib"])
            foreign_roots = set()
            for other in snapshot["distributions"]:
                if canonical(other["name"]) != name:
                    foreign_roots.update(
                        PurePosixPath(f["relative"]).parts[0].removesuffix(".py")
                        for f in other["files"]
                        if PurePosixPath(f["relative"]).parts
                        and not PurePosixPath(f["relative"])
                        .parts[0]
                        .endswith(".dist-info")
                    )
            if {r.casefold() for r in info["roots"]} & {
                r.casefold() for r in foreign_roots
            }:
                raise ValueError("Wheel overlaps another package namespace")
            if any(
                not (base / path).resolve().is_relative_to(base.resolve())
                for path in info["files"]
            ):
                raise ValueError("Wheel path escapes package environment")
            if any(
                (base / path).exists() and path not in own for path in info["files"]
            ):
                raise ValueError("Wheel would overwrite unowned package files")
        return row

    def preview(self, path):
        info = wheel_info(path)
        snapshot = self.probe()
        old = self.admissible(snapshot, info["package"], info)
        return {
            k: info[k] for k in ("package", "version", "entries", "requires", "sha256")
        } | {
            "installed_version": old["version"] if old else None,
            "expected_fingerprint": self.fingerprint(snapshot, old),
            "policy_revision": startup.read(self.store, environment=self.environment)[
                "revision"
            ],
            "restart_required": True,
            "activation_performed": False,
            "provenance": "local_wheel_metadata_and_digest_not_publisher_verification",
        }

    def fingerprint(self, snapshot, row):
        return (
            digest(json.dumps(self.files(snapshot, row), sort_keys=True).encode())
            if row
            else "absent"
        )

    def backup(self, snapshot, row, folder):
        if row is None:
            return None
        files = self.files(snapshot, row)
        base = Path(snapshot["purelib"])
        filename = (
            canonical(row["name"]).replace("-", "_")
            + "-"
            + str(version(row["version"]))
            + "-py3-none-any.whl"
        )
        target = folder / filename
        with zipfile.ZipFile(
            folder / "original.zip", "w", zipfile.ZIP_DEFLATED
        ) as original:
            for relative in files:
                original.write(base / relative, relative)
        (folder / "original.zip").chmod(0o600)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative in files:
                if relative.endswith(
                    ("/RECORD", "/direct_url.json", "/REQUESTED", "/INSTALLER")
                ):
                    continue
                archive.write(base / relative, relative)
            metadata = next(
                (
                    p.rsplit("/", 1)[0]
                    for p in files
                    if p.endswith(".dist-info/METADATA")
                ),
                None,
            )
            if not metadata:
                raise ValueError("Installed wheel metadata unavailable")
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            for p in archive.namelist():
                value = archive.read(p)
                writer.writerow(
                    [
                        p,
                        "sha256="
                        + base64.urlsafe_b64encode(hashlib.sha256(value).digest())
                        .decode()
                        .rstrip("="),
                        len(value),
                    ]
                )
            writer.writerow([metadata + "/RECORD", "", ""])
            archive.writestr(metadata + "/RECORD", output.getvalue())
        target.chmod(0o600)
        wheel_info(
            target
        )  # Recovery must be admissible before any environment mutation.
        return filename

    def _pip(self, args, on_started):
        if self.guard():
            raise RuntimeError(
                "Global Stop/live-owner guard stopped package operation; inspect retained state"
            )
        bootstrap = "import sys;sys.prefix=sys.exec_prefix=sys.argv[1];import sysconfig;sys.path.append(sysconfig.get_path('purelib'));import runpy;sys.argv=['pip',*sys.argv[2:]];runpy.run_module('pip',run_name='__main__')"
        process = subprocess.Popen(
            [
                str(self.python),
                "-I",
                "-S",
                "-B",
                "-c",
                bootstrap,
                str(self.prefix),
                "--isolated",
                "--disable-pip-version-check",
                "--no-cache-dir",
                *args,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            on_started(process.pid)
        except Exception:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            else:
                process.wait()
            raise RuntimeError(
                "Installer launch record failed; owned installer stopped, outcome requires inspection"
            ) from None
        deadline = time.monotonic() + 90
        while process.poll() is None:
            if self.guard() or time.monotonic() > deadline:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise RuntimeError(
                    "Owned installer stopped; package outcome requires inspection"
                )
            time.sleep(0.05)
        if process.returncode:
            raise RuntimeError(
                "Installer did not acknowledge success; inspect without retry"
            )

    def change(
        self,
        oid,
        *,
        action,
        path=None,
        package=None,
        expected_fingerprint,
        expected_policy_revision,
        restore_from=None,
        expected_sha=None,
    ):
        if action not in {"install", "remove", "restore"}:
            raise ValueError("Unsupported package action")
        with self.locked():
            if self.guard():
                raise ValueError(
                    "Global Stop/live-owner guard prevents package changes"
                )
            if self.progress(oid):
                raise RuntimeError(
                    "Existing package progress must be inspected, never replayed"
                )
            info = wheel_info(path) if path else None
            if info and info["sha256"] != expected_sha:
                raise ValueError("Selected wheel digest differs from reviewed artifact")
            name = info["package"] if info else canonical(package or "")
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
                raise ValueError("Invalid distribution identity")
            snapshot = self.probe()
            old = self.admissible(snapshot, name, info)
            if self.fingerprint(snapshot, old) != expected_fingerprint:
                raise ValueError(
                    "Installed files changed; review before package changes"
                )
            if not old and action == "remove":
                raise ValueError("Plugin is not installed")
            folder = self.directory(oid)
            folder.mkdir(mode=0o700)
            previous = self.files(snapshot, old)
            backup = self.backup(snapshot, old, folder)
            if self.fingerprint(snapshot, old) != expected_fingerprint:
                raise ValueError(
                    "Installed files changed during recovery snapshot; no environment mutation"
                )
            if backup:
                with zipfile.ZipFile(folder / "original.zip") as archived:
                    if set(archived.namelist()) != set(previous) or any(
                        digest(archived.read(p)) != r["sha256"]
                        for p, r in previous.items()
                    ):
                        raise ValueError(
                            "Recovery snapshot changed during capture; no environment mutation"
                        )
            source = None
            if info:
                (folder / "selected").mkdir(mode=0o700)
                source = folder / "selected" / info["filename"]
                source.write_bytes(path.read_bytes())
                if digest(source.read_bytes()) != info["sha256"]:
                    raise ValueError(
                        "Selected artifact changed; no environment mutation"
                    )
            slots = {e["slot_id"] for e in (info["entries"] if info else [])}
            if old:
                slots.update(
                    startup.slot(e["group"], e["name"], old["name"])
                    for e in old["entries"]
                )
            original = self.restore_preview(restore_from)[1] if restore_from else None
            state = {
                "operation_id": oid,
                "created_at": time.time(),
                "action": "update" if action == "install" and old else action,
                "package": name,
                "version": info["version"] if info else None,
                "backup": backup,
                "source": source.relative_to(folder).as_posix() if source else None,
                "previous_files": previous,
                "expected_files": {
                    p: digest(b)
                    for p, b in info["files"].items()
                    if not p.endswith("/RECORD")
                }
                if info
                else {},
                "restore_from": restore_from,
                "expected_modes": {
                    p: v["mode"]
                    for p, v in (
                        original["previous_files"] if original else previous
                    ).items()
                },
                "phase": "prepared",
                "owner_pid": os.getpid(),
                "backup_sha256": digest((folder / backup).read_bytes())
                if backup
                else None,
                "original_sha256": digest((folder / "original.zip").read_bytes())
                if backup
                else None,
                "expected_policy_revision": expected_policy_revision,
            }
            if original:
                state["expected_files"] = {
                    p: r["sha256"] for p, r in original["previous_files"].items()
                }
            # Preserve intent/progress AND deny future loads before calling the package owner.
            with self.store._immediate() as conn:
                key = "plugin_startup:" + self.environment
                policy = startup._decode(
                    conn.execute(
                        "SELECT value FROM schema_meta WHERE key=?", (key,)
                    ).fetchone()
                )
                if policy["revision"] != expected_policy_revision:
                    raise ValueError("Startup policy changed; review package plan")
                policy = {
                    "revision": policy["revision"] + 1,
                    "entries": {
                        **policy["entries"],
                        **{slot: "disabled" for slot in slots},
                    },
                }
                conn.execute(
                    "INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(policy)),
                )
                conn.execute(
                    "INSERT INTO schema_meta(key,value) VALUES(?,?)",
                    (
                        "plugin_package:"
                        + self.environment
                        + ":"
                        + digest(oid.encode()),
                        json.dumps(state),
                    ),
                )
            state["phase"] = "installer_started"
            self.checkpoint(oid, state)

            def started(pid):
                state["installer_pid"] = pid
                self.checkpoint(oid, state)

            if source:
                self._pip(
                    [
                        "install",
                        "--no-index",
                        "--no-deps",
                        "--no-compile",
                        "--no-warn-script-location",
                        "--force-reinstall",
                        str(source),
                    ],
                    started,
                )
            else:
                self._pip(["uninstall", "--yes", name], started)
            if original:
                self._restore_original(original, restore_from, folder)
            else:
                base = Path(snapshot["purelib"])
                for relative, mode in state["expected_modes"].items():
                    target = base / relative
                    if relative in state["expected_files"] and target.is_file():
                        target.chmod(mode)
            state["phase"] = "installer_exited"
            self.checkpoint(oid, state)
            return self.inspect(oid, locked=True)

    def inspect(self, oid, *, locked=False):
        if not locked:
            existing = self.store.control_operation(oid)
            if existing and existing["receipt"]:
                return existing["receipt"]
            if not self.progress(oid):
                return None
            with self.locked():
                return self.inspect(oid, locked=True)
        state = self.progress(oid)
        existing = self.store.control_operation(oid)
        if existing and existing["receipt"]:
            return existing["receipt"]
        if not state:
            return None
        if state["phase"] == "installer_started":
            pid = state.get("installer_pid")
            if not pid:
                return {
                    "operation_id": oid,
                    "execution_unknown": True,
                    "error": "Installer identity was not durably recorded; no replay or automatic recovery",
                }
            try:
                os.kill(pid, 0)
                return {
                    "operation_id": oid,
                    "execution_unknown": True,
                    "error": "Recorded installer may still be active; no replay or automatic recovery",
                }
            except ProcessLookupError:
                pass
        snapshot = self.probe()
        row = self.current(snapshot, state["package"])
        files = self.files(snapshot, row)
        expected = state["expected_files"]
        matches = (
            row is None
            if not expected
            else row is not None
            and row["version"] == state["version"]
            and all(
                files.get(p, {}).get("sha256") == sha for p, sha in expected.items()
            )
        )
        if expected and any(
            files.get(p, {}).get("mode") != mode
            for p, mode in state.get("expected_modes", {}).items()
            if p in expected
        ):
            matches = False
        generated = {
            p
            for p in files
            if p.endswith(("/RECORD", "/INSTALLER", "/REQUESTED", "/direct_url.json"))
        }
        if expected and set(files) - set(expected) - generated:
            matches = False
        if not matches:
            return {
                "operation_id": oid,
                "execution_unknown": True,
                "phase": state["phase"],
                "backup_available": bool(state["backup"]),
                "error": "Installed files do not prove the requested state; no automatic replay/restore",
            }
        receipt = {
            "ok": True,
            "operation_id": oid,
            "http_status": 200,
            "result": {
                "domain": "plugin_package",
                "package": state["package"],
                "version": state["version"],
                "state": "removed" if not expected else "installed_disabled",
                "observed_state_reconciled": True,
                "receipt_scope": "observed_package_files_only",
                "activation_performed": False,
                "restart_required": True,
                "retained_code": "no_hot_unload_performed",
                "backup_available": bool(state["backup"]),
                "fingerprint": self.fingerprint(snapshot, row),
                "restored_from": state.get("restore_from"),
            },
        }
        self.store.finish_control_operation(oid, receipt)
        return receipt

    def restore_preview(self, original_oid):
        state = self.progress(original_oid)
        if not state or not state["backup"]:
            raise ValueError("No preserved package revision for this operation")
        folder = self.directory(original_oid)
        path = folder / state["backup"]
        if (
            path.name != state["backup"]
            or digest(path.read_bytes()) != state["backup_sha256"]
            or digest((folder / "original.zip").read_bytes())
            != state["original_sha256"]
        ):
            raise ValueError(
                "Preserved recovery artifacts changed; no restore permitted"
            )
        return path, state, self.preview(path)

    def restore(
        self, oid, original_oid, *, expected_fingerprint, expected_policy_revision
    ):
        path, _, _ = self.restore_preview(original_oid)
        return self.change(
            oid,
            action="restore",
            path=path,
            expected_fingerprint=expected_fingerprint,
            expected_policy_revision=expected_policy_revision,
            restore_from=original_oid,
            expected_sha=self.progress(original_oid)["backup_sha256"],
        )

    def _restore_original(self, original, original_oid, folder):
        archive_path = self.directory(original_oid) / "original.zip"
        if digest(archive_path.read_bytes()) != original["original_sha256"]:
            raise RuntimeError("Preserved original files changed; no restore replay")
        snapshot = self.probe()
        row = self.current(snapshot, original["package"])
        base = Path(snapshot["purelib"]).resolve()
        current = self.files(snapshot, row)
        with zipfile.ZipFile(archive_path) as archive:
            for relative, record in original["previous_files"].items():
                target = base / relative
                if not target.resolve().is_relative_to(base) or target.is_symlink():
                    raise RuntimeError("Recovery target escaped environment")
                content = archive.read(relative)
                if digest(content) != record["sha256"]:
                    raise RuntimeError("Preserved original content changed")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                target.chmod(record["mode"])
        for relative in set(current) - set(original["previous_files"]):
            if relative.endswith(
                ("/INSTALLER", "/REQUESTED", "/direct_url.json", "/RECORD")
            ):
                target = base / relative
                saved = folder / "installer-metadata" / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, saved)

    def history(self, before=None):
        cursor = None
        if before is not None:
            try:
                cursor = json.loads(
                    base64.urlsafe_b64decode(before + "=" * (-len(before) % 4))
                )
                if (
                    len(before) > 500
                    or not isinstance(cursor, list)
                    or len(cursor) != 2
                    or type(cursor[0]) not in {int, float}
                    or not __import__("math").isfinite(cursor[0])
                    or cursor[0] < 0
                    or not isinstance(cursor[1], str)
                    or not cursor[1].startswith(
                        "plugin_package:" + self.environment + ":"
                    )
                ):
                    raise ValueError()
            except Exception:
                raise ValueError("Invalid package history cursor") from None
        prefix = "plugin_package:" + self.environment + ":"
        conn = self.store._get_conn()
        try:
            query = "SELECT key,value FROM schema_meta WHERE key LIKE ?"
            args = [prefix + "%"]
            if cursor:
                query += " AND (json_extract(value,'$.created_at')<? OR (json_extract(value,'$.created_at')=? AND key<?))"
                args.extend([cursor[0], cursor[0], cursor[1]])
            rows = conn.execute(
                query
                + " ORDER BY json_extract(value,'$.created_at') DESC,key DESC LIMIT 31",
                args,
            ).fetchall()
        finally:
            conn.close()
        operations = []
        for row in rows[:30]:
            value = json.loads(row["value"])
            record = self.store.control_operation(value["operation_id"])
            operations.append(
                {
                    k: value[k]
                    for k in ("operation_id", "package", "version", "action", "phase")
                }
                | {
                    "backup_available": bool(value["backup"]),
                    "status": record["status"] if record else "unknown",
                    "compensated_by": value.get("compensated_by"),
                }
            )
        next_before = None
        if len(rows) > 30:
            last = rows[29]
            next_before = (
                base64.urlsafe_b64encode(
                    json.dumps(
                        [json.loads(last["value"])["created_at"], last["key"]]
                    ).encode()
                )
                .decode()
                .rstrip("=")
            )
        return {"operations": operations, "next_before": next_before}

    def removal_preview(self, name):
        name = canonical(name)
        snapshot = self.probe()
        row = self.admissible(snapshot, name)
        if row is None:
            raise ValueError("Existing extension package required")
        return {
            "package": name,
            "version": None,
            "installed_version": row["version"],
            "expected_fingerprint": self.fingerprint(snapshot, row),
            "policy_revision": startup.read(self.store, environment=self.environment)[
                "revision"
            ],
            "restart_required": True,
            "activation_performed": False,
            "entries": [],
            "requires": [],
            "provenance": "installed_distribution_metadata_not_publisher_verification",
        }

    def reserve_restore(self, oid, command, original_oid):
        """Explicit compensation only, never retry an unknown installer command.

        Allows a reviewed backup to supersede the latest package-only unknown
        when its recorded installer is gone. Original unknown is kept intact.
        """
        from jaeger_ai.core.gateway.session_store import input_fingerprint

        state = self.progress(original_oid)
        if not state or not state["backup"]:
            raise ValueError("No owned recoverable package snapshot")
        if state["phase"] == "installer_started":
            pid = state.get("installer_pid")
            if not pid:
                raise ValueError(
                    "Installer identity missing; explicit process inspection required before compensation"
                )
            try:
                os.kill(pid, 0)
                raise ValueError(
                    "Recorded installer may be active; no compensation admitted"
                )
            except ProcessLookupError:
                pass
        self.restore_preview(
            original_oid
        )  # validates original artifact/hash/owned current files
        fingerprint = input_fingerprint(json.dumps(command, sort_keys=True))
        with self.store._immediate() as conn:
            old = conn.execute(
                "SELECT fingerprint FROM control_operations WHERE operation_id=?",
                (oid,),
            ).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise ValueError("Operation identity belongs to another command")
                return False
            key = "control_scope:plugin-packages:" + self.environment
            pointer = conn.execute(
                "SELECT value FROM schema_meta WHERE key=?", (key,)
            ).fetchone()
            if not pointer or pointer[0] != original_oid:
                raise ValueError(
                    "Only the latest unresolved package operation may be compensated"
                )
            previous = conn.execute(
                "SELECT receipt_json FROM control_operations WHERE operation_id=?",
                (original_oid,),
            ).fetchone()
            if previous is None or previous[0] is not None:
                raise ValueError(
                    "Package operation already settled; use normal restore admission"
                )
            conn.execute(
                "INSERT INTO control_operations VALUES(?,?,'execution_unknown',NULL,?)",
                (oid, fingerprint, time.time()),
            )
            conn.execute("UPDATE schema_meta SET value=? WHERE key=?", (oid, key))
            state["compensated_by"] = oid
            conn.execute(
                "UPDATE schema_meta SET value=? WHERE key=?",
                (
                    json.dumps(state),
                    "plugin_package:"
                    + self.environment
                    + ":"
                    + digest(original_oid.encode()),
                ),
            )
        return True
