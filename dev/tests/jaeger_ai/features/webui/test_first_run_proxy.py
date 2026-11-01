"""First-run WebUI routes forward to the owner-authenticated Gateway proxy."""
import ast
from pathlib import Path

ROUTES = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/routes.py'


def test_first_run_proxy_routes_are_explicit():
    tree = ast.parse(ROUTES.read_text())
    get = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'handle_get')
    post = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'handle_post')
    get_text = ast.unparse(get)
    post_text = ast.unparse(post)
    assert "parsed.path == '/v1/first-run'" in get_text
    assert "_proxy_jaeger_gateway(handler, 'GET', '/v1/first-run')" in get_text
    assert "'/v1/first-run/setup'" in post_text
    assert "'/v1/first-run/skip'" in post_text
    assert "_proxy_jaeger_gateway(handler, 'POST', parsed.path" in post_text
