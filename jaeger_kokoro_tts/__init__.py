"""JaegerKokoroTTS — the kokoro_tts engine module, its own package.

Split out of the JROS monorepo (0.9 step 4): the module IS the engine
(see ``nodes/kokoro_tts/__init__.py`` for the full architecture note).
Pins ``jaeger-os`` only — never ``jaeger-ai`` — so a robot body (JP01
and friends) can speak without the AI product installed at all.
"""

__version__ = "1.0.0"
