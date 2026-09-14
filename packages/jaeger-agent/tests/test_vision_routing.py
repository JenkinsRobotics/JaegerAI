"""The projector must not defeat text-prefix caching on the shared model."""
from types import SimpleNamespace

from jaeger_agent.core.engine import vis_mod


def setup_handler():
    calls = []

    class Vision:
        _exit_stack = object()

        def _init_mtmd_context(self, llama):
            calls.append("prewarm-projector")

        def __call__(self, **kwargs):
            calls.append(("vision", kwargs))
            return "vision"

    def text(**kwargs):
        calls.append(("text", kwargs))
        return "text"

    llama = SimpleNamespace(chat_format="gemma", _chat_handlers={"gemma": text},
                            reset=lambda: calls.append("reset"),
                            _ctx=SimpleNamespace(kv_cache_clear=lambda: calls.append("clear")))
    return vis_mod.ModalityAwareChatHandler(Vision()), llama, calls


def test_text_keeps_tools_and_reuses_original_formatter_without_reset():
    handler, llama, calls = setup_handler()
    messages = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "function": {"name": "calculate"}}]
    for _ in range(2):
        assert handler(llama=llama, messages=messages, tools=tools, temperature=0.0) == "text"
    assert "reset" not in calls and "clear" not in calls
    assert calls[1][1]["messages"] is messages
    assert calls[1][1]["tools"] is tools
    assert calls[1][1]["llama"] is llama


def test_image_in_prior_turn_keeps_vision_context():
    handler, llama, calls = setup_handler()
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}]},
                {"role": "assistant", "content": "red square"},
                {"role": "user", "content": "What color was it?"}]
    assert handler(llama=llama, messages=messages) == "vision"
    assert calls[0][0] == "vision"


def test_leaving_media_history_invalidates_synthetic_positions_only_once():
    handler, llama, calls = setup_handler()
    handler(llama=llama, messages=[{"content": [{"type": "image_url"}]}])
    handler(llama=llama, messages=[{"content": "fresh session"}])
    handler(llama=llama, messages=[{"content": [{"type": "text", "text": "next"}]}])
    assert calls.count("reset") == calls.count("clear") == 1


def test_wrapper_keeps_projector_cleanup_contract():
    handler, _, _ = setup_handler()
    assert handler._exit_stack is handler.vision._exit_stack


def test_standalone_constructor_uses_gguf_template_not_generic_fallback():
    handler, llama, calls = setup_handler()
    llama._chat_handlers["chat_template.default"] = llama._chat_handlers.pop("gemma")
    llama.chat_format = "llama-2"
    assert handler(llama=llama, messages=[{"content": "hello"}]) == "text"
    assert calls[-1][0] == "text"


def test_missing_text_template_keeps_original_vision_semantics():
    handler, llama, _ = setup_handler()
    llama._chat_handlers.clear()
    assert handler(llama=llama, messages=[{"content": "hello"}]) == "vision"


def test_media_reuses_only_exact_leading_text_and_still_decodes_every_image():
    import numpy as np

    calls = []
    llama = SimpleNamespace(n_tokens=5, input_ids=np.array([1, 2, 3, 99, 99] + [0] * 30))
    llama._ctx = SimpleNamespace(
        ctx=object(), kv_cache_clear=lambda: calls.append("clear"),
        kv_cache_seq_rm=lambda *args: calls.append(("trim", args)) or True,
    )
    llama.reset = lambda: setattr(llama, "n_tokens", 0)

    def evaluate(tokens):
        calls.append(("eval", list(tokens)))
        start = llama.n_tokens
        llama.input_ids[start:start + len(tokens)] = tokens
        llama.n_tokens += len(tokens)

    llama.eval = evaluate

    class Vision:
        def __call__(self, *, llama, **kwargs):
            llama.reset()
            llama._ctx.kv_cache_clear()
            assert llama.n_tokens == 0
            llama.eval([1, 2, 3, 4])
            assert llama.n_tokens == 4
            assert llama._ctx.ctx is not None
            calls.append("decode-image")
            llama.n_tokens += 8
            llama.eval([5, 6])
            return "seen"

    handler = vis_mod.ModalityAwareChatHandler(Vision())
    media = [{"content": [{"type": "image_url"}]}]
    assert handler(llama=llama, messages=media) == "seen"
    assert ("eval", [4]) in calls
    assert ("eval", [1, 2, 3, 4]) not in calls
    calls.clear()
    # The second call may reuse four text tokens, never the image positions.
    assert handler(llama=llama, messages=media) == "seen"
    assert calls == [("trim", (0, 4, -1)), "decode-image", ("eval", [5, 6])]


def test_image_without_a_leading_text_chunk_clears_before_native_decode():
    import numpy as np

    calls = []
    llama = SimpleNamespace(n_tokens=3, input_ids=np.array([1, 2, 3]))
    llama._ctx = SimpleNamespace(ctx="native", kv_cache_clear=lambda: calls.append("clear"),
                                 kv_cache_seq_rm=lambda *args: True)
    llama.reset = lambda: calls.append("reset") or setattr(llama, "n_tokens", 0)
    proxy = vis_mod._PrefixLlama(llama, 3)
    proxy.reset()
    proxy._ctx.kv_cache_clear()
    assert calls == []
    assert proxy._ctx.ctx == "native"
    assert calls == ["reset", "clear"]
    assert llama.n_tokens == 0


def test_prefix_mismatch_or_failed_native_trim_falls_back_to_full_evaluation():
    import numpy as np

    for tokens, trim in [([7, 8], True), ([1, 8], False)]:
        calls = []
        llama = SimpleNamespace(n_tokens=2, input_ids=np.array([1, 2]))
        llama._ctx = SimpleNamespace(kv_cache_clear=lambda: calls.append("clear"),
                                     kv_cache_seq_rm=lambda *args: trim)
        llama.reset = lambda: calls.append("reset") or setattr(llama, "n_tokens", 0)
        llama.eval = lambda value: calls.append(("eval", list(value)))
        proxy = vis_mod._PrefixLlama(llama, 2)
        proxy.reset()
        proxy._ctx.kv_cache_clear()
        proxy.eval(tokens)
        assert calls == ["reset", "clear", ("eval", tokens)]
