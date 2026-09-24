#!/usr/bin/env python3
"""Import every Codex skill into the repo as first-party playbook skills.

Sources (all read from the operator's local Codex install, never modified):
  * ``~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/skills/**/SKILL.md``
  * ``~/.codex/vendor_imports/skills/skills/**/SKILL.md``   (curated catalog)

Destination: ``packages/jaeger-agent/jaeger_agent/skills/codex/<source>/<skill>/``.
``playbook_skills.discover_playbooks`` finds them by ``rglob("SKILL.md")`` and,
because they are not listed in ``skills/catalog.yaml``, exposes them as
``optional`` (searchable and explicitly loadable, not injected into every
routing prompt). Each imported skill folder gets a ``.provenance.json`` with
its source, version, and license so attribution survives the copy.

Re-running is idempotent: destination skill folders are rewritten from source.

    python dev/scripts/import_codex_skills.py --dry-run
    python dev/scripts/import_codex_skills.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEST_ROOT = REPO / "packages" / "jaeger-agent" / "jaeger_agent" / "skills" / "codex"
CODEX = Path.home() / ".codex"
SKIP_DIRS = {"node_modules", ".git", "__pycache__"}


def _version_key(p: Path) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.\-]", p.name))


def _license_of(plugin_root: Path) -> tuple[str, str | None]:
    """(spdx-ish label, path of the LICENSE file relative to the plugin) or ('none', None)."""
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.TXT"):
        f = plugin_root / name
        if f.is_file():
            head = " ".join(f.read_text(errors="replace").split()[:12]).lower()
            if "apache license" in head:
                return "Apache-2.0", name
            if "mit license" in head:
                return "MIT", name
            return "see-license-file", name
    return "none-declared", None


def _sources() -> list[tuple[str, Path, Path]]:
    """(source-label, plugin_root, skills_root) for every skill-bearing plugin."""
    out: list[tuple[str, Path, Path]] = []
    cache = CODEX / "plugins" / "cache"
    for market in sorted(p for p in cache.iterdir() if p.is_dir()):
        for plugin in sorted(p for p in market.iterdir() if p.is_dir() and not p.name.startswith(".")):
            versions = sorted((v for v in plugin.iterdir() if v.is_dir()), key=_version_key)
            if not versions:
                continue
            root = versions[-1]  # newest installed version only
            skills = root / "skills"
            if skills.is_dir():
                out.append((f"{market.name}--{plugin.name}", root, skills))
    vendor = CODEX / "vendor_imports" / "skills" / "skills"
    if vendor.is_dir():
        out.append(("openai-curated", vendor.parent, vendor))
    return out


def _skill_dirs(skills_root: Path) -> list[Path]:
    found = []
    for md in sorted(skills_root.rglob("SKILL.md")):
        if any(part in SKIP_DIRS for part in md.parts):
            continue
        found.append(md.parent)
    return found


def _frontmatter_name(md: Path) -> str:
    text = md.read_text(errors="replace")
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("name:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    return md.parent.name


def _existing_names() -> set[str]:
    """Names of skills already shipped in the repo (everything outside codex/)."""
    names: set[str] = set()
    for md in DEST_ROOT.parent.rglob("SKILL.md"):
        if DEST_ROOT in md.parents:
            continue
        names.add(_frontmatter_name(md))
    return names


def _rename_frontmatter(md: Path, new_name: str) -> None:
    """Rewrite only the ``name:`` line so a colliding skill stays loadable."""
    text = md.read_text(errors="replace")
    m = re.match(r"(---\s*\n)(.*?)(\n---)", text, re.S)
    if not m:
        return
    lines = m.group(2).splitlines()
    for i, line in enumerate(lines):
        if line.startswith("name:"):
            lines[i] = f'name: "{new_name}"'
            break
    else:
        lines.insert(0, f'name: "{new_name}"')
    md.write_text(m.group(1) + "\n".join(lines) + m.group(3) + text[m.end():])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    plan = []  # (source, skill_dir, dest, name, license, plugin_root)
    for label, plugin_root, skills_root in _sources():
        lic, lic_file = _license_of(plugin_root)
        for sd in _skill_dirs(skills_root):
            rel = sd.relative_to(skills_root)
            dest = DEST_ROOT / label / "__".join(rel.parts)
            plan.append((label, sd, dest, _frontmatter_name(sd / "SKILL.md"), lic, lic_file, plugin_root))

    by_name: dict[str, list[str]] = {}
    for label, sd, dest, name, *_ in plan:
        by_name.setdefault(name, []).append(label)
    existing = _existing_names()
    # A name that repeats across sources, or that a shipped skill already uses,
    # would silently shadow (discovery keys by name). Namespace those as
    # ``<plugin>:<name>`` — the same convention Codex uses.
    dup = {n: s for n, s in by_name.items() if len(s) > 1 or n in existing}

    print(f"skills found: {len(plan)}  sources: {len({p[0] for p in plan})}")
    lic_count: dict[str, int] = {}
    for p in plan:
        lic_count[p[4]] = lic_count.get(p[4], 0) + 1
    print("licenses:", lic_count)
    print(f"colliding names to namespace: {len(dup)}")
    for n, s in sorted(dup.items()):
        print(f"  {n}: {s}")
    if args.dry_run:
        return 0

    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    seen_labels = set()
    for label, sd, dest, name, lic, lic_file, plugin_root in plan:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(sd, dest, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        final_name = name
        if name in dup:
            final_name = f"{label.split('--')[-1]}:{name}"
            _rename_frontmatter(dest / "SKILL.md", final_name)
        digest = hashlib.sha256((sd / "SKILL.md").read_bytes()).hexdigest()
        (dest / ".provenance.json").write_text(json.dumps({
            "name": final_name,
            "original_name": name,
            "source": label,
            "origin_path": str(sd.relative_to(CODEX)),
            "plugin_version": plugin_root.name,
            "license": lic,
            "license_file": f"../LICENSE.{label}" if lic_file else None,
            "skill_md_sha256": digest,
        }, indent=2) + "\n")
        if label not in seen_labels and lic_file:
            shutil.copyfile(plugin_root / lic_file, DEST_ROOT / label / f"LICENSE.{label}")
        seen_labels.add(label)
    print(f"imported {len(plan)} skills into {DEST_ROOT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
