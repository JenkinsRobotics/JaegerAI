"""Interface surfaces (TUI, PySide6 widgets, Swift bridge, …).

The unshipped Qt surfaces (studio, gallery, media_player, dev_launcher,
v4) live under ``jaeger-studio/interfaces`` in the repo — outside the
shipped ``jaeger_os`` package — but still import as
``jaeger_os.interfaces.*`` (their internal imports and the
``jaeger dev --dev-gui`` launcher use that name). When that staging
directory exists next to this package (a dev checkout), it is appended
to this package's search path so those imports resolve; in a shipped
install it is absent and this is a no-op.
"""

from pathlib import Path as _Path

_studio_interfaces = (
    _Path(__file__).resolve().parent.parent.parent / "jaeger-studio" / "interfaces"
)
if _studio_interfaces.is_dir():
    __path__.append(str(_studio_interfaces))
del _Path, _studio_interfaces
