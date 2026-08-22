"""jaeger_whisper_stt.nodes — a single-module namespace: this repo
ships exactly one engine module (``whisper_stt/``), unlike
jaeger_os.nodes (the framework's multi-node package) or jaeger_ai.nodes
(the product's own shipped-module set). No re-exports here on purpose —
importers go through ``jaeger_whisper_stt.nodes.whisper_stt`` directly,
or through the cross-package ``discover_modules()`` + factory-string
resolution the framework uses for slot binding.
"""
