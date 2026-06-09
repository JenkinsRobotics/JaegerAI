"""Migration runner.

Walks `jaeger_os/migrations/` for modules named
`v<FROM>_to_v<TO>.py`, sorts them by version order, and applies any whose
FROM matches the instance's current manifest schema_version. The instance's
manifest is updated after each successful migration; on failure the runner
raises and the agent refuses to start.

Version comparison is naive lexical for simplicity (`1.0.0` < `1.1.0` <
`1.2.0` works; pre-release tags would break it, which is fine — we don't
ship pre-releases from migrations).
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path
from typing import Any

from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.core.instance.schemas import SCHEMA_VERSION, Manifest, dump_json, load_json


# core/instance/ is two levels deeper than the framework package; migrations/ sits at the framework root, so reach two levels up.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"
_FILENAME_RE = re.compile(r"^v(?P<from>[\d_]+)_to_v(?P<to>[\d_]+)\.py$")


def _ver_to_tuple(s: str) -> tuple[int, ...]:
    """`1_0_0` (filename style) or `1.0.0` (semver style) → (1, 0, 0)."""
    return tuple(int(p) for p in re.split(r"[._]", s))


def _ver_tuple_to_dot(t: tuple[int, ...]) -> str:
    return ".".join(str(p) for p in t)


def discover_migrations() -> list[dict[str, Any]]:
    """Return migrations sorted by (from_ver, to_ver). Each entry is
    {name, from_ver, to_ver, path}."""
    if not MIGRATIONS_DIR.exists():
        return []
    found: list[dict[str, Any]] = []
    for p in MIGRATIONS_DIR.iterdir():
        if not p.is_file():
            continue
        m = _FILENAME_RE.match(p.name)
        if not m:
            continue
        from_ver = _ver_to_tuple(m.group("from"))
        to_ver = _ver_to_tuple(m.group("to"))
        found.append({
            "name": p.stem,
            "from_ver": from_ver,
            "to_ver": to_ver,
            "from_str": _ver_tuple_to_dot(from_ver),
            "to_str": _ver_tuple_to_dot(to_ver),
            "path": p,
        })
    return sorted(found, key=lambda r: (r["from_ver"], r["to_ver"]))


def _load(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"_jaeger_migration_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import migration {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "migrate"):
        raise RuntimeError(f"migration {path.stem!r} has no `migrate(layout)` callable")
    return mod


def run_pending_migrations(layout: InstanceLayout) -> list[str]:
    """Apply migrations until the instance manifest matches SCHEMA_VERSION.

    Returns the list of applied migration names. Raises on any failure
    (the agent loop should treat that as refuse-to-start)."""
    manifest = load_json(layout.manifest_path, Manifest)
    current = manifest.schema_version
    target = SCHEMA_VERSION
    if current == target:
        return []

    current_tup = _ver_to_tuple(current.replace(".", "_"))
    target_tup = _ver_to_tuple(target.replace(".", "_"))
    if current_tup > target_tup:
        raise RuntimeError(
            f"instance is at core {current!r} but installed core is {target!r} — "
            "downgrade migrations are not supported. Restore the instance from backup."
        )

    plan: list[dict[str, Any]] = []
    cur = current_tup
    for mig in discover_migrations():
        if mig["from_ver"] == cur:
            plan.append(mig)
            cur = mig["to_ver"]
            if cur == target_tup:
                break

    if cur != target_tup:
        raise RuntimeError(
            f"no migration path from core {current!r} to {target!r} "
            f"(stuck at {_ver_tuple_to_dot(cur)}); add the missing migration script."
        )

    applied: list[str] = []
    for mig in plan:
        print(f"[jaeger-migrate] {mig['name']}: {mig['from_str']} → {mig['to_str']}", flush=True)
        mod = _load(mig["path"])
        mod.migrate(layout)
        manifest = manifest.model_copy(update={"schema_version": mig["to_str"]})
        dump_json(layout.manifest_path, manifest)
        applied.append(mig["name"])

    return applied
