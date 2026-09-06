"""Restore native SessionDB history at Hermes' Runs execution boundary.

The upstream Runs endpoint supplies an empty conversation_history on every
request unless the caller sends one. Unlike native session-chat, that loses
context. Load native structured messages inside the worker, not flattened
peer transcripts or client-provided history. The native agent still owns its
durable turn lease, compression, tool messages and persistence.
"""
from functools import wraps


def resumable_adapter(base):
    class ResumableAPI(base):
        def _create_agent(self, *args, **kwargs):
            session = kwargs.get("session_id")
            db = self._ensure_session_db() if session else None
            if session and db is None:
                raise RuntimeError("Native session database unavailable; refusing a contextless turn")
            if db is not None:
                session = db.resolve_resume_session_id(session) or session
                kwargs["session_id"] = session
            agent = super()._create_agent(*args, **kwargs)
            original = agent.run_conversation

            @wraps(original)
            def run(*run_args, **run_kwargs):
                if session and not run_kwargs.get("conversation_history"):
                    # Keep tool-call IDs and compression metadata intact. Do
                    # not pass this through the Runs JSON history normalizer,
                    # which retains only role/content. DB failure propagates;
                    # an empty fallback would silently erase conversation scope.
                    run_kwargs["conversation_history"] = db.get_messages_as_conversation(session)
                return original(*run_args, **run_kwargs)

            agent.run_conversation = run
            return agent
    return ResumableAPI
