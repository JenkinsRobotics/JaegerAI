"""INST-5 + INST-6 — ``jaeger backup`` and ``jaeger restore``."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from jaeger_os.cli.verbs import backup_restore as B


# ── fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def fake_instance(tmp_path, monkeypatch):
    """Build a fake ``~/.jaeger/instances/test/`` instance with a
    handful of files + the standard subdirs, and point HOME at the
    tmp_path so the resolver discovers it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)

    inst = tmp_path / ".jaeger_os" / "instances" / "test"
    inst.mkdir(parents=True)
    (inst / "identity.yaml").write_text("name: Test\n", encoding="utf-8")
    (inst / "config.yaml").write_text("ctx: 32768\n", encoding="utf-8")
    (inst / "manifest.json").write_text(
        '{"instance_name":"test","schema_version":"1.1.0"}',
        encoding="utf-8",
    )
    (inst / "soul.md").write_text("# test agent\n", encoding="utf-8")

    # Memory — kept.
    (inst / "memory").mkdir()
    (inst / "memory" / "facts.json").write_text('{"birthday":"may"}',
                                                encoding="utf-8")
    # Memory — excluded by default (large npz).
    (inst / "memory" / "episodic.embeddings.npz").write_bytes(b"\x00" * 100)

    # Logs — live one kept, rotated ones excluded.
    (inst / "logs").mkdir()
    (inst / "logs" / "audit.log").write_text("live\n", encoding="utf-8")
    (inst / "logs" / "audit.log.20260101").write_text("old\n",
                                                       encoding="utf-8")

    # Credentials — excluded by default.
    (inst / "credentials").mkdir(mode=0o700)
    (inst / "credentials" / "external_model_api_key").write_text(
        "sk-secret", encoding="utf-8",
    )

    # Skills — kept by default.
    (inst / "skills").mkdir()
    (inst / "skills" / "my_skill_v1").mkdir()
    (inst / "skills" / "my_skill_v1" / "SKILL.md").write_text(
        "# my skill", encoding="utf-8",
    )

    # Run — excluded (runtime state).
    (inst / "run").mkdir()
    (inst / "run" / "jaeger.pid").write_text("12345", encoding="utf-8")

    return inst


# ── backup_instance ────────────────────────────────────────────────


def test_backup_creates_archive_with_manifest(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    archive = B.backup_instance("test", output=out)
    assert archive == out
    assert archive.exists()
    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("MANIFEST.json"))
    assert manifest["instance_name"] == "test"
    assert manifest["schema"] == "jaeger-backup"
    assert manifest["include_credentials"] is False


def test_backup_excludes_credentials_by_default(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    B.backup_instance("test", output=out)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert not any("external_model_api_key" in n for n in names)
    # The .gitkeep placeholder for credentials/ DOES still ship so a
    # restored instance has a structurally complete tree.
    # (depends on whether the fixture has one; not asserted here)


def test_backup_includes_credentials_when_opted_in(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    B.backup_instance("test", output=out, include_credentials=True)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any("credentials/external_model_api_key" in n for n in names)


def test_backup_excludes_embeddings_npz(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    B.backup_instance("test", output=out)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert not any("episodic.embeddings.npz" in n for n in names)
    # ``memory/facts.json`` IS included (small + load-bearing).
    assert any("memory/facts.json" in n for n in names)


def test_backup_excludes_rotated_logs(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    B.backup_instance("test", output=out)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any("logs/audit.log" in n for n in names)
    assert not any("audit.log.20260101" in n for n in names)


def test_backup_excludes_run_dir(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    B.backup_instance("test", output=out)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert not any("run/" in n for n in names)


def test_backup_includes_skills_by_default(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    B.backup_instance("test", output=out)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert any("skills/my_skill_v1/SKILL.md" in n for n in names)


def test_backup_skips_skills_when_no_skills(fake_instance, tmp_path):
    out = tmp_path / "out.zip"
    B.backup_instance("test", output=out, include_skills=False)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert not any("skills/my_skill_v1" in n for n in names)


def test_backup_default_output_lands_in_backups_dir(fake_instance, tmp_path,
                                                     monkeypatch):
    archive = B.backup_instance("test")
    assert archive.parent == tmp_path / ".jaeger_os" / "backups"
    assert archive.name.startswith("test-")
    assert archive.suffix == ".zip"


def test_backup_raises_on_missing_instance(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    with pytest.raises(FileNotFoundError):
        B.backup_instance("nonexistent", output=tmp_path / "out.zip")


# ── restore_instance ───────────────────────────────────────────────


def test_restore_round_trip(fake_instance, tmp_path):
    archive = tmp_path / "out.zip"
    B.backup_instance("test", output=archive)

    # Wipe original to force restore.
    import shutil
    shutil.rmtree(fake_instance)

    target = B.restore_instance(archive)
    # Should have landed back at the same path.
    assert target == fake_instance.resolve()
    assert (target / "identity.yaml").exists()
    assert (target / "memory" / "facts.json").exists()
    # Credentials should NOT be restored (they weren't backed up).
    assert not (target / "credentials" / "external_model_api_key").exists()


def test_restore_refuses_on_name_collision(fake_instance, tmp_path):
    archive = tmp_path / "out.zip"
    B.backup_instance("test", output=archive)

    # ``test`` still exists; restore without --force should refuse.
    with pytest.raises(B.RestoreError, match="already exists"):
        B.restore_instance(archive)


def test_restore_force_backs_up_existing(fake_instance, tmp_path):
    archive = tmp_path / "out.zip"
    B.backup_instance("test", output=archive)

    # Put a marker in the existing instance so we can verify the
    # backup-aside happened.
    (fake_instance / "marker.txt").write_text("original", encoding="utf-8")

    B.restore_instance(archive, force=True)

    # The restored instance is fresh (no marker.txt) and the
    # original got renamed to <name>.bak.<ts>.
    assert not (fake_instance / "marker.txt").exists()
    siblings = list(fake_instance.parent.iterdir())
    bak_dirs = [p for p in siblings if p.name.startswith("test.bak.")]
    assert bak_dirs, "expected a backup-aside dir"
    assert (bak_dirs[0] / "marker.txt").read_text() == "original"


def test_restore_to_different_name(fake_instance, tmp_path):
    archive = tmp_path / "out.zip"
    B.backup_instance("test", output=archive)
    target = B.restore_instance(archive, name_override="restored")
    assert target.name == "restored"
    assert (target / "identity.yaml").exists()


def test_restore_stamps_distribution_yaml(fake_instance, tmp_path):
    archive = tmp_path / "out.zip"
    B.backup_instance("test", output=archive)
    target = B.restore_instance(archive, name_override="restored2")
    dist_path = target / "distribution.yaml"
    assert dist_path.exists()
    body = dist_path.read_text(encoding="utf-8")
    assert "install_method: imported" in body
    assert "restored_from:" in body


def test_restore_refuses_newer_archive(fake_instance, tmp_path):
    archive = tmp_path / "future.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("MANIFEST.json", json.dumps({
            "schema": "jaeger-backup",
            "instance_name": "test",
            "schema_version": "99.0.0",  # impossibly future
        }))
    with pytest.raises(B.RestoreError, match="newer framework"):
        B.restore_instance(archive)


def test_restore_zip_slip_protection(fake_instance, tmp_path):
    """An archive containing a ``../`` traversal attempt must NOT
    write outside the target dir."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("MANIFEST.json", json.dumps({"instance_name": "evil"}))
        zf.writestr("evil/identity.yaml", "name: evil\n")
        # Try to escape.
        zf.writestr("evil/../escaped.txt", "should not land")
    target = B.restore_instance(archive)
    assert (target / "identity.yaml").exists()
    # The escape attempt didn't write anywhere visible.
    assert not (target.parent / "escaped.txt").exists()
