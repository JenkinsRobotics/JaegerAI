"""WebUI service package.

Manages WebUI runtime lifecycle, profile layout, and session unification.
"""
from .service import HermesWebUIService, hermes_webui_urls
from .profile_layout import (
    PROFILE_DISPLAY_NAMES,
    profile_display_name,
    library_model,
    ensure_webui_profile_layout,
    link_shared_profiles,
    ensure_agent_state_schema,
    prepare_vendor_webui_home,
)
from .session_unify import (
    normalize_session_profile,
    infer_session_profile,
    profile_badge_for_session,
    reconcile_keep,
    import_keep,
)

__all__ = [
    "HermesWebUIService",
    "hermes_webui_urls",
    "PROFILE_DISPLAY_NAMES",
    "profile_display_name",
    "library_model",
    "ensure_webui_profile_layout",
    "link_shared_profiles",
    "ensure_agent_state_schema",
    "prepare_vendor_webui_home",
    "normalize_session_profile",
    "infer_session_profile",
    "profile_badge_for_session",
    "reconcile_keep",
    "import_keep",
]
