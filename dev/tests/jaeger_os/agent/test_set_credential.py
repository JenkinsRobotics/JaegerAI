"""set_credential — the agent can PERSIST a credential the user hands it.

The Lilith episode: the user gave the agent a bot token + chat ID and the
agent had no write tool, so it couldn't save them (and confabulated a CLI
command instead). The core writer already existed; this adds + exposes the
agent-callable tool and wires it into the credentials toolset so the model
actually sees it.
"""

import pathlib
import tempfile

import pytest

from jaeger_os.core import credentials as creds
from jaeger_os.core.instance.instance import InstanceLayout


def _layout() -> InstanceLayout:
    return InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))


def test_set_then_get_round_trip() -> None:
    layout = _layout()
    creds.set_credential(layout, "TELEGRAM_BOT_TOKEN", "123:abc")
    assert creds.get_credential(layout, "TELEGRAM_BOT_TOKEN") == "123:abc"
    assert "TELEGRAM_BOT_TOKEN" in creds.list_credentials(layout)


def test_written_credential_is_0600() -> None:
    p = creds.set_credential(_layout(), "K", "v")
    assert (p.stat().st_mode & 0o777) == 0o600


def test_empty_value_rejected() -> None:
    with pytest.raises(creds.CredentialError):
        creds.set_credential(_layout(), "K", "")


def test_set_credential_is_visible_in_the_credentials_toolset() -> None:
    # Membership here is what makes the model actually SEE set_credential
    # when the credentials toolset is scoped in — without it the tool is
    # registered but invisible, which is how this gap stayed hidden.
    from jaeger_os.agent.skill_registry.toolset_scoping import TOOLSETS
    assert "set_credential" in TOOLSETS["credentials"]
