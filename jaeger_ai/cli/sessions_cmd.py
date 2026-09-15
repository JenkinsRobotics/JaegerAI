"""``jaeger sessions`` — see, repair and prune conversations per framework.

Conversations live in three databases written by three different things, and
they disagreed about whose conversation each one was: the Gateway stamped
``jaeger`` on everything by default, and the Hermes agent left its profile
column empty because it does not know Jaeger has profiles. The result was a
sidebar that could not answer "show me Hermes' conversations".

Three subcommands:

``list``    what each framework has, split browser vs terminal
``repair``  backfill each store's profile column from the session id
``prune``   delete stale empty conversations

``repair`` and ``prune`` both preview by default and need ``--apply`` to write.
"""

from __future__ import annotations

from typing import Any

from jaeger_ai.contract.frameworks import FRAMEWORKS, display_name
from jaeger_ai.features.session_search.endpoints import (
    all_sessions,
    by_profile,
    endpoints,
    prune_sessions,
    repair_attribution,
)


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "sessions",
        help="list, repair and prune conversations per framework",
    )
    sub = parser.add_subparsers(dest="_sessions_cmd")

    listing = sub.add_parser("list", help="conversations per framework")
    listing.add_argument("--profile", help="only this framework (hermes, jaeger, …)")
    listing.add_argument("--limit", type=int, default=5,
                         help="conversations to show per bucket (default 5)")
    listing.set_defaults(_handler=run_list)

    repair = sub.add_parser(
        "repair", help="backfill profile attribution from session ids")
    repair.add_argument("--apply", action="store_true",
                        help="write the changes (default: preview only)")
    repair.set_defaults(_handler=run_repair)

    prune = sub.add_parser("prune", help="delete stale empty conversations")
    prune.add_argument("--older-than", type=float, default=30.0,
                       metavar="DAYS", help="age cutoff in days (default 30)")
    prune.add_argument("--min-messages", type=int, default=1, metavar="N",
                       help="keep anything with at least N messages (default 1)")
    prune.add_argument("--apply", action="store_true",
                       help="delete them (default: preview only)")
    prune.set_defaults(_handler=run_prune)

    parser.set_defaults(_handler=run_list)


def run_list(args: Any) -> int:
    wanted = (args.profile or "").strip().lower() or None
    limit = max(0, int(getattr(args, "limit", 5) or 0))
    buckets = by_profile()

    print(f"{len(all_sessions())} conversations across "
          f"{sum(1 for e in endpoints() if e.exists())} stores\n")

    order = [f.runtime for f in FRAMEWORKS] + ["unattributed"]
    for runtime in order:
        if wanted and runtime != wanted:
            continue
        group = buckets.get(runtime)
        if group is None:
            continue
        total = sum(len(v) for v in group.values())
        label = display_name(runtime) if runtime != "unattributed" else "Unattributed"
        if not total:
            print(f"── {label}\n     no conversations yet\n")
            continue
        print(f"── {label}  ({total})")
        for bucket, heading in (("browser", "WebUI"),
                                ("terminal", "Terminal"),
                                ("other", "Other surface")):
            rows = group.get(bucket, [])
            if not rows:
                continue
            print(f"     {heading} ({len(rows)})")
            for row in rows[:limit]:
                title = row.title or "(untitled)"
                count = "  ?" if row.message_count is None else f"{row.message_count:>3}"
                print(f"       {row.session_id[:38]:<40} {count} msg  "
                      f"{row.age_days:>5.0f}d  {title[:40]}")
            if len(rows) > limit:
                print(f"       … {len(rows) - limit} more")
        print()

    if wanted and wanted not in order:
        known = ", ".join(f.runtime for f in FRAMEWORKS)
        print(f"unknown profile {wanted!r}; known frameworks are {known}")
        return 1
    return 0


def run_repair(args: Any) -> int:
    report = repair_attribution(dry_run=not args.apply)
    total = sum(report["updated"].values())
    verb = "would set" if report["dry_run"] else "set"
    for store, count in sorted(report["updated"].items()):
        print(f"  {store:<12} {verb} a profile on {count} row(s)")
    if not total:
        print("  every row already carries a profile — nothing to repair")
    elif report["dry_run"]:
        print(f"\n{total} row(s) would be updated. Re-run with --apply to write.")
    else:
        print(f"\n{total} row(s) updated.")
    return 0


def run_prune(args: Any) -> int:
    try:
        report = prune_sessions(
            args.older_than,
            min_messages=args.min_messages,
            dry_run=not args.apply,
        )
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    for store, why in sorted(report.get("skipped", {}).items()):
        print(f"  {store:<12} skipped — {why}")
    doomed = {k: v for k, v in report["removed"].items() if v}
    total = sum(len(v) for v in doomed.values())
    if not total:
        print(f"nothing older than {args.older_than:g} days with fewer than "
              f"{args.min_messages} message(s) — nothing to prune")
        return 0

    verb = "would delete" if report["dry_run"] else "deleted"
    for store, ids in sorted(doomed.items()):
        print(f"  {store:<12} {verb} {len(ids)}")
        for sid in ids[:5]:
            print(f"       {sid}")
        if len(ids) > 5:
            print(f"       … {len(ids) - 5} more")
    if report["dry_run"]:
        print(f"\n{total} conversation(s) would be deleted. "
              f"Re-run with --apply to remove them.")
    else:
        print(f"\n{total} conversation(s) deleted.")
    return 0
