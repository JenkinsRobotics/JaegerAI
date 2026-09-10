"""Product classification for Config leaves outside the generic catalog.

All mutable configuration is catalog-driven. ``instance_name`` alone is an
immutable identity key managed by the instance lifecycle UI.
"""

NONCATALOG_EXPOSURE = {
    "instance_name": "dedicated_ui",
}

__all__ = ["NONCATALOG_EXPOSURE"]
