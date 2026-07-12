"""Agent-centric settings HUD — the game-profile layout, wired to real data.

Left icon rail flips pages; the agent avatar sits on the right; each page edits a
real slice of the running agent and persists it:

  Home         — read-only overview (name + trait bars)
  Character    — soul / backstory / role / custom-instructions -> character.yaml
  Traits       — the trait-layer sliders -> save_character_traits()
  App Settings — real Config fields -> config.yaml (Pydantic-validated)
  Permissions  — system permission mode + per-skill grants (permissions.json)

Bottom-left rail button connects to Jaeger Studio (the advanced app).
Character/trait edits take effect on the agent's next turn (signature reload);
app/config changes follow the usual restart contract.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from jaeger_ai.interfaces.avatar_player.window import (
    AvatarView, agent_name, resolve_character, show_card, wire_avatar_frames,
)

# ── palette (from the reference: near-black + green accent) ────────────
_BG = "#0C100E"
_PANEL = "#141A17"
_FIELD = "#0E1512"
_STROKE = "#233029"
_INK = "#E8EFEA"
_INK_DIM = "#7C8A81"
_ACCENT = "#43E08A"

_SAMPLE = [("Force Attack", 0.6), ("Magic Attack", 0.4), ("Shield Defense", 0.75),
           ("Control", 0.9), ("Stamina", 0.3), ("Endurance", 0.55)]
_TRAIT_LAYERS = ("hexaco", "special", "expression", "domains")

# 3-letter trait abbreviations for the library-card stat row (from Studio).
_TRAIT_SHORT = {
    "openness": "OPEN", "conscientiousness": "DISC", "extraversion": "EXTR",
    "agreeableness": "AGRE", "neuroticism": "NEUR", "honesty_humility": "HON",
    "strength": "STR", "perception": "PER", "endurance": "END", "charisma": "CHA",
    "intelligence": "INT", "agility": "AGI", "luck": "LCK",
    "sarcasm": "SARC", "warmth": "WARM", "verbosity": "VERB", "formality": "FORM",
    "directness": "DIR", "humor": "HUM", "empathy": "EMP", "aggression": "AGGR",
    "science": "SCI", "philosophy": "PHIL", "combat": "CMBT", "art": "ART",
    "politics": "POL", "technology": "TECH", "nature": "NAT", "psychology": "PSY",
}


def _f(v: Any) -> float:
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return 0.0


_ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h5v-6h4v6h5V9.5"/>',
    "library": ('<rect x="3.5" y="3.5" width="7" height="7" rx="1.4"/>'
                '<rect x="13.5" y="3.5" width="7" height="7" rx="1.4"/>'
                '<rect x="3.5" y="13.5" width="7" height="7" rx="1.4"/>'
                '<rect x="13.5" y="13.5" width="7" height="7" rx="1.4"/>'),
    "character": ('<circle cx="12" cy="8" r="3.4"/>'
                  '<path d="M5 20c0-3.5 3-5.6 7-5.6s7 2.1 7 5.6"/>'),
    "traits": '<path d="M4 20V10M10 20V4M16 20v-8M22 20V7"/>',
    "app": ('<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/>'
            '<path d="M1 14h6M9 8h6M17 16h6"/>'),
    "permissions": '<path d="M12 3l8 3v5c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6z"/>',
    "studio": ('<path d="M9 15l6-6"/><path d="M10.5 6.5 12 5a4 4 0 0 1 6 6l-1.5 1.5"/>'
               '<path d="M13.5 17.5 12 19a4 4 0 0 1-6-6l1.5-1.5"/>'),
}
_WRAP = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
         'stroke="{c}" stroke-width="1.7" stroke-linecap="round" '
         'stroke-linejoin="round">{p}</svg>')


def _icon(name: str, color: str = _INK_DIM, size: int = 22) -> QIcon:
    r = QSvgRenderer(QByteArray(_WRAP.format(c=color, p=_ICONS[name]).encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


class StatBar(QWidget):
    """Segmented level bar (green filled / dim empty), à la the reference."""

    def __init__(self, value: float, segments: int = 14):
        super().__init__()
        self._v = max(0.0, min(1.0, value))
        self._n = segments
        self.setFixedHeight(10)
        self.setMinimumWidth(120)

    def paintEvent(self, e: Any) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        gap = 3
        w = (self.width() - (self._n - 1) * gap) / self._n
        filled = round(self._v * self._n)
        for i in range(self._n):
            p.setBrush(QColor(_ACCENT if i < filled else _STROKE))
            p.drawRoundedRect(QRectF(i * (w + gap), 0, w, self.height()), 2, 2)
        p.end()


_REV_QSS = ("background: rgba(0,0,0,0.45); color:#B8B3D0; font-size:10px;"
            " font-weight:700; border-radius:8px; padding:2px 7px;")
_LV_QSS = (f"background: rgba(67,224,138,0.95); color:#05140C; font-size:11px;"
           f" font-weight:800; border-radius:9px; padding:3px 9px;")
_BTN_SELECT = (f"QPushButton{{background:{_ACCENT}; color:#05140C; border:none;"
               f" border-radius:9px; padding:10px; font-weight:800; font-size:12px;}}"
               f" QPushButton:hover{{background:#5CEBA0;}}")
_BTN_ACTIVE = (f"QPushButton{{background:#2A6B49; color:{_INK}; border:none;"
               f" border-radius:9px; padding:10px; font-weight:800; font-size:12px;}}")
_BTN_DEFAULT = (f"QPushButton{{background:{_FIELD}; color:{_INK};"
                f" border:1px solid {_STROKE}; border-radius:9px; padding:10px;"
                f" font-weight:800; font-size:12px;}}"
                f" QPushButton:hover{{border:1px solid {_ACCENT};}}"
                f" QPushButton:disabled{{color:{_ACCENT}; border:1px solid {_ACCENT};}}")


class LibraryCard(QFrame):
    """Character-library card — art fill + rev/level badges + top-3 stats over a
    bottom gradient, with SELECT (play it) + MAKE DEFAULT (bind it)."""

    CARD_W, CARD_H = 276, 356

    def __init__(self, character: Any, *, active: bool, bound: bool,
                 on_select: Any, on_default: Any) -> None:
        super().__init__()
        self._char = character
        self._active = active
        self.setFixedSize(self.CARD_W, self.CARD_H)
        cp = character.card_path()
        self._pix = QPixmap(str(cp)) if cp is not None else None

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 16)
        v.setSpacing(3)
        top = QHBoxLayout()
        rev = QLabel(f"rev {character.revision:.1f}")
        rev.setStyleSheet(_REV_QSS)
        top.addWidget(rev)
        top.addStretch(1)
        lv = QLabel(f"Lv {character.level}")
        lv.setStyleSheet(_LV_QSS)
        top.addWidget(lv)
        v.addLayout(top)
        v.addStretch(1)

        nm = QLabel(character.name.upper())
        nm.setStyleSheet(f"color:{_INK}; font-size:19px; font-weight:800;")
        v.addWidget(nm)
        role = QLabel(character.role or "—")
        role.setStyleSheet("color:#C9C4E0; font-size:11px;")
        role.setMaximumWidth(self.CARD_W - 34)
        v.addWidget(role)
        v.addSpacing(4)
        v.addLayout(self._stats_row())
        v.addSpacing(9)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        sel = QPushButton("✓ SELECTED" if active else "SELECT")
        sel.setStyleSheet(_BTN_ACTIVE if active else _BTN_SELECT)
        sel.setCursor(Qt.CursorShape.PointingHandCursor)
        sel.clicked.connect(lambda: on_select(character))
        mk = QPushButton("★ DEFAULT" if bound else "MAKE DEFAULT")
        mk.setStyleSheet(_BTN_DEFAULT)
        mk.setEnabled(not bound)
        mk.setCursor(Qt.CursorShape.PointingHandCursor)
        mk.clicked.connect(lambda: on_default(character))
        btns.addWidget(sel, 3)
        btns.addWidget(mk, 3)
        v.addLayout(btns)

    def _stats_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        for short, val in self._defining_traits():
            col = QVBoxLayout()
            col.setSpacing(0)
            s = QLabel(short)
            s.setStyleSheet("color:#A29DC0; font-size:9px; font-weight:700;")
            n = QLabel(str(val))
            n.setStyleSheet(f"color:{_INK}; font-size:14px; font-weight:800;")
            col.addWidget(s)
            col.addWidget(n)
            row.addLayout(col)
        row.addStretch(1)
        return row

    def _defining_traits(self) -> list[tuple[str, int]]:
        from jaeger_ai.personality.character import layer_items
        allt: list = []
        for layer in _TRAIT_LAYERS:
            sub = getattr(self._char.personality, layer, None)
            if sub is not None:
                allt += layer_items(sub)
        top = sorted(allt, key=lambda kv: abs(_f(kv[1]) - 0.5), reverse=True)[:3]
        return [(_TRAIT_SHORT.get(k, k[:4].upper()), int(round(_f(v) * 100)))
                for k, v in top]

    def paintEvent(self, e: Any) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rf = QRectF(self.rect().adjusted(0, 0, -1, -1))
        path = QPainterPath()
        path.addRoundedRect(rf, 16, 16)
        p.setClipPath(path)
        if self._pix is not None and not self._pix.isNull():
            sc = self._pix.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
            sx = max(0, (sc.width() - self.width()) // 2)
            sy = max(0, (sc.height() - self.height()) // 2)
            p.drawPixmap(0, 0, sc, sx, sy, self.width(), self.height())
        else:
            p.fillRect(rf, QColor(_PANEL))
        grad = QLinearGradient(0, self.height() * 0.32, 0, self.height())
        grad.setColorAt(0.0, QColor(8, 12, 10, 0))
        grad.setColorAt(0.55, QColor(8, 12, 10, 205))
        grad.setColorAt(1.0, QColor(8, 12, 10, 248))
        p.fillRect(rf, QBrush(grad))
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(_ACCENT) if self._active else QColor(_STROKE),
                      2 if self._active else 1))
        p.drawRoundedRect(rf, 16, 16)
        p.end()


def _traits(character: Any) -> list[tuple[str, float]]:
    """Flatten the personality's numeric trait leaves (0..1) → (name, value)."""
    if character is None:
        return []
    import msgspec

    def leaves(obj: Any, name: str = ""):
        try:
            obj = msgspec.structs.asdict(obj)
        except Exception:  # noqa: BLE001 — not a struct
            pass
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from leaves(v, k)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            if 0.0 <= float(obj) <= 1.0:
                yield (name.replace("_", " "), float(obj))

    try:
        return list(leaves(character.personality))[:12]
    except Exception:  # noqa: BLE001
        return []


class AgentSettingsWindow(QWidget):
    NAV = [("home", "Home"), ("library", "Library"), ("character", "Character"),
           ("traits", "Traits"), ("app", "App Settings"), ("permissions", "Permissions")]

    def __init__(self, ctx: Any = None) -> None:
        super().__init__()
        self.ctx = ctx
        self._lay: Any = None
        self.character = resolve_character(ctx)
        # The AGENT's own name (identity.yaml) — never the character. This
        # window title / panel heading / dashboard heading represent the
        # agent, not the persona it's playing (that's shown, labeled, only
        # on the Character/Library tabs).
        self._name = agent_name(ctx)
        self._studio: Any = None
        self._trait_sliders: dict[tuple[str, str], QSlider] = {}

        self.setObjectName("AgentSettings")
        self.setWindowTitle(f"JROS — {self._name} · settings")
        self.resize(1080, 680)
        self.setStyleSheet(_QSS)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._rail())
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)
        root.addWidget(self._agent_panel())

        self._bound_id = self._id_via("bound_character_id")
        self._active_id = self._id_via("active_character_id")
        self._index: dict[str, int] = {}
        self._build_pages()

    def _id_via(self, fn_name: str) -> Any:
        """The instance's bound (default) or active character id, else current."""
        try:
            import jaeger_ai.personality.character as ch
            root = getattr(self._inst_layout(), "root", None)
            if root is not None:
                cid = getattr(ch, fn_name)(root)
                if cid:
                    return cid
        except Exception:  # noqa: BLE001
            pass
        return self.character.id if self.character else None

    def _build_pages(self, current: str = "Home") -> None:
        """(Re)build every page — called on init and when the agent switches, so
        the Character/Traits tabs always edit the selected character."""
        self._trait_sliders = {}
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        builders = {
            "home": self._home_page, "library": self._library_page,
            "character": self._character_page, "traits": self._traits_page,
            "app": self._app_page, "permissions": self._permissions_page,
        }
        self._index = {}
        for key, label in self.NAV:
            try:
                page = builders[key]()
            except Exception as exc:  # noqa: BLE001 — a broken page must not kill the window
                page = self._error_page(label, exc)
            self._index[label] = self._stack.addWidget(page)
        self._go(current)

    def _switch_character(self, ch: Any, goto: str = "Library") -> None:
        """Retarget the whole app to a character — panel + all editable tabs.
        The agent's own name (``self._name``) never changes on a persona
        switch, so the panel heading is left alone; only the avatar/pages
        retarget to the new character."""
        self.character = ch
        show_card(self._avatar, ch)
        self._build_pages(goto)

    # ── left rail ──
    def _rail(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Rail")
        bar.setFixedWidth(66)
        v = QVBoxLayout(bar)
        v.setContentsMargins(9, 16, 9, 16)
        v.setSpacing(6)
        self._railbtns: dict[str, QPushButton] = {}
        for key, label in self.NAV:
            b = QPushButton()
            b.setObjectName("RailBtn")
            b.setCheckable(True)
            b.setIcon(_icon(key))
            b.setIconSize(QSize(22, 22))
            b.setToolTip(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, la=label: self._go(la))
            v.addWidget(b)
            self._railbtns[label] = b
        self._railbtns["Home"].setChecked(True)
        v.addStretch(1)
        connect = QPushButton()
        connect.setObjectName("RailConnect")
        connect.setIcon(_icon("studio", color=_ACCENT, size=24))
        connect.setIconSize(QSize(24, 24))
        connect.setToolTip("Jaeger Studio — coming soon")
        connect.setCursor(Qt.CursorShape.PointingHandCursor)
        connect.clicked.connect(self._connect_studio)
        v.addWidget(connect, 0, Qt.AlignmentFlag.AlignHCenter)
        return bar

    def _go(self, label: str) -> None:
        self._stack.setCurrentIndex(self._index[label])
        for la, b in self._railbtns.items():
            b.setChecked(la == label)

    # ── right agent panel ──
    def _agent_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("AgentPanel")
        panel.setFixedWidth(320)
        v = QVBoxLayout(panel)
        v.setContentsMargins(20, 24, 20, 24)
        v.setSpacing(12)
        nm = QLabel(self._name.upper())
        nm.setObjectName("PanelName")
        self._panel_name = nm
        v.addWidget(nm)
        self._avatar = AvatarView()
        v.addWidget(self._avatar, 1)
        show_card(self._avatar, self.character)
        self._bridge = wire_avatar_frames(self._avatar, self.ctx)
        return panel

    # ── page scaffolding ──
    def _page(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(40, 32, 30, 28)
        v.setSpacing(10)
        v.addWidget(self._section(title))
        v.addSpacing(6)
        return page, v

    def _scroll(self, inner: QWidget) -> QScrollArea:
        sc = QScrollArea()
        sc.setObjectName("Scroll")
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.Shape.NoFrame)
        sc.setWidget(inner)
        return sc

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text.upper())
        lab.setObjectName("Section")
        return lab

    def _field(self, label: str, widget: QWidget) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        cap = QLabel(label.upper())
        cap.setObjectName("FieldLabel")
        v.addWidget(cap)
        v.addWidget(widget)
        return box

    def _save_row(self, text: str, slot) -> tuple[QHBoxLayout, QLabel]:
        row = QHBoxLayout()
        status = QLabel("")
        status.setObjectName("SaveStatus")
        btn = QPushButton(text)
        btn.setObjectName("SaveBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        row.addWidget(status)
        row.addStretch(1)
        row.addWidget(btn)
        return row, status

    def _toast(self, status: QLabel, msg: str, error: bool = False) -> None:
        status.setStyleSheet(f"color: {'#FF6B6B' if error else _ACCENT};")
        status.setText(msg)
        QTimer.singleShot(4000, lambda: status.setText(""))

    def _error_page(self, title: str, exc: Exception) -> QWidget:
        page, v = self._page(title)
        lab = QLabel(f"Couldn't load {title.lower()} — {exc}")
        lab.setObjectName("Stub")
        lab.setWordWrap(True)
        v.addWidget(lab)
        v.addStretch(1)
        return page

    def _no_char_page(self, title: str) -> QWidget:
        page, v = self._page(title)
        lab = QLabel("No character is loaded for this instance.")
        lab.setObjectName("Stub")
        v.addWidget(lab)
        v.addStretch(1)
        return page

    # ── Home (overview only) ──
    def _home_page(self) -> QWidget:
        page, v = self._page("Dashboard")
        big = QLabel(self._name.upper())
        big.setObjectName("BigName")
        lvl = getattr(self.character, "level", 1) if self.character else 1
        sub = QLabel(f"LVL {lvl}  ·  agent overview")
        sub.setObjectName("Sub")
        v.itemAt(0).widget().deleteLater()   # drop the small section header
        v.insertWidget(0, big)
        v.insertWidget(1, sub)
        v.addWidget(self._section("Characteristics"))
        for name, frac in (_traits(self.character) or _SAMPLE):
            v.addLayout(self._trait_row(name, frac))
        v.addStretch(1)
        return page

    # ── Library (Studio-style card grid → Select / Make Default) ──
    def _library_page(self) -> QWidget:
        from jaeger_ai.personality.character import list_characters
        chars = list_characters()
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(36, 30, 30, 28)
        v.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(self._section("Character Library"))
        count = QLabel(f"·  {len(chars)} characters")
        count.setObjectName("Sub")
        head.addWidget(count)
        head.addStretch(1)
        v.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)
        for i, ch in enumerate(chars):
            card = LibraryCard(
                ch, active=(ch.id == self._active_id), bound=(ch.id == self._bound_id),
                on_select=self._select_character, on_default=self._make_default)
            grid.addWidget(card, i // 3, i % 3)
        grid.setColumnStretch(3, 1)
        v.addLayout(grid)
        v.addStretch(1)
        return self._scroll(inner)

    def _select_character(self, ch: Any) -> None:
        """SELECT — the instance plays this character now; tabs edit it."""
        from jaeger_ai.personality.character import set_active_character
        try:
            root = getattr(self._inst_layout(), "root", None)
            if root is not None:
                set_active_character(root, ch.id)
            self._active_id = ch.id
        except Exception:  # noqa: BLE001 — still retarget the UI
            pass
        self._switch_character(ch, goto="Library")

    def _make_default(self, ch: Any) -> None:
        """MAKE DEFAULT — bind as the instance's canonical character (+ active)."""
        from jaeger_ai.personality.character import bind_character
        try:
            root = getattr(self._inst_layout(), "root", None)
            if root is not None:
                bind_character(root, ch.id)
            self._bound_id = ch.id
            self._active_id = ch.id
        except Exception:  # noqa: BLE001
            pass
        self._switch_character(ch, goto="Library")

    def _trait_row(self, name: str, frac: float) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        lbl = QLabel(name.upper())
        lbl.setObjectName("TraitName")
        lbl.setFixedWidth(160)
        val = QLabel(f"LVL {max(1, round(frac * 15))}")
        val.setObjectName("TraitLvl")
        val.setFixedWidth(56)
        row.addWidget(lbl)
        row.addWidget(StatBar(frac), 1)
        row.addWidget(val)
        return row

    # ── Character (soul / bio / role / prompt) ──
    def _character_page(self) -> QWidget:
        if self.character is None:
            return self._no_char_page("Character")
        c = self.character
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(40, 32, 30, 28)
        v.setSpacing(12)
        v.addWidget(self._section("Character"))

        self._role_edit = QLineEdit(c.role)
        self._tone_edit = QLineEdit(c.voice_tone)
        self._voice_edit = QLineEdit(c.voice_id or "")
        self._voice_edit.setPlaceholderText("e.g. af_heart (blank = default)")
        self._soul_edit = QPlainTextEdit(c.soul)
        self._soul_edit.setMinimumHeight(90)
        self._back_edit = QPlainTextEdit(c.backstory)
        self._back_edit.setMinimumHeight(90)
        ci = getattr(c.personality, "custom_instructions", "")
        self._ci_edit = QPlainTextEdit(ci)
        self._ci_edit.setMinimumHeight(90)

        v.addWidget(self._field("Role", self._role_edit))
        row = QHBoxLayout()
        row.addWidget(self._field("Voice tone", self._tone_edit), 1)
        row.addWidget(self._field("Voice ID", self._voice_edit), 1)
        v.addLayout(row)
        v.addWidget(self._field("Soul (core narrative)", self._soul_edit))
        v.addWidget(self._field("Backstory", self._back_edit))
        v.addWidget(self._field("Custom instructions (prompt)", self._ci_edit))
        save, self._char_status = self._save_row("Save character", self._save_character)
        v.addLayout(save)
        v.addStretch(1)
        return self._scroll(inner)

    def _save_character(self) -> None:
        from jaeger_ai.personality.character import save_character_profile
        try:
            save_character_profile(
                self.character.root,
                role=self._role_edit.text().strip(),
                voice_tone=self._tone_edit.text().strip(),
                voice_id=self._voice_edit.text().strip() or None,
                soul=self._soul_edit.toPlainText(),
                backstory=self._back_edit.toPlainText(),
                custom_instructions=self._ci_edit.toPlainText())
            self._toast(self._char_status, "Saved ✓  agent picks it up next turn")
        except Exception as exc:  # noqa: BLE001
            self._toast(self._char_status, f"Error: {exc}", error=True)

    # ── Traits (sliders per layer) ──
    def _traits_page(self) -> QWidget:
        if self.character is None:
            return self._no_char_page("Traits")
        from jaeger_ai.personality.character import layer_items
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(40, 32, 30, 28)
        v.setSpacing(8)
        v.addWidget(self._section("Traits"))
        for layer in _TRAIT_LAYERS:
            sub = getattr(self.character.personality, layer, None)
            if sub is None:
                continue
            lab = QLabel(layer.upper())
            lab.setObjectName("LayerLabel")
            v.addWidget(lab)
            for key, val in layer_items(sub):
                v.addLayout(self._slider_row(layer, key, float(val)))
            v.addSpacing(6)
        save, self._trait_status = self._save_row("Save traits", self._save_traits)
        v.addLayout(save)
        v.addStretch(1)
        return self._scroll(inner)

    def _slider_row(self, layer: str, key: str, value: float) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        lbl = QLabel(key.replace("_", " ").upper())
        lbl.setObjectName("TraitName")
        lbl.setFixedWidth(160)
        sld = QSlider(Qt.Orientation.Horizontal)
        sld.setRange(0, 100)
        sld.setValue(round(value * 100))
        val = QLabel(f"{round(value * 100)}")
        val.setObjectName("TraitLvl")
        val.setFixedWidth(40)
        sld.valueChanged.connect(lambda n: val.setText(str(n)))
        self._trait_sliders[(layer, key)] = sld
        row.addWidget(lbl)
        row.addWidget(sld, 1)
        row.addWidget(val)
        return row

    def _save_traits(self) -> None:
        from jaeger_ai.personality.character import save_character_traits
        traits: dict[str, dict[str, float]] = {}
        for (layer, key), sld in self._trait_sliders.items():
            traits.setdefault(layer, {})[key] = sld.value() / 100.0
        try:
            save_character_traits(self.character.root, traits)
            self._toast(self._trait_status, "Saved ✓  agent picks it up next turn")
        except Exception as exc:  # noqa: BLE001
            self._toast(self._trait_status, f"Error: {exc}", error=True)

    # ── App Settings (real Config fields) ──
    def _app_page(self) -> QWidget:
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        lay = self._inst_layout()
        cfg = load_yaml(lay.config_path, Config)
        page, v = self._page("App Settings")

        self._default_mode = QComboBox()
        self._default_mode.addItems(["tui", "gui", "voice"])
        self._default_mode.setCurrentText(cfg.interaction.default_mode)
        self._ui_toolkit = QComboBox()
        self._ui_toolkit.addItems(["swift", "pyside6"])
        self._ui_toolkit.setCurrentText(cfg.interaction.ui)
        self._voice_enabled = QCheckBox("Voice input (mic) at boot")
        self._voice_enabled.setChecked(cfg.voice.enabled)
        self._speak_replies = QCheckBox("Speak replies (speaker) by default")
        self._speak_replies.setChecked(cfg.voice.speak_replies)
        self._show_latency = QCheckBox("Show latency")
        self._show_latency.setChecked(cfg.display.show_latency)
        self._show_tools = QCheckBox("Show tool activity")
        self._show_tools.setChecked(cfg.display.show_tool_activity)
        self._lazy = QCheckBox("Allow lazy installs")
        self._lazy.setChecked(cfg.security.allow_lazy_installs)
        self._idle_spin = QSpinBox()
        self._idle_spin.setRange(0, 240)
        self._idle_spin.setValue(cfg.deep_think.auto_idle_minutes)

        v.addWidget(self._field("Default interface", self._default_mode))
        v.addWidget(self._field("Windowed UI toolkit (restart to apply)", self._ui_toolkit))
        v.addWidget(self._field("Deep-think idle (minutes)", self._idle_spin))
        v.addWidget(self._voice_enabled)
        v.addWidget(self._speak_replies)
        v.addWidget(self._show_latency)
        v.addWidget(self._show_tools)
        v.addWidget(self._lazy)
        note = QLabel("Model, engine & voice-device changes take effect after "
                      "restarting the agent.")
        note.setObjectName("Note")
        note.setWordWrap(True)
        v.addWidget(note)
        save, self._app_status = self._save_row("Save settings", self._save_app)
        v.addLayout(save)
        v.addStretch(1)
        return page

    def _save_app(self) -> None:
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
        lay = self._inst_layout()
        cfg = load_yaml(lay.config_path, Config)  # fresh — preserve unexposed fields
        cfg.interaction.default_mode = self._default_mode.currentText()
        cfg.interaction.ui = self._ui_toolkit.currentText()
        cfg.voice.enabled = self._voice_enabled.isChecked()
        cfg.voice.speak_replies = self._speak_replies.isChecked()
        cfg.display.show_latency = self._show_latency.isChecked()
        cfg.display.show_tool_activity = self._show_tools.isChecked()
        cfg.security.allow_lazy_installs = self._lazy.isChecked()
        cfg.deep_think.auto_idle_minutes = self._idle_spin.value()
        try:
            cfg = Config.model_validate(cfg.model_dump())
            dump_yaml(lay.config_path, cfg)
            self._toast(self._app_status, "Saved ✓")
        except Exception as exc:  # noqa: BLE001
            self._toast(self._app_status, f"Invalid: {exc}", error=True)

    # ── Permissions (mode + per-skill grants) ──
    def _permissions_page(self) -> QWidget:
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        from jaeger_os.core.safety.permissions import PermissionGrants
        lay = self._inst_layout()
        cfg = load_yaml(lay.config_path, Config)
        page, v = self._page("Permissions")

        self._perm_mode = QComboBox()
        self._perm_mode.addItems(["confirm", "allow"])
        self._perm_mode.setCurrentText(cfg.permissions.mode)
        v.addWidget(self._field("System permission mode", self._perm_mode))
        desc = QLabel("confirm — ask before risky / system actions.\n"
                      "allow — auto-approve every action (full system access).")
        desc.setObjectName("Note")
        v.addWidget(desc)
        save, self._perm_status = self._save_row("Save mode", self._save_perms)
        v.addLayout(save)

        v.addSpacing(10)
        v.addWidget(self._section("Granted skills"))
        self._grants = PermissionGrants.load(lay.root)
        self._grants_box = QVBoxLayout()
        self._grants_box.setSpacing(6)
        v.addLayout(self._grants_box)
        self._populate_grants()
        v.addStretch(1)
        return page

    def _populate_grants(self) -> None:
        while self._grants_box.count():
            item = self._grants_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        skills = sorted(self._grants.persistent)
        if not skills:
            empty = QLabel("No skills have persistent access — each prompts on use.")
            empty.setObjectName("Stub")
            self._grants_box.addWidget(empty)
            return
        for skill in skills:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            name = QLabel(skill)
            name.setObjectName("GrantName")
            revoke = QPushButton("Revoke")
            revoke.setObjectName("RevokeBtn")
            revoke.setCursor(Qt.CursorShape.PointingHandCursor)
            revoke.clicked.connect(lambda _c=False, s=skill: self._revoke(s))
            h.addWidget(name)
            h.addStretch(1)
            h.addWidget(revoke)
            self._grants_box.addWidget(row)

    def _revoke(self, skill: str) -> None:
        self._grants.revoke(skill)
        self._populate_grants()
        self._toast(self._perm_status, f"Revoked {skill}")

    def _save_perms(self) -> None:
        from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml
        lay = self._inst_layout()
        cfg = load_yaml(lay.config_path, Config)
        cfg.permissions.mode = self._perm_mode.currentText()
        try:
            cfg = Config.model_validate(cfg.model_dump())
            dump_yaml(lay.config_path, cfg)
            self._toast(self._perm_status, "Saved ✓  effective immediately")
        except Exception as exc:  # noqa: BLE001
            self._toast(self._perm_status, f"Invalid: {exc}", error=True)

    # ── shared ──
    def _inst_layout(self) -> Any:
        if self._lay is None:
            from jaeger_ai.core.instance.instance import (
                InstanceLayout, resolve_instance_dir,
            )
            self._lay = (getattr(self.ctx, "layout", None)
                         or InstanceLayout(root=resolve_instance_dir()))
        return self._lay

    def _connect_studio(self) -> None:
        # Studio integration isn't being built yet — just say so, launch nothing.
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setWindowTitle("Jaeger Studio")
        box.setText("Jaeger Studio integration is coming soon.")
        box.setIcon(QMessageBox.Icon.Information)
        box.exec()


def make_surface(ctx: Any, spec: Any = None) -> AgentSettingsWindow:  # noqa: ARG001
    return AgentSettingsWindow(ctx)


_QSS = f"""
    QWidget#AgentSettings {{ background-color: {_BG}; }}
    QFrame#Rail {{ background-color: {_PANEL}; border-right: 1px solid {_STROKE}; }}
    QPushButton#RailBtn {{ border: none; background: transparent; border-radius: 12px;
        padding: 10px; }}
    QPushButton#RailBtn:hover {{ background-color: rgba(255,255,255,0.05); }}
    QPushButton#RailBtn:checked {{ background-color: rgba(67,224,138,0.16); }}
    QPushButton#RailConnect {{ border: none; background: rgba(67,224,138,0.12);
        border-radius: 14px; padding: 10px; }}
    QPushButton#RailConnect:hover {{ background-color: rgba(67,224,138,0.22); }}
    QFrame#AgentPanel {{ background-color: {_PANEL}; border-left: 1px solid {_STROKE}; }}
    QScrollArea#Scroll {{ background: transparent; border: none; }}
    QScrollArea#Scroll > QWidget > QWidget {{ background: transparent; }}
    QLabel#PanelName {{ color: {_INK}; font-size: 17px; font-weight: 700;
        letter-spacing: 1px; }}
    QLabel#BigName {{ color: {_INK}; font-size: 40px; font-weight: 800;
        letter-spacing: 1px; }}
    QLabel#Sub {{ color: {_INK_DIM}; font-size: 12px; }}
    QLabel#Section {{ color: {_INK_DIM}; font-size: 11px; font-weight: 700;
        letter-spacing: 2px; }}
    QLabel#LayerLabel {{ color: {_ACCENT}; font-size: 10px; font-weight: 700;
        letter-spacing: 2px; margin-top: 4px; }}
    QLabel#FieldLabel {{ color: {_INK_DIM}; font-size: 10px; font-weight: 600;
        letter-spacing: 1px; }}
    QLabel#TraitName {{ color: {_INK}; font-size: 12px; font-weight: 600; }}
    QLabel#TraitLvl {{ color: {_ACCENT}; font-size: 11px; font-weight: 700; }}
    QLabel#GrantName {{ color: {_INK}; font-size: 13px; }}
    QLabel#Stub, QLabel#Note {{ color: {_INK_DIM}; font-size: 12px; }}
    QLabel#SaveStatus {{ font-size: 12px; }}
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{
        background: {_FIELD}; color: {_INK}; border: 1px solid {_STROKE};
        border-radius: 8px; padding: 6px 8px; font-size: 13px;
        selection-background-color: {_ACCENT}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
        border: 1px solid {_ACCENT}; }}
    QCheckBox {{ color: {_INK}; font-size: 13px; spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {_STROKE}; background: {_FIELD}; }}
    QCheckBox::indicator:checked {{ background: {_ACCENT}; border: 1px solid {_ACCENT}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {_STROKE}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {_ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 14px; margin: -6px 0; border-radius: 7px;
        background: {_INK}; }}
    QPushButton#SaveBtn {{ background: {_ACCENT}; color: #05140C; border: none;
        border-radius: 9px; padding: 8px 18px; font-size: 13px; font-weight: 700; }}
    QPushButton#SaveBtn:hover {{ background: #5CEBA0; }}
    QPushButton#RevokeBtn {{ background: transparent; color: #FF6B6B; border: 1px solid #4A2530;
        border-radius: 7px; padding: 4px 12px; font-size: 12px; }}
    QPushButton#RevokeBtn:hover {{ background: rgba(255,107,107,0.12); }}
    QFrame#AgentCard {{ background: {_FIELD}; border: 1px solid {_STROKE}; border-radius: 10px; }}
    QFrame#AgentCard:hover {{ border: 1px solid {_INK_DIM}; }}
    QFrame#AgentCardSel {{ background: rgba(67,224,138,0.10); border: 1px solid {_ACCENT};
        border-radius: 10px; }}
    QLabel#AgentCardName {{ color: {_INK}; font-size: 13px; font-weight: 600; }}
    QLabel#AgentCardRole {{ color: {_INK_DIM}; font-size: 11px; }}
    QLabel#Thumb {{ background: {_STROKE}; border-radius: 8px; }}
    QLabel#DefaultTag {{ color: {_ACCENT}; font-size: 9px; font-weight: 700; letter-spacing: 1px;
        border: 1px solid {_ACCENT}; border-radius: 6px; padding: 2px 6px; }}
    QPushButton#RevertBtn {{ background: transparent; color: {_INK_DIM}; border: 1px solid {_STROKE};
        border-radius: 9px; padding: 8px 16px; font-size: 13px; }}
    QPushButton#RevertBtn:hover {{ color: {_INK}; border: 1px solid {_INK_DIM}; }}
    QPushButton#SaveBtn:disabled, QPushButton#RevertBtn:disabled {{
        color: {_INK_DIM}; background: {_STROKE}; border: none; }}
"""
