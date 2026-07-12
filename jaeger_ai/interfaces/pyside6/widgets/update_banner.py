"""``UpdateBanner`` — a drop-in "update available" widget for any Qt window.

Add it to any layout and it does the rest: an off-thread GitHub check on
:meth:`start`, then — only when a newer release exists — it reveals a banner
with an **Update now** button. The button runs ``jaeger update`` in an
:class:`UpdateDialog` that streams the download/apply output and prompts to
restart. Hidden when up to date / offline.

    from jaeger_os.interfaces.pyside6.widgets.update_banner import UpdateBanner
    layout.addWidget(UpdateBanner())          # self-checks, self-installs

Reusable knobs:
- ``auto_start=False`` — don't check on construction; call ``start()`` yourself
  (or feed a status dict to ``set_status`` — handy for tests / a shared check).
- ``run_default=False`` — clicking only emits ``updateRequested`` (the host
  drives the action); otherwise the built-in update dialog opens.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


def _jaeger_exe() -> Path:
    """The install's ``jaeger`` (venv console script, else the wrapper)."""
    from jaeger_ai.core.instance.instance import PACKAGE_ROOT
    home = PACKAGE_ROOT.parent
    venv = home / ".venv" / "bin" / "jaeger"
    return venv if venv.exists() else home / "jaeger"


class _CheckThread(QThread):
    """Off-main-thread "newer release?" probe — never blocks the UI. Emits the
    ``version_check.update_status`` dict (or ``None`` on any error)."""

    done = Signal(object)

    def run(self) -> None:  # noqa: D401 — QThread entry
        try:
            from jaeger_ai.core.version_check import update_status
            self.done.emit(update_status())
        except Exception:  # noqa: BLE001 — best-effort; never crash the UI
            self.done.emit(None)


class UpdateDialog(QDialog):
    """Runs ``jaeger update`` (optionally pinned to ``target``) via ``QProcess``,
    streaming output into a log. On success, prompts to restart. Cross-platform,
    in-app — no terminal spawn."""

    def __init__(self, jaeger_exe: Path, target: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Update Jaeger → {target}" if target else "Update Jaeger")
        self.resize(640, 400)
        v = QVBoxLayout(self)
        self._status = QLabel(
            f"Downloading + applying {target or 'the latest release'}… "
            "your agents and their data are preserved.")
        self._status.setWordWrap(True)
        v.addWidget(self._status)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet("font-family: monospace; font-size: 12px;")
        v.addWidget(self._log, 1)
        self._close = QPushButton("Close")
        self._close.clicked.connect(self.accept)
        v.addWidget(self._close)
        self._start_update(jaeger_exe, target)

    def _start_update(self, jaeger_exe: Path, target: str) -> None:
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        args = ["update", *(["--ref", target] if target else [])]
        self._proc.start(str(jaeger_exe), args)

    def _on_output(self) -> None:
        text = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        if text.strip():
            self._log.appendPlainText(text.rstrip())

    def _on_finished(self, code: int, _status) -> None:
        if code == 0:
            self._status.setText("✓ Update applied — restart Jaeger to load the "
                                 "new version.")
        else:
            self._status.setText(f"Update exited {code} — see the log. "
                                 "`jaeger update --rollback` reverts.")


class UpdateBanner(QFrame):
    """Drop-in update-available banner. Hidden until a newer release is found."""

    updateRequested = Signal(str)   # emitted on click with the target version

    def __init__(self, parent=None, *, auto_start: bool = True,
                 run_default: bool = True) -> None:
        super().__init__(parent)
        self._run_default = run_default
        self._latest = ""
        self._thread: _CheckThread | None = None
        self.setObjectName("UpdateBanner")
        self.setStyleSheet(
            "#UpdateBanner{background:rgba(70,90,160,0.95);}"
            "#UpdateBanner QLabel{color:#eef2ff;font-weight:600;}"
            "#UpdateBanner QPushButton{color:#0b1020;background:#eef2ff;"
            "border:none;border-radius:6px;padding:5px 14px;font-weight:700;}")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(12)
        self._label = QLabel("")
        row.addWidget(self._label)
        row.addStretch(1)
        self._btn = QPushButton("Update now")
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._on_click)
        row.addWidget(self._btn)
        self.setVisible(False)
        if auto_start:
            self.start()

    def start(self) -> None:
        """Kick the off-thread version check (idempotent enough — one thread)."""
        self._thread = _CheckThread(self)
        self._thread.done.connect(self.set_status)
        self._thread.start()

    def set_status(self, st) -> None:
        """Apply an update-status dict (``version_check.update_status`` shape).
        Reveals the banner only on a real newer release; hides otherwise."""
        if isinstance(st, dict) and st.get("available"):
            self._latest = st.get("latest") or ""
            self._label.setText(
                f"Update available — {self._latest} "
                f"(you're on {st.get('current', '?')}).")
            self.setVisible(True)
        else:
            self.setVisible(False)

    def _on_click(self) -> None:
        self.updateRequested.emit(self._latest)
        if self._run_default:
            UpdateDialog(_jaeger_exe(), self._latest, self.window()).exec()


__all__ = ["UpdateBanner", "UpdateDialog"]
