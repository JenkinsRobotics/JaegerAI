from multidict import CIMultiDict

from jaeger_ai.features.engines import embed_proxy as p


def test_loopback_only():
    assert p.is_loopback("127.0.0.1") and p.is_loopback("::1")
    assert not p.is_loopback("100.74.2.15") and not p.is_loopback("192.168.1.5") and not p.is_loopback(None)


def test_frame_headers_rewritten_but_engine_csp_kept():
    up = CIMultiDict({"X-Frame-Options": "DENY", "Content-Type": "text/html",
                      "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; script-src 'self'"})
    out = p.response_headers(up)
    assert "X-Frame-Options" not in out and out["Content-Type"] == "text/html"
    csp = out["Content-Security-Policy"]
    assert "frame-ancestors 'none'" not in csp and "script-src 'self'" in csp
    assert "frame-ancestors 'self' http://127.0.0.1:8790" in csp


def test_targets_bind_loopback_ports():
    names = {t.name: t for t in p.TARGETS}
    assert names["openclaw"].upstream == 18789 and names["hermes"].upstream == 9119
