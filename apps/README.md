# 📱 Jaeger Applications (`apps/`)

> Modeled after OpenClaw's decoupled multi-surface layout, all frontend user interfaces for Jaeger live here.

---

* **[`macos/`](macos/)**: Native macOS SwiftUI / AppKit application with Menu Bar presence, floating chat, voice activation, and Gateway connection.
* **[`ios/`](ios/)**: Native iOS / iPadOS SwiftUI application with Dynamic Island / Live Activities, Share Extension, and touch-optimized controls.
* **[`web/`](web/)**: Browser-based chat interface and Kanban board dashboard.

All applications connect to the background **Jaeger Gateway** as decoupled clients, sharing persistent sessions and real-time event streams.
