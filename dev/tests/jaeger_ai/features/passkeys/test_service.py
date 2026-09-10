from __future__ import annotations

from email.message import Message

from jaeger_ai.features.passkeys import service


class _Handler:
    headers = Message()
    is_secure_context = True


def test_passkeys_are_instance_scoped_and_public_metadata_excludes_keys(tmp_path) -> None:
    service.bind_state_dir(tmp_path)
    service._save_credentials([{
        "id": "credential",
        "label": "Laptop",
        "public_key_pem": "SECRET PUBLIC KEY",
        "created_at": 1,
        "sign_count": 2,
    }])
    assert service.passkeys_available()
    assert service.registered_credentials() == [{
        "id": "credential",
        "label": "Laptop",
        "created_at": 1,
        "last_used_at": None,
        "sign_count": 2,
    }]
    assert (tmp_path / "passkeys.json").stat().st_mode & 0o777 == 0o600


def test_authentication_options_create_bounded_challenge(tmp_path) -> None:
    service.bind_state_dir(tmp_path)
    service._save_credentials([{"id": "credential", "label": "Laptop"}])
    handler = _Handler()
    handler.headers["Host"] = "jaeger.example"
    options = service.authentication_options(handler)
    assert options["rpId"] == "jaeger.example"
    assert options["allowCredentials"][0]["id"] == "credential"
    assert len(service._load_challenges()) == 1
