"""Jaeger web app surface, served by the Gateway on 127.0.0.1:8790 (R11).

Folded from the Hermes WebUI fork: the Jaeger-authored route modules moved
here unchanged, the vendored Hermes server/config/session code was archived,
and the few ``/api/*`` routes that still lean on it were rewritten in
``workspace_api``. The modules import each other as ``api.<name>`` (their
original package name); that name is aliased to this package.
"""
import sys as _sys

_sys.modules.setdefault("api", _sys.modules[__name__])
