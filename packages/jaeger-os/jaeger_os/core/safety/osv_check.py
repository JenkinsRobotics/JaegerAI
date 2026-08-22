"""OSV malware check for package installs (audit gap #12).

Before pip-installing a package, query the OSV database
(https://osv.dev) for ``MAL-*`` advisories — known-malicious packages:
typosquats, dependency-confusion drops, supply-chain worms. A human
approving an ``install_package`` confirmation can't realistically vet a
package name; this catches the ones the database already knows are bad.

Fail-open: any network / parse error allows the install. OSV being
unreachable must never break a legitimate package install — the check
is a safety net, not a hard dependency.
"""

from __future__ import annotations

import json
import urllib.request

_OSV_ENDPOINT = "https://api.osv.dev/v1/query"
_TIMEOUT = 6.0

# pip requirement separators — everything up to the first one is the
# bare package name (``httpx>=0.27`` → ``httpx``).
_SEPARATORS = ("===", "==", ">=", "<=", "~=", "!=", ">", "<",
               "[", " ", ";", "@")


def pypi_base_name(spec: str) -> str:
    """The bare package name from a pip requirement spec."""
    name = (spec or "").strip()
    for sep in _SEPARATORS:
        name = name.split(sep)[0]
    return name.strip().lower()


def check_pypi_package(spec: str) -> str | None:
    """Check a pip requirement against OSV's malware advisories.

    Returns a human-readable warning string when the package has a
    known ``MAL-*`` advisory; ``None`` when it is clean, unknown, or the
    check could not run (fail-open)."""
    name = pypi_base_name(spec)
    if not name:
        return None
    try:
        payload = json.dumps(
            {"package": {"name": name, "ecosystem": "PyPI"}}
        ).encode("utf-8")
        req = urllib.request.Request(
            _OSV_ENDPOINT, data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "jaeger-os-osv-check/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
    except Exception:  # noqa: BLE001 — fail-open on any error
        return None
    malware = [
        v for v in (data.get("vulns") or [])
        if str(v.get("id", "")).startswith("MAL-")
    ]
    if not malware:
        return None
    ids = ", ".join(str(v.get("id", "?")) for v in malware[:3])
    return (
        f"package {name!r} has {len(malware)} known malware advisory(ies) "
        f"in the OSV database ({ids}). This is a known-malicious package — "
        f"refusing to install it."
    )
