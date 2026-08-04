"""{{package_name}}.config — this module's own settings-catalog schema
slice.

"The module IS the engine" — its config schema lives beside its node
code, not centralized in some host project's schemas.py. If this module
gets nested into a host's central Config model (as
``Config.{{package_name}}``, one line on the host side), the settings-catalog
walk renders this group automatically — zero catalog-side edits, matching
module.yaml's ``config: {{package_name}}`` pointer.

Copy to config.py (drop the .example suffix) and replace the example
field with your module's real settings, or delete this file entirely (and
the ``config:`` line in module.yaml) if this module has nothing to
configure.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class {{PackageName}}Config(BaseModel):
    """Settings-catalog-visible defaults for the ``{{package_name}}``
    module. Every field here shows up under the ``{{package_name}}`` group
    the moment this model is nested into a host Config — see the module
    docstring."""

    model_config = ConfigDict(extra="forbid")

    example_setting: str = Field(
        "default_value",
        description=(
            "Replace with a real setting this module needs. Keep the "
            "description accurate to what the code actually reads — "
            "see CONVENTIONS.md 'No spec ahead of code'."
        ),
    )


__all__ = ["{{PackageName}}Config"]
