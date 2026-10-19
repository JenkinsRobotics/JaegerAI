# Native multimodal components

Only `remote_runtime.py` (bridge socket adapter) and `preflight.py` (device/model diagnostics) were extracted from the archived Qt frontend. No Qt window, application host, tray, identity or runtime owner is retained here. The adapter is independently tested; the new Mac shell does not yet call it. Shared model/audio services remain in the backend.

`jaeger multimodal --check` runs diagnostics. Launching the retired multimodal window now fails explicitly. Camera/video presentation and ambient/barge-in integration in the new shell remain unavailable; this directory is not a replacement implementation of those features.
