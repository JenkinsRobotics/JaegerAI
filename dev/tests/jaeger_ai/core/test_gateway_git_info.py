from jaeger_ai.core.gateway.git_info import git_commit


def test_non_repo_is_quiet_and_unknown(tmp_path, capfd):
    git_commit.cache_clear()
    assert git_commit(str(tmp_path)) == "unknown"
    out, err = capfd.readouterr()
    assert "not a git repository" not in out + err


def test_cached_per_path(tmp_path, monkeypatch):
    git_commit.cache_clear()
    calls = []
    import subprocess as sp
    real = sp.run
    monkeypatch.setattr(sp, "run", lambda *a, **k: calls.append(1) or real(*a, **k))
    git_commit(str(tmp_path)); git_commit(str(tmp_path))
    assert len(calls) == 1


def test_standalone_revision_works_after_relocation(tmp_path):
    root = tmp_path / "JaegerAI.app" / "Contents" / "Resources" / "source"
    nested = root / "jaeger_ai" / "core" / "gateway"
    nested.mkdir(parents=True)
    sha = "ab" * 20
    (root / "build-revision").write_text(sha + "\n")
    git_commit.cache_clear()
    assert git_commit(str(nested)) == sha
