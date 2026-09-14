"""Optional non-agentic baseline: Gemma E4B plus an eight-exchange log.

The packaged engine uses an injected ``AgentRuntime`` by default.  This node
exists only for offline comparison with the original VoiceLLM playground.
"""
from __future__ import annotations

from pathlib import Path

try:  # packaged engine
    from jaeger_agent.core.policy import LLM_MODEL_PATH
except ImportError:  # portable node folder loaded by the playground
    from policy import LLM_MODEL_PATH


class BrainGemma:
    MAX_TOKENS = 160
    MAX_MESSAGES = 16               # 8 exchanges

    def __init__(self) -> None:
        self.llm = None
        self.history: list[dict] = []

    def load(self, chat_handler=None, say=print,
             *, model_path: str | Path = LLM_MODEL_PATH) -> None:
        from llama_cpp import Llama
        path = Path(model_path).expanduser()
        say(f"loading {path.name}…")
        kw = dict(model_path=str(path), n_ctx=4096,
                  n_gpu_layers=-1, verbose=False)
        if chat_handler is not None:
            kw["chat_handler"] = chat_handler
        self.llm = Llama(**kw)
        self.llm.create_chat_completion(
            messages=[{"role": "user", "content": "hi"}], max_tokens=1)

    def answer(self, content, system: str) -> str:
        out = self.llm.create_chat_completion(
            messages=[{"role": "system", "content": system},
                      *self.history,
                      {"role": "user", "content": content}],
            max_tokens=self.MAX_TOKENS, temperature=0.7)
        return (out["choices"][0]["message"]["content"] or "").strip()

    def remember(self, user_text: str, reply: str) -> None:
        """There is no built-in memory: the log IS the context."""
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        if len(self.history) > self.MAX_MESSAGES:
            self.history = self.history[-self.MAX_MESSAGES:]

    def clear(self) -> None:
        self.history.clear()


def build():
    return BrainGemma()
