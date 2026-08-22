"""Secret redaction — keep API keys out of logs / the audit trail.

Audit A3. `core/redact.py` masks API keys, tokens, auth headers, private
keys and credentialed URLs before they reach `logs/audit.log` or the
JSONL trajectory export. Each secret below carries a recognisable marker
substring; the test asserts that marker is gone after redaction.
"""

from __future__ import annotations

from jaeger_os.core.safety.redact import mask_secret, redact_obj, redact_text


# ── redact_text — secrets are masked ────────────────────────────────


def test_openai_style_key_is_masked():
    out = redact_text("here is sk-SECRETvalue1234567890abc done")
    assert "SECRETvalue" not in out
    assert "sk-" in out          # the prefix survives for debuggability


def test_google_key_is_masked():
    out = redact_text("key AIzaSECRETgooglekey1234567890abcdefghij end")
    assert "SECRETgooglekey" not in out


def test_github_pat_is_masked():
    out = redact_text("token ghp_SECRETgithubtoken123456 ok")
    assert "SECRETgithubtoken" not in out


def test_env_assignment_is_masked():
    out = redact_text("OPENAI_API_KEY=SUPERSECRETvalue123456")
    assert "SUPERSECRET" not in out
    assert "OPENAI_API_KEY=" in out


def test_json_api_key_field_is_masked():
    out = redact_text('{"api_key": "SECRETjsonvalue123456"}')
    assert "SECRETjsonvalue" not in out


def test_auth_header_is_masked():
    out = redact_text("Authorization: Bearer abcSECRETbearertoken123")
    assert "SECRETbearertoken" not in out


def test_private_key_block_is_redacted():
    block = ("-----BEGIN RSA PRIVATE KEY-----\n"
             "MIISECRETkeymaterialblob\n"
             "-----END RSA PRIVATE KEY-----")
    out = redact_text(f"the key is:\n{block}\nthanks")
    assert "SECRETkeymaterial" not in out
    assert "[REDACTED PRIVATE KEY]" in out


def test_db_connection_string_password_is_masked():
    out = redact_text("postgres://admin:hunter2SECRETpw@db.example.com/app")
    assert "hunter2SECRETpw" not in out
    assert "admin" in out         # only the password is masked


def test_url_userinfo_password_is_masked():
    out = redact_text("clone https://user:t0kenSECRETvalue@github.com/x.git")
    assert "t0kenSECRETvalue" not in out


def test_jwt_is_masked():
    jwt = "eyJhbGciOiJIUzI1NiSECRETjwt.eyJzdWIiOiJ1c2VyMS234.SflKxwSECRETsig"
    out = redact_text(f"cookie={jwt}")
    assert "SECRETjwt" not in out


# ── redact_text — innocent text untouched ───────────────────────────


def test_plain_text_passes_through_unchanged():
    text = "The quick brown fox jumps over the lazy dog. 2 + 2 = 4."
    assert redact_text(text) == text


def test_non_string_passes_through():
    assert redact_text(None) is None
    assert redact_text(42) == 42


# ── redact_obj — recursive ──────────────────────────────────────────


def test_redact_obj_walks_nested_structures():
    obj = {
        "command": "curl -H 'Authorization: Bearer sk-SECRETnested12345678'",
        "count": 5,
        "ok": True,
        "tags": ["plain", "AIzaSECRETnestedgooglekey1234567890abcd"],
        "nested": {"note": "OPENAI_API_KEY=SECRETnestedenv123456"},
    }
    out = redact_obj(obj)
    assert "SECRETnested12345678" not in out["command"]
    assert "SECRETnestedgooglekey" not in out["tags"][1]
    assert "SECRETnestedenv" not in out["nested"]["note"]
    # Non-strings and innocent values are untouched.
    assert out["count"] == 5
    assert out["ok"] is True
    assert out["tags"][0] == "plain"


def test_redact_obj_does_not_mutate_input():
    obj = {"k": "sk-SECRETnomutate1234567890"}
    redact_obj(obj)
    assert obj["k"] == "sk-SECRETnomutate1234567890"   # original intact


# ── mask_secret — display helper ────────────────────────────────────


def test_mask_secret_keeps_head_and_tail():
    masked = mask_secret("sk-proj-abcdefghijklmnop1234")
    assert masked.startswith("sk-p")
    assert masked.endswith("1234")
    assert "..." in masked


def test_mask_secret_fully_masks_short_values():
    assert mask_secret("short") == "***"


def test_mask_secret_empty_is_empty():
    assert mask_secret("") == ""
