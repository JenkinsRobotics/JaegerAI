"""jaeger_kokoro_tts.nodes — a single-module namespace: this repo ships
exactly one engine module (``kokoro_tts/``), unlike jaeger_os.nodes
(the framework's multi-node package) or jaeger_ai.nodes (the product's
own shipped-module set). No re-exports here on purpose — importers go
through ``jaeger_kokoro_tts.nodes.kokoro_tts`` directly, or through the
cross-package ``discover_modules()`` + factory-string resolution the
framework uses for slot binding.
"""
