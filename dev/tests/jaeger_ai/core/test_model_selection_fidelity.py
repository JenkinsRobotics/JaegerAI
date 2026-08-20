"""A selected model serves, or the boot says why — it never substitutes.

The failure this file pins: selecting a cloud model (Qwen on Ollama
Cloud) with a key that doesn't resolve used to print one warning line and
then allocate ~15 GB of LOCAL GGUF weights, answering every subsequent
turn from a model nobody chose. The operator saw the cloud model in
``config.yaml`` and a different brain doing the work.

So:

  - ``make_client`` RAISES :class:`ExternalModelSelectionError` when the
    selected external brain can't be built or reached;
  - the message names provider and model SEPARATELY (they are two
    choices, and merging them reads as one model id) and carries the
    fixes for that provider;
  - there is no degrade-to-local path, including ``JAEGER_ALLOW_LOCAL_FALLBACK``;
  - switching away from a local brain RELEASES its weights rather than
    waiting for the GC — on unified memory those weights are VRAM.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import jaeger_ai.main as main
from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, ModelConfig
from jaeger_ai.core.models import external_model as em
from jaeger_ai.core.models.external_model import (
    ExternalModelError,
    ExternalModelSelectionError,
    resolve_api_key,
    selection_failure_message,
    validate_external_provider,
)
from jaeger_ai.core.models.vram import release_local_client


def _cloud_config(**over):
    """A Config whose brain is Ollama Cloud — the reported scenario."""
    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
        **over,
    )
    cfg = Config(
        instance_name="t",
        model=ModelConfig(model_path="/tmp/never-loaded.gguf"),
    )
    cfg.external_model = ext
    return cfg


class _Unreachable:
    """Stands in for ``ExternalModelClient`` when the endpoint is down."""

    def __init__(self, ext, layout=None):
        self.ext = ext

    def connectivity_check(self):
        return {"ok": False, "detail": "401 Unauthorized", "latency_s": 0.0}

    def describe(self):
        return "external · unreachable"


# ── no silent substitution ──────────────────────────────────────────


def test_unreachable_cloud_selection_raises_instead_of_loading_local(monkeypatch):
    """The reported bug: a cloud model that fails its check must NOT
    fall through to the local GGUF branch."""
    monkeypatch.delenv("JAEGER_ALLOW_LOCAL_FALLBACK", raising=False)
    monkeypatch.setattr(em, "ExternalModelClient", _Unreachable)

    def _boom(*a, **k):  # pragma: no cover — reaching this IS the failure
        raise AssertionError("local engine was resolved for a cloud selection")

    from jaeger_ai.core.models import engine_registry
    monkeypatch.setattr(engine_registry, "resolve_engine", _boom)

    with pytest.raises(ExternalModelSelectionError) as caught:
        main.make_client(_cloud_config(), layout=None)
    assert "401 Unauthorized" in str(caught.value)


def test_missing_key_raises_selection_error(monkeypatch):
    """A key that doesn't resolve is a selection failure too — the
    client never even constructs."""
    monkeypatch.delenv("JAEGER_ALLOW_LOCAL_FALLBACK", raising=False)
    for var in ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ExternalModelSelectionError):
        main.make_client(_cloud_config(), layout=None)


def test_selection_error_is_an_external_model_error():
    """Callers catching the broad type keep working."""
    assert issubclass(ExternalModelSelectionError, ExternalModelError)


def test_reachable_selection_is_returned(monkeypatch):
    """The happy path still returns the external client, untouched."""

    class _Reachable(_Unreachable):
        def connectivity_check(self):
            return {"ok": True, "detail": "endpoint reachable", "latency_s": 0.1}

    monkeypatch.setattr(em, "ExternalModelClient", _Reachable)
    client = main.make_client(_cloud_config(), layout=None)
    assert isinstance(client, _Reachable)


def test_env_opt_in_does_not_restore_local_fallback(monkeypatch):
    """``JAEGER_ALLOW_LOCAL_FALLBACK`` used to load 15 GB of local weights
    while the picker still named a cloud model. It is ignored."""
    monkeypatch.setenv("JAEGER_ALLOW_LOCAL_FALLBACK", "1")
    monkeypatch.setattr(em, "ExternalModelClient", _Unreachable)

    def _boom(*a, **k):  # pragma: no cover — reaching this IS the failure
        raise AssertionError("local engine was resolved for a cloud selection")

    from jaeger_ai.core.models import engine_registry
    monkeypatch.setattr(engine_registry, "resolve_engine", _boom)

    with pytest.raises(ExternalModelSelectionError):
        main.make_client(_cloud_config(), layout=None)


# ── the message an operator actually reads ──────────────────────────


def test_failure_message_keeps_provider_and_model_separate():
    ext = _cloud_config().external_model
    msg = selection_failure_message(ext, "unreachable — 401 Unauthorized")
    assert "'ollama-cloud'" in msg
    assert "'qwen3.5:397b'" in msg
    # Never merged into one provider/model token — that reads as a model id.
    assert "ollama-cloud/qwen3.5:397b" not in msg


def test_failure_message_names_credentials_and_env_vars():
    ext = _cloud_config().external_model
    msg = selection_failure_message(ext, "not configured — no key")
    assert "OLLAMA_API_KEY" in msg and "OLLAMA_CLOUD_API_KEY" in msg
    assert "will not load a local" in msg


def test_failure_message_for_a_local_server_says_start_it():
    ext = ExternalModelConfig(
        enabled=True, provider="lmstudio", model="local-model",
    )
    msg = selection_failure_message(ext, "unreachable — connection refused")
    assert "start the lmstudio server" in msg
    assert "OPENAI_API_KEY" not in msg   # a local server needs no key


def test_missing_key_message_lists_env_vars_readably():
    """``_CONVENTIONAL_ENV`` holds tuples; the message must not print a
    Python tuple repr at the operator."""
    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
    )
    with pytest.raises(ExternalModelError) as caught:
        validate_external_provider(ext, api_key="")
    msg = str(caught.value)
    assert "OLLAMA_API_KEY, OLLAMA_CLOUD_API_KEY" in msg
    assert "('OLLAMA_API_KEY'" not in msg


# ── credential + env aliases ────────────────────────────────────────


_KEY_VARS = ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY",
             "GEMINI_API_KEY", "GOOGLE_API_KEY",
             "XAI_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY")


@pytest.mark.parametrize("provider,var,expected", [
    ("ollama-cloud", "OLLAMA_CLOUD_API_KEY", "cloud-key"),
    ("ollama-cloud", "OLLAMA_KEY", "short-key"),
    ("gemini", "GOOGLE_API_KEY", "google-key"),
    ("xai", "GROK_API_KEY", "grok-key"),
])
def test_conventional_env_aliases(monkeypatch, provider, var, expected):
    for name in _KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(var, expected)
    ext = ExternalModelConfig(provider=provider, api_key_env="")
    assert resolve_api_key(ext, layout=None) == expected


@pytest.mark.parametrize("filename", [
    "ollama_cloud_api_key",       # the provider's own credential name
    "ollama_api_key",             # the shared-with-local-Ollama alias
    "external_model_api_key",     # the generic fallback
])
def test_ollama_cloud_key_from_credential_file(monkeypatch, tmp_path, filename):
    """A key stored under ANY of the names the operator might plausibly
    have used resolves — the gap that made a configured cloud brain look
    unconfigured and hand the turn to local weights."""
    for name in _KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    creds = tmp_path / "credentials"
    creds.mkdir()
    (creds / filename).write_text("stored-key\n", encoding="utf-8")

    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
    )
    layout = SimpleNamespace(root=tmp_path, credentials_dir=creds)
    assert resolve_api_key(ext, layout) == "stored-key"


def test_credential_file_beats_env(monkeypatch, tmp_path):
    """Credentials are the sanctioned secret path — they win."""
    monkeypatch.setenv("OLLAMA_API_KEY", "from-env")
    creds = tmp_path / "credentials"
    creds.mkdir()
    (creds / "ollama_cloud_api_key").write_text("from-store", encoding="utf-8")
    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
    )
    layout = SimpleNamespace(root=tmp_path, credentials_dir=creds)
    assert resolve_api_key(ext, layout) == "from-store"


# ── connectivity probe diagnostics ──────────────────────────────────


def test_probe_reports_the_real_error_not_the_fallbacks(monkeypatch):
    """Ollama's ``/api/tags`` retry must not overwrite the diagnosis. A
    rejected key on ``/v1/models`` followed by a 404 on ``/api/tags``
    used to be reported as "404" — sending the operator to look for a
    missing model instead of a bad key."""
    import requests

    class _Resp:
        def __init__(self, msg):
            self.msg = msg

        def raise_for_status(self):
            raise requests.HTTPError(self.msg)

    def _fake_get(url, **kwargs):
        return _Resp("401 Client Error: Unauthorized"
                     if "/models" in url else "404 Client Error: Not Found")

    monkeypatch.setattr(requests, "get", _fake_get)

    ext = ExternalModelConfig(
        enabled=True, provider="ollama-cloud",
        base_url="https://ollama.com/v1", model="qwen3.5:397b",
    )
    client = em.ExternalModelClient.__new__(em.ExternalModelClient)
    client.ext = ext
    client.provider = "ollama-cloud"
    client._api_key = "bad-key"

    result = client.connectivity_check()
    assert result["ok"] is False
    assert "401" in result["detail"] or "Unauthorized" in result["detail"]
    assert "404" not in result["detail"]


# ── explicit VRAM release ───────────────────────────────────────────


class _FakeLlama:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeExecutor:
    def __init__(self):
        self.shut = False

    def shutdown(self, wait=True):
        self.shut = True


def _local_client():
    return SimpleNamespace(
        kind="local", llm=_FakeLlama(), _aux_llm=_FakeLlama(),
        _executor=_FakeExecutor(), model_name="gemma.gguf",
    )


def test_release_closes_worker_and_aux_lanes():
    client = _local_client()
    llm, aux, executor = client.llm, client._aux_llm, client._executor

    assert release_local_client(client) is True

    assert llm.closed and aux.closed
    assert executor.shut
    # Nulled, so a reference that outlived the switch can't decode into
    # weights that are gone.
    assert client.llm is None and client._aux_llm is None


def test_release_ignores_an_external_client():
    """An HTTP endpoint holds no local weights — nothing to unload."""
    client = SimpleNamespace(kind="external", provider="ollama-cloud")
    assert release_local_client(client) is False


def test_release_handles_nothing_loaded():
    assert release_local_client(None) is False


def test_release_survives_a_client_that_fails_to_close():
    """Teardown is best-effort: a broken close must not abort the switch."""
    class _Angry:
        def close(self):
            raise RuntimeError("nope")

    client = SimpleNamespace(kind="local", llm=_Angry(), _aux_llm=None,
                             _executor=None)
    assert release_local_client(client) is True


def test_every_local_client_class_exposes_unload():
    """``unload()`` is the verb teardown paths call. It must exist on
    every client that can hold weights — and on the external client too,
    so no call site needs a ``hasattr`` guard that could skip the one
    case that matters."""
    from jaeger_ai.core.models.llm_client import (
        LlamaCppPythonClient as BenchClient,
    )
    from jaeger_ai.core.models.mlx_client import MlxClient
    from jaeger_ai.core.models.mlx_vlm_client import MlxVlmClient

    for cls in (main.LlamaCppPythonClient, BenchClient, MlxClient,
                MlxVlmClient, em.ExternalModelClient):
        assert callable(getattr(cls, "unload", None)), cls.__name__


@pytest.mark.parametrize("cls_getter", [
    lambda: main.LlamaCppPythonClient,
    lambda: __import__(
        "jaeger_ai.core.models.mlx_client", fromlist=["MlxClient"],
    ).MlxClient,
])
def test_unload_releases_weights_without_constructing_a_model(cls_getter):
    """Called against a stand-in holding the same fields a real client
    holds — the weights close, the executor stops, nothing raises. (The
    real classes can't be constructed without multi-GB weights on disk,
    so the method is exercised unbound.)"""
    client = _local_client()
    llm, executor = client.llm, client._executor

    cls_getter().unload(client)

    assert llm.closed and executor.shut
    assert client.llm is None


def test_external_client_unload_is_a_harmless_noop():
    ext = ExternalModelConfig(enabled=True, provider="lmstudio", model="m")
    client = em.ExternalModelClient(ext, layout=None)
    assert client.unload() is None
    # Still usable — nothing was torn down, because nothing was held.
    assert client.provider == "lmstudio"


def test_unload_is_idempotent():
    """Teardown paths overlap (boot cleanup AND the switch both call it);
    the second call must be a no-op, not a crash."""
    client = _local_client()
    assert release_local_client(client) is True
    assert release_local_client(client) is True
    assert client.llm is None


def test_boot_cleanup_unloads_the_client():
    """``boot_for_tui``'s cleanup frees the weights as part of teardown.
    Pinned because the failure is invisible: everything still works, the
    memory just never comes back."""
    import inspect
    source = inspect.getsource(main.boot_for_tui)
    cleanup = source[source.index("def cleanup()"):]
    assert "client.unload()" in cleanup


def test_unload_local_brain_clears_the_pipeline(monkeypatch):
    """The pipeline's own reference is one of the ones pinning the
    weights — clearing it is part of the release, not the caller's job."""
    client = _local_client()
    monkeypatch.setitem(main._pipeline, "client", client)

    assert main.unload_local_brain() is True
    assert main._pipeline.get("client") is None
    assert client.llm is None


def test_apply_live_model_unloads_local_when_switching_to_cloud(
        tmp_path, monkeypatch):
    """ARES picks a cloud model, configure_model writes the file, then
    re-attaches to this process. Without a hot swap the local MLX/GGUF
    stays in VRAM and keeps answering. The switch must unload first."""
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import dump_yaml

    layout = InstanceLayout(root=tmp_path)
    layout.root.mkdir(parents=True, exist_ok=True)
    dump_yaml(layout.config_path, _cloud_config())

    local = _local_client()
    monkeypatch.setitem(main._pipeline, "layout", layout)
    monkeypatch.setitem(main._pipeline, "client", local)
    monkeypatch.setitem(main._pipeline, "llm_lock", None)
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {
        "desktop-app": SimpleNamespace(messages=[1], system_prompt="old"),
    })
    released: list[bool] = []
    monkeypatch.setattr(
        main, "unload_local_brain",
        lambda client=None: released.append(True) or True,
    )
    cloud = SimpleNamespace(
        kind="external", provider="ollama-cloud", model_name="gemma4:31b")
    monkeypatch.setattr(main, "make_client", lambda *a, **k: cloud)
    monkeypatch.setattr(main, "build_system_prompt", lambda _layout: "PROMPT")

    assert main.apply_live_model() is True
    assert released == [True]
    assert main._pipeline["client"] is cloud
    assert main._jaeger_agents_by_session == {}
