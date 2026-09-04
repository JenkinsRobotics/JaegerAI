"""``jaeger delegate`` — drive the external agent runtimes from the terminal.

Jaeger has carried a full delegate stack for a while (registry, health
scoring, ranked routing, a durable run per task) and exposed exactly none
of it outside ``list_delegates`` over MCP. That left the operator unable to
answer "which of my agent CLIs can Jaeger actually reach right now?"
without writing Python, and unable to run a task through one at all.

  jaeger delegate list [--json]        every runtime, probed live
  jaeger delegate run <prompt>         best-ranked delegate runs the task
  jaeger delegate run --chain <prompt> try each in rank order until one wins
  jaeger delegate moa <prompt>         ask several at once and compare answers

``--chain`` is the failover path: probes only tell you a binary exists, so
an installed-but-unauthenticated CLI still passes eligibility and then
fails on first contact. The chain keeps going; a single delegate does not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from jaeger_ai.cli import _common as c

_SENSITIVITIES = ("public", "personal", "sensitive", "private", "secret")


def _cmd_delegate_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger delegate <verb> [args...]\n"
            "\n"
            "verbs:\n"
            "  list [--json]                    probe every runtime: available, capabilities\n"
            "  run [opts] <prompt>              run a task on the best-ranked delegate\n"
            "  moa [opts] <prompt>              ask the top N in parallel, print every answer\n"
            "\n"
            "run options:\n"
            "  --chain                          on failure, fall through the ranked list\n"
            "  --to NAME                        force one runtime (claude, hermes, openclaw, ...)\n"
            "  --capability CAP                 require a capability (repeatable)\n"
            "  --sensitivity S                  " + "|".join(_SENSITIVITIES) + " (default: personal)\n"
            "                                   private/secret force a LOCAL runtime\n"
            "  --timeout SECONDS                default 300\n"
            "\n"
            "\n"
            "moa options:  -n COUNT (default 3), --require K completions (default 1)\n"
            "\n"
            "  e.g. jaeger delegate run --chain 'summarise the repo README'\n"
            "       jaeger delegate moa -n 3 'is this regex correct: ^\\d{3}-\\d{4}$'\n",
            file=sys.stderr,
        )
        return 0 if argv else 2

    verb, rest = argv[0], argv[1:]
    if verb == "list":
        return _delegate_list(rest)
    if verb == "run":
        return _delegate_run(rest)
    if verb == "moa":
        return _delegate_moa(rest)
    print(f"jaeger delegate: unknown verb {verb!r}", file=sys.stderr)
    return 2


def _registry():
    from jaeger_agent.delegates import get_delegate_registry, register_builtin_delegates

    register_builtin_delegates()
    return get_delegate_registry()


def _delegate_list(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="jaeger delegate list", add_help=False)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    registry = _registry()
    runtimes = registry.list()

    async def probe_all():
        return await asyncio.gather(
            *(rt.probe() for rt in runtimes), return_exceptions=True
        )

    statuses = asyncio.run(probe_all())
    rows = []
    for rt, st in zip(runtimes, statuses, strict=True):
        if isinstance(st, BaseException):
            rows.append({"runtime": rt.runtime_id, "available": False,
                         "detail": f"probe failed: {type(st).__name__}",
                         "capabilities": [], "local": None})
            continue
        rows.append({
            "runtime": rt.runtime_id, "available": bool(st.available),
            "detail": st.detail or "", "capabilities": sorted(st.capabilities),
            "local": bool(st.local),
        })
    rows.sort(key=lambda r: (not r["available"], r["runtime"]))

    if args.json:
        print(json.dumps({"delegates": rows, "count": len(rows)}, indent=2))
        return 0

    ready = sum(1 for r in rows if r["available"])
    print(c.bold(f"\n  Delegates — {ready}/{len(rows)} available\n"))
    for r in rows:
        mark = c.green("✓") if r["available"] else c.red("✗")
        where = c.dim("local") if r["local"] else c.dim("remote")
        print(f"  {mark} {c.bold(r['runtime']):<20} {where}  {r['detail']}")
        if r["capabilities"]:
            print(f"      {c.dim(', '.join(r['capabilities']))}")
    print()
    return 0


def _delegate_run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="jaeger delegate run", add_help=False)
    ap.add_argument("--chain", action="store_true")
    ap.add_argument("--to")
    ap.add_argument("--capability", action="append", default=[])
    ap.add_argument("--sensitivity", default="personal", choices=_SENSITIVITIES)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("prompt", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("jaeger delegate run: a prompt is required", file=sys.stderr)
        return 2

    from jaeger_agent.cognition.runs import InMemoryRunStore
    from jaeger_agent.delegates import (
        AllDelegatesFailed,
        DelegateExecutor,
        DelegateRequest,
    )
    from jaeger_agent.delegates.routing import DelegateRouter, NoEligibleDelegate

    registry = _registry()
    runs = InMemoryRunStore()
    run = runs.create("cli-delegate", provider="cli")
    executor = DelegateExecutor(registry, runs)
    caps = frozenset(args.capability)

    request = DelegateRequest(
        task_id=run.id,
        prompt=prompt,
        required_capabilities=caps,
        sensitivity=args.sensitivity,  # type: ignore[arg-type]
        timeout_seconds=args.timeout,
        idempotency_key=uuid.uuid4().hex,
    )

    async def go():
        if args.to and not args.chain:
            return await executor.execute(args.to, request)
        router = DelegateRouter(registry)
        routes = await router.rank(
            required_capabilities=caps,
            sensitivity=args.sensitivity,
            preferred=args.to,
        )
        if not routes:
            raise NoEligibleDelegate(
                "no available delegate satisfies locality and capability requirements"
            )
        order = [r.runtime_id for r in routes]
        if not args.chain:
            return await executor.execute(order[0], request)
        print(c.dim(f"  chain: {' → '.join(order)}"), file=sys.stderr)
        return await executor.execute_with_fallback(
            order, request,
            on_failover=lambda rid, exc: print(
                c.yellow(f"  ↪ {rid} failed ({type(exc).__name__}); trying next"),
                file=sys.stderr),
        )

    try:
        result = asyncio.run(go())
    except NoEligibleDelegate as exc:
        print(c.red(f"  no eligible delegate: {exc}"), file=sys.stderr)
        return 1
    except AllDelegatesFailed as exc:
        print(c.red(f"  {exc}"), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — surface the runtime's own message
        print(c.red(f"  delegate failed: {type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1

    print(result.summary or "")
    return 0 if result.status == "completed" else 1


def _delegate_moa(argv: list[str]) -> int:
    """Mixture of Agents: fan the same prompt out and show every answer.

    Deliberately does NOT merge the responses into one. Picking a winner
    needs a judge, and a judge that is itself one of the agents just
    launders that agent's opinion into an apparent consensus. Showing the
    spread lets the operator see agreement — or disagreement, which is the
    part worth knowing.
    """
    ap = argparse.ArgumentParser(prog="jaeger delegate moa", add_help=False)
    ap.add_argument("-n", "--count", type=int, default=3)
    ap.add_argument("--require", type=int, default=1)
    ap.add_argument("--capability", action="append", default=[])
    ap.add_argument("--sensitivity", default="personal", choices=_SENSITIVITIES)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("prompt", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("jaeger delegate moa: a prompt is required", file=sys.stderr)
        return 2

    from jaeger_agent.cognition.runs import InMemoryRunStore
    from jaeger_agent.delegates import (
        AllDelegatesFailed,
        DelegateExecutor,
        DelegateRequest,
    )
    from jaeger_agent.delegates.routing import DelegateRouter, NoEligibleDelegate

    registry = _registry()
    runs = InMemoryRunStore()
    executor = DelegateExecutor(registry, runs)
    caps = frozenset(args.capability)
    request = DelegateRequest(
        task_id="pending",  # execute_ensemble gives each delegate its own run
        prompt=prompt,
        required_capabilities=caps,
        sensitivity=args.sensitivity,  # type: ignore[arg-type]
        timeout_seconds=args.timeout,
        idempotency_key=uuid.uuid4().hex,
    )

    async def go():
        routes = await DelegateRouter(registry).rank(
            required_capabilities=caps, sensitivity=args.sensitivity
        )
        if not routes:
            raise NoEligibleDelegate("no available delegate satisfies the requirements")
        chosen = [r.runtime_id for r in routes][: max(1, args.count)]
        print(c.dim(f"  asking: {', '.join(chosen)}"), file=sys.stderr)
        return await executor.execute_ensemble(chosen, request, require=args.require)

    try:
        outcomes = asyncio.run(go())
    except NoEligibleDelegate as exc:
        print(c.red(f"  {exc}"), file=sys.stderr)
        return 1
    except AllDelegatesFailed as exc:
        print(c.red(f"  {exc}"), file=sys.stderr)
        return 1

    ok = 0
    for outcome in outcomes:
        if outcome.result is not None and outcome.result.status == "completed":
            ok += 1
            print(f"\n{c.green('✓')} {c.bold(outcome.runtime_id)}")
            print((outcome.result.summary or "").strip())
        else:
            why = outcome.error or (outcome.result.status if outcome.result else "unknown")
            print(f"\n{c.red('✗')} {c.bold(outcome.runtime_id)} {c.dim(why)}")
    print(c.dim(f"\n  {ok}/{len(outcomes)} answered"))
    return 0 if ok >= args.require else 1
