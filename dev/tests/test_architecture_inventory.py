"""Inventory must inspect potentially side-effectful code without executing it."""
import hashlib
import json
from pathlib import Path

from dev.scripts.architecture_inventory import build_domains, inspect_python


ROOT = Path(__file__).resolve().parents[2]


def test_inventory_extracts_evidence_without_executing_source():
    report = inspect_python('''
raise RuntimeError("must never execute")
import sqlite3
from api.config import STATE_DIR
path = os.environ["JAEGER_STATE_DIR"]
db = sqlite3.connect(STATE_DIR / "sessions.db")
@register_tool_from_function(name="remember", side_effect="write")
def save(text: str):
    return text
async def run_turn():
    route = "/v1/sessions"
''')
    assert report["environment"] == ["JAEGER_STATE_DIR"]
    assert report["imports"] == ["api.config", "sqlite3"]
    assert report["tools"][0]["name"] == "remember"
    assert report["tools"][0]["side_effect"] == "write"
    assert report["stores"][0]["expression"] == "sqlite3.connect(STATE_DIR / 'sessions.db')"
    assert report["routes"][0]["literal"] == "/v1/sessions"
    assert report["entrypoints"][0]["name"] == "run_turn"


def test_computed_routes_are_not_misrepresented_as_verified_endpoints():
    report = inspect_python('path = "/api/" + name')
    assert report["routes"][0]["literal"] == "/api/"
    assert report["routes"][0]["method"] is None
    assert report["routes"][0]["matcher"] == "reference"


def test_route_dispatcher_records_method_and_prefix_without_claiming_runtime_contract():
    report = inspect_python('''
def handle_get(handler, parsed):
    if parsed.path == "/health":
        return ok(handler)
    if parsed.path.startswith("/api/sessions/"):
        return session(handler)
''')
    routes = {route["literal"]: route for route in report["routes"]}
    assert routes["/health"]["method"] == "GET"
    assert routes["/health"]["dispatcher"] == "handle_get"
    assert routes["/api/sessions/"]["matcher"] == "prefix"


def test_domain_inventory_reports_source_evidence_without_claiming_ownership(tmp_path):
    feature = tmp_path / "jaeger_ai" / "features" / "camera"
    feature.mkdir(parents=True)
    (feature / "README.md").write_text("# Camera\n\nExperimental.\n", encoding="utf-8")
    report = {
        "files": {
            "jaeger_ai/features/camera/store.py": {
                "environment": ["CAMERA_DEVICE"],
                "imports": ["sqlite3"],
                "stores": [{"line": 7, "expression": "sqlite3.connect(path)"}],
            },
            "jaeger_ai/main.py": {
                "imports": ["jaeger_ai.features.camera.store"],
            },
            "dev/tests/jaeger_ai/features/test_camera.py": {},
        },
    }

    domains = build_domains(report, tmp_path)

    camera = domains["features"][0]
    assert camera["callers"] == ["jaeger_ai/main.py"]
    assert camera["configuration_keys"] == ["CAMERA_DEVICE"]
    assert camera["maturity"] == "experimental"
    assert camera["parity_evidence"] == []
    assert domains["stores"][0]["ownership"] == "unclassified"
    assert domains["stores"][0]["evidence"] == "Python AST"


def test_webui_static_dispatch_contract_has_not_silently_drifted():
    fixture = json.loads(
        (ROOT / "dev/tests/fixtures/webui_static_dispatch_contract.json").read_text(
            encoding="utf-8"
        )
    )
    source = (ROOT / "jaeger_ai/features/webui/api/routes.py").read_text(encoding="utf-8")
    routes = inspect_python(source)["routes"]
    rows = sorted(
        (route["method"], route["matcher"], route["literal"], route["dispatcher"])
        for route in routes
        if route["method"]
    )
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode()
    counts = {method: sum(row[0] == method for row in rows) for method in fixture["method_counts"]}

    assert len(rows) == fixture["route_count"]
    assert counts == fixture["method_counts"]
    assert hashlib.sha256(payload).hexdigest() == fixture["route_fingerprint_sha256"]
    for required in fixture["required_routes"]:
        assert tuple(required) in rows
    assert fixture["unverified"], "static evidence must not be represented as runtime proof"
