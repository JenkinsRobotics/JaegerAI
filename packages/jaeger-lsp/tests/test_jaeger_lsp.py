from __future__ import annotations

from jaeger_lsp import check_file_diagnostics


def test_python_diagnostics_catches_syntax_error(tmp_path):
    bad = tmp_path / "broken.py"
    bad.write_text("def oops(:\n    pass\n", encoding="utf-8")
    rep = check_file_diagnostics(bad)
    assert rep.ok is False
    assert rep.language == "python"
    assert len(rep.diagnostics) == 1
    assert rep.diagnostics[0].severity == "error"

    good = tmp_path / "clean.py"
    good.write_text("def ok(x: int) -> int:\n    return x + 1\n", encoding="utf-8")
    rep_ok = check_file_diagnostics(good)
    assert rep_ok.ok is True


def test_json_diagnostics_catches_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"a": 1,}', encoding="utf-8")
    rep = check_file_diagnostics(bad)
    assert rep.ok is False and rep.language == "json"

    good = tmp_path / "good.json"
    good.write_text('{"a": 1}\n', encoding="utf-8")
    assert check_file_diagnostics(good).ok is True
