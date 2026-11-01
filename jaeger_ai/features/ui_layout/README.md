# ui_layout

Shared WebUI appearance persisted by the Gateway so the Mac app, the browser and the iPhone PWA match.

- `routes.py`: layout preset (Glass, Arc, Linear, Dia), stored as `ui/layout.json`.
- `logo.py`: logo choice (`GET/POST /v1/ui/logo`, J-085/J-086), stored as `ui/logo.json`; custom SVGs are sanitized.

Touchpoints: Settings › Appearance, the Chat home mark and top bar.
