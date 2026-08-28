from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jaeger_agent import workspace
from jaeger_agent.safety import _DESTRUCTIVE_COMMAND_RE
from jaeger_agent.trace import Tracer


def test_destructive_commands_are_detected():
    commands = (
        "rm -rf /", "rm -fr /", "rm -rf ~", "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/sda", "chmod -R 777 /", "git clean -fdx",
    )
    assert all(_DESTRUCTIVE_COMMAND_RE.search(command) for command in commands)


def test_safe_commands_are_not_overblocked():
    commands = ("rm -f ./build.log", "chmod 755 ./script", "git clean -n")
    assert not any(_DESTRUCTIVE_COMMAND_RE.search(command) for command in commands)


def test_project_root_override_does_not_replace_process_fallback(tmp_path: Path):
    base = tmp_path / "base"
    override = tmp_path / "override"
    base.mkdir()
    override.mkdir()
    workspace._project_root_global_fallback = base

    def set_override():
        workspace.set_project_root(override)
        return workspace.get_project_root()

    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(set_override).result() == override
    assert workspace._project_root_global_fallback == base


def test_tracer_turn_ids_are_unique_across_threads(monkeypatch):
    tracer = Tracer()
    monkeypatch.setattr(tracer, "_emit", lambda *args, **kwargs: None)
    with ThreadPoolExecutor(max_workers=16) as pool:
        ids = list(pool.map(lambda index: tracer.begin(str(index), "x"), range(500)))
    assert len(ids) == len(set(ids)) == 500
