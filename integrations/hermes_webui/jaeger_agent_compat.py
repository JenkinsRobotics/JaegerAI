"""Narrow compatibility fixes for the deployed Hermes + Ollama cloud lane."""
from functools import wraps


def install(agent_class):
    original = getattr(agent_class, "_should_treat_stop_as_truncated", None)
    if original is None or getattr(original, "_jaeger_cloud_stop_fix", False):
        return agent_class

    @wraps(original)
    def should_truncate(self, finish_reason, assistant_message, messages=None):
        # A cloud `stop` is not evidence of truncation. Lists, file paths, and
        # code often end without sentence punctuation. Replaying complete
        # answers four times eventually raised a false WebUI error. Genuine
        # provider `length` signals still use Hermes' existing recovery path.
        if (finish_reason == "stop" and str(getattr(self, "model", "")).endswith(":cloud")
                and self._is_ollama_glm_backend()):
            return False
        return original(self, finish_reason, assistant_message, messages)

    should_truncate._jaeger_cloud_stop_fix = True
    agent_class._should_treat_stop_as_truncated = should_truncate
    return agent_class
