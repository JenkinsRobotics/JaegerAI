"""Memory dreaming CLI verbs.

Commands:
    jaeger memory dream          # Run a dreaming cycle now
    jaeger memory dream status   # Show dreaming status
    jaeger memory dream schedule # Show/update schedule
"""

from __future__ import annotations

from typing import Any
import argparse
import asyncio
import json
import sys

from jaeger_ai.core.memory.dreaming import DreamingEngine, get_dreaming_status


def cmd_memory_dream(args: argparse.Namespace) -> int:
    """Run a memory dreaming cycle."""
    from pathlib import Path
    
    # Get memory subsystem
    try:
        from jaeger_ai.core.entity.memory import MemorySubsystem
        memory = MemorySubsystem()
    except Exception as e:
        print(f"Error: Could not initialize memory subsystem: {e}", file=sys.stderr)
        print("Hint: Make sure you have an active instance", file=sys.stderr)
        return 1
    
    async def run():
        engine = DreamingEngine(memory)
        
        lookback = getattr(args, "hours", 24)
        print(f"🔮 Starting memory dreaming cycle (looking back {lookback}h)...")
        print("")
        
        report = await engine.run_dream_cycle(since_hours=lookback)
        
        print(f"✅ Dream cycle complete!")
        print(f"   Duration: {report.duration_seconds:.1f}s")
        print(f"   Candidates processed: {report.candidates_processed}")
        print(f"   Memories promoted: {report.candidates_promoted}")
        print(f"   Patterns found: {len(report.patterns_found)}")
        
        if report.patterns_found:
            print("")
            print("   Top patterns:")
            for pattern in report.patterns_found[:5]:
                print(f"     • {pattern}")
        
        if report.promoted_memories:
            print("")
            print("   Promoted memories:")
            for memory in report.promoted_memories[:5]:
                preview = memory.content[:80] + "..." if len(memory.content) > 80 else memory.content
                print(f"     • [{memory.score:.2f}] {preview}")
        
        if args.json:
            print("")
            print(json.dumps(report.to_dict(), indent=2))
        
        return 0
    
    try:
        return asyncio.run(run())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_memory_dream_status(args: argparse.Namespace) -> int:
    """Show dreaming system status."""
    from pathlib import Path
    
    status = get_dreaming_status()
    
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print("🔮 Memory Dreaming Status")
        print("=" * 40)
        print(f"  State directory:   {status['state_dir']}")
        print(f"  Tracked memories:  {status['tracked_memories']}")
        print(f"  Dream cycles run:  {status['total_dream_cycles']}")
        print(f"  Last dream cycle:  {status['last_dream_cycle'] or 'never'}")
        print("")
        print("To run a dream cycle now:")
        print("  jaeger memory dream")
    
    return 0


def cmd_memory_dream_schedule(args: argparse.Namespace) -> int:
    """Show or update dreaming schedule."""
    print("🔮 Memory Dreaming Schedule")
    print("=" * 40)
    print("")
    print("Dreaming runs automatically via the scheduler when idle.")
    print("")
    print("Default schedule: Daily at 3:00 AM (when system is idle)")
    print("")
    print("To run manually:")
    print("  jaeger memory dream")
    print("")
    print("To run with custom lookback:")
    print("  jaeger memory dream --hours 48")
    print("")
    print("Dream journal location:")
    print("  ~/.jaeger/memory/dreams/DREAMS.md")
    
    return 0


def register(subparsers) -> None:
    """Register memory dreaming commands."""
    # jaeger memory dream
    dream_parser = subparsers.add_parser(
        "dream",
        help="Run memory consolidation (dreaming)",
    )
    dream_parser.add_argument(
        "--hours", type=int, default=24,
        help="Hours to look back for memories (default: 24)"
    )
    dream_parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON"
    )
    dream_parser.set_defaults(func=cmd_memory_dream)
    
    # jaeger memory dream status
    status_parser = subparsers.add_parser(
        "dream-status",
        help="Show dreaming system status",
    )
    status_parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON"
    )
    status_parser.set_defaults(func=cmd_memory_dream_status)
    
    # jaeger memory dream schedule
    schedule_parser = subparsers.add_parser(
        "dream-schedule",
        help="Show dreaming schedule",
    )
    schedule_parser.set_defaults(func=cmd_memory_dream_schedule)
