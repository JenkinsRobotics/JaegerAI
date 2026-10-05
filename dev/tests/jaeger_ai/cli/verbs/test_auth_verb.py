"""``jaeger auth`` never prints token values and creates only missing tokens."""

from __future__ import annotations

import json
import os

from jaeger_ai.cli.verbs.auth_verb import _cmd_auth_argv
from jaeger_ai.core.gateway import caller_auth


def _fresh_store(tmp_path, monkeypatch):
    store = tmp_path / "tokens"
    store.mkdir(mode=0o700)
    monkeypatch.setenv(caller_auth.TOKEN_DIR_ENV, str(store))
    return store


def test_init_creates_every_caller_token_without_printing_values(tmp_path, monkeypatch, capsys):
    store = _fresh_store(tmp_path, monkeypatch)
    assert _cmd_auth_argv(["init", "--json"]) == 0
    out = capsys.readouterr().out
    result = json.loads(out)["callers"]
    assert result == {name: "created" for name in caller_auth.CALLERS}
    for name in caller_auth.CALLERS:
        value = caller_auth.read_token(name)
        assert value and value not in out
        assert oct(os.stat(store / f"{name}.token").st_mode & 0o777) == "0o600"
    tokens = {caller_auth.read_token(name) for name in caller_auth.CALLERS}
    assert len(tokens) == len(caller_auth.CALLERS)  # one distinct token per caller


def test_init_keeps_existing_tokens(tmp_path, monkeypatch, capsys):
    _fresh_store(tmp_path, monkeypatch)
    _cmd_auth_argv(["init"])
    before = caller_auth.read_token("menubar")
    capsys.readouterr()
    assert _cmd_auth_argv(["init", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)["callers"]
    assert set(result.values()) == {"existing"}
    assert caller_auth.read_token("menubar") == before


def test_status_reports_presence_only(tmp_path, monkeypatch, capsys):
    _fresh_store(tmp_path, monkeypatch)
    assert _cmd_auth_argv(["status"]) == 1  # nothing created yet
    assert "MISSING" in capsys.readouterr().out
    _cmd_auth_argv(["init"])
    capsys.readouterr()
    assert _cmd_auth_argv(["status", "--json"]) == 0
    out = capsys.readouterr().out
    rows = json.loads(out)["callers"]
    assert all(row["token"] is True for row in rows)
    for name in caller_auth.CALLERS:
        assert caller_auth.read_token(name) not in out
