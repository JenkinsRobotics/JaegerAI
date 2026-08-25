"""``jaeger doctor`` must not report green for what it could not determine.

Field blocker #8: on a real machine doctor printed

    ✓ full_disk_access      could not determine
    All dependencies present — the Jaeger is fully operational.

Both lines are wrong in the same way. ``Check.ok`` is a bool, so a probe
that FAILED TO ANSWER had to pick a side, and it picked green — the ✓ and
the summary then actively assert something the tool does not know. An
operator reading that has no signal to go grant the permission.

A probe has three outcomes, not two: pass, fail, and "could not tell".
"""

from __future__ import annotations

from jaeger_ai.core.runtime.preflight import Check, format_report, missing


def _green(name="git"):
    return Check(name=name, category="system", ok=True, detail="present")


def _unknown(name="full_disk_access"):
    return Check(name=name, category="system", ok=True,
                 detail="could not determine", unknown=True)


def _failed(name="kokoro"):
    return Check(name=name, category="voice", ok=False,
                 detail="missing", fix="pip install kokoro")


def test_unknown_is_not_marked_pass():
    report = format_report([_unknown()])
    row = next(ln for ln in report.splitlines() if "full_disk_access" in ln)
    assert "✓" not in row, "an undetermined probe is rendered as a pass"
    assert "?" in row


def test_summary_does_not_claim_fully_operational_when_undetermined():
    report = format_report([_green(), _unknown()])
    assert "fully operational" not in report, \
        "doctor claimed full health while a probe was undetermined"
    assert "could not" in report.lower() or "undetermined" in report.lower()


def test_all_green_still_reports_fully_operational():
    """The honest case must keep working — no false alarms."""
    assert "fully operational" in format_report([_green(), _green("osascript")])


def test_unknown_is_not_counted_as_a_failure():
    """Undetermined is not broken: it must not land in the fix list."""
    checks = [_green(), _unknown(), _failed()]
    bad = missing(checks)
    assert [c.name for c in bad] == ["kokoro"]


def test_real_fda_probe_marks_itself_unknown_when_it_cannot_tell(monkeypatch):
    """The actual check, not a hand-built one."""
    import jaeger_ai.core.diagnostics.doctor as doc

    monkeypatch.setattr(doc, "_probe_fda", lambda: None)
    check = doc._fda_check()
    if check is None:
        return                       # non-macOS: nothing to assert
    assert check.unknown is True
    assert "could not determine" in check.detail
