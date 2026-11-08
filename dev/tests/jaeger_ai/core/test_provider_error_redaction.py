"""Provider diagnostic redaction preserves the actionable cause, never credentials."""
import pytest

from jaeger_ai.core.redaction import redact_text


@pytest.mark.parametrize("value,secret", [
    ('401 rejected {"Authorization": "Bearer dummy-header-key"}', 'dummy-header-key'),
    ("401 rejected {'Authorization': 'Basic dummy-basic-key'}", 'dummy-basic-key'),
    ('400 invalid model {"api_key": "dummy-json-key"}', 'dummy-json-key'),
    ('503 unavailable https://user:dummy-password@provider.invalid/v1', 'dummy-password'),
    ('503 unavailable https://dummy-userinfo@provider.invalid/v1', 'dummy-userinfo'),
    ('400 invalid model https://provider.invalid?api_key=dummy-query-key&model=bad', 'dummy-query-key'),
])
def test_redacts_provider_diagnostic_credentials(value, secret):
    result = redact_text(value)
    assert secret not in result
    assert value.split()[0] in result
    assert redact_text(result) == result


def test_preserves_useful_uncredentialed_error():
    value = "503 provider unavailable; retry later, model=example-model"
    assert redact_text(value) == value


@pytest.mark.parametrize("value,secret", [
    ("503 password='dummy words, suffix' unavailable", 'words'),
    ('503 {"api_key": "dummy words, suffix"} unavailable', 'suffix'),
    (r'401 {\"Authorization\": \"Bearer dummy-escaped-key\"}', 'dummy-escaped-key'),
    ('503 https://user:dummy@part@provider.invalid unavailable', 'part@'),
])
def test_quoted_and_nested_provider_diagnostics(value, secret):
    result = redact_text(value)
    assert secret not in result
    assert value[:3] in result
    assert redact_text(result) == result


@pytest.mark.parametrize("value", [
    r'401 {"password":"dummy\"tail"}',
    "401 password='dummy\ntail'",
])
def test_quoted_credentials_with_escapes_or_newlines(value):
    result = redact_text(value)
    assert "dummy" not in result and "tail" not in result
    assert "401" in result


@pytest.mark.parametrize("value,secret", [
    ("401 rejected Bearer dummy-standalone-key", "dummy-standalone-key"),
    ("401 headers=[('Authorization', 'Bearer dummy-tuple-key')]", "dummy-tuple-key"),
    ("401 headers=[('Authorization', 'Basic ZHVtbXk6c2VjcmV0')]", "ZHVtbXk6c2VjcmV0"),
])
def test_explicit_auth_schemes(value, secret):
    result = redact_text(value)
    assert secret not in result
    assert "401" in result
    assert redact_text(result) == result


@pytest.mark.parametrize("value", ["authentication required", "Bearer authentication required", "Bearer credentials unavailable"])
def test_authentication_guidance_is_not_a_credential(value):
    assert redact_text(value) == value


def test_receipt_redaction_preserves_operational_fields_and_numeric_usage():
    from jaeger_ai.core.gateway.server import _redact_native_receipt
    value = {"turn_id": "token=harmless-id", "session_id": "password=harmless-id", "status": "completed",
             "execution_unknown": False, "source": "native", "observed_at": 123,
             "reply": {"usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
                       "metadata": {"author": "worker", "auth_required": False},
                       "text": "Completed report", "diagnostics": {"error": "401 Bearer dummy-error-key"},
                       "headers": {"Authorization": "dummy-header-key"}}}
    result = _redact_native_receipt(value)
    for key in ("turn_id", "session_id", "status", "execution_unknown", "source", "observed_at"):
        assert result[key] == value[key]
    for key in ("usage", "metadata", "text"):
        assert result["reply"][key] == value["reply"][key]
    assert "dummy-error-key" not in str(result) and "dummy-header-key" not in str(result)
    assert "dummy-error-key" in str(value)


@pytest.mark.parametrize("value,secret", [
    ("401 [('Authorization', 'Bearer abcdefgh')]", "abcdefgh"),
    ('401 [("Authorization", "Basic abcdefgh")]', "abcdefgh"),
    ('401 [["Authorization", "Bearer abcdefgh"]]', "abcdefgh"),
    (r"401 [('Authorization', 'Bearer abc\'defgh')]", "defgh"),
    (r'401 [(\"Authorization\", \"Bearer abcdefgh\")]', "abcdefgh"),
])
def test_explicit_tuple_authorization_hides_short_credential(value, secret):
    result = redact_text(value)
    assert secret not in result
    assert "401" in result and "Authorization" in result
    assert redact_text(result) == result


@pytest.mark.parametrize("pair", [("Authorization", "Bearer abcdefgh"), ["Authorization", "Bearer abcdefgh"]])
def test_receipt_header_pairs_are_sensitive_only_in_diagnostics(pair):
    from jaeger_ai.core.gateway.server import _redact_native_receipt
    source = {"reply": {"headers": [pair], "diagnostics": {"request_headers": [pair]},
                        "metadata": {"operational_pairs": [pair]}}}
    result = _redact_native_receipt(source)
    for key in ("headers", "diagnostics"):
        assert "abcdefgh" not in str(result["reply"][key])
    assert result["reply"]["metadata"] == source["reply"]["metadata"]
    assert type(result["reply"]["headers"][0]) is type(pair)
    assert "abcdefgh" in str(source["reply"]["headers"])


@pytest.mark.parametrize("value", [
    "503 https://provider.invalid?contact=user@example.invalid",
    "503 https://provider.invalid#user@example.invalid",
])
def test_url_query_or_fragment_email_is_not_userinfo(value):
    assert redact_text(value) == value


def test_escaped_header_pair_with_escaped_credential_quote():
    value = r'401 [(\"Authorization\", \"Bearer abc\\\"defgh\")]'
    result = redact_text(value)
    assert "defgh" not in result and "401" in result
