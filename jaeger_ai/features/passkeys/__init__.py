"""WebAuthn passkey authentication feature."""

from .service import (
    PasskeyError,
    authentication_options,
    bind_state_dir,
    delete_credential,
    finish_login,
    finish_registration,
    passkeys_available,
    registered_credentials,
    registration_options,
)

__all__ = [
    "PasskeyError",
    "authentication_options",
    "bind_state_dir",
    "delete_credential",
    "finish_login",
    "finish_registration",
    "passkeys_available",
    "registered_credentials",
    "registration_options",
]
