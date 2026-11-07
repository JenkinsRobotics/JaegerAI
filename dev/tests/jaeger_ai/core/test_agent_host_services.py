"""Host injection preserves canonical authority and repair implementations."""
import pytest
from pathlib import Path
import subprocess
import sys

from jaeger_agent.core import host


def test_missing_service_fails_at_the_feature_boundary():
    with pytest.raises(ImportError, match="not bound"):
        host.service("unbound-test-service")


def test_build_path_helper_does_not_require_agent_installation(tmp_path):
    repo = Path(__file__).resolve().parents[4]
    program = '''
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
class NoAgent:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'jaeger_agent' or fullname.startswith('jaeger_agent.'):
            raise ModuleNotFoundError('agent intentionally unavailable', name=fullname)
sys.meta_path.insert(0, NoAgent())
from jaeger_ai.cli._common import mac_shell_build_dir
assert mac_shell_build_dir(Path(sys.argv[1]))
assert 'jaeger_agent' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(repo)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_product_binds_authority_and_repair_without_alternate_implementations():
    from jaeger_ai.core.agent_host import bind_agent_host
    from jaeger_ai.core.entity import authority
    from jaeger_ai.core.runtime import tool_repair

    bind_agent_host()
    assert host.service("authority") is authority
    assert host.service("tool_repair") is tool_repair
    assert host.service("tool_repair").safe_parse_tool_arguments("{'count': 3}") == {"count": 3}
