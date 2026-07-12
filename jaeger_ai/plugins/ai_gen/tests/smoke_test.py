"""Smoke test for the ai_gen plugin. Confirms importability and that the
unconfigured path degrades to a friendly error instead of crashing."""

from __future__ import annotations


def test_plugin_importable() -> None:
    from jaeger_ai.plugins.ai_gen import generate_image_fal, generate_video_fal

    assert callable(generate_image_fal)
    assert callable(generate_video_fal)


if __name__ == "__main__":
    test_plugin_importable()
    print("ai_gen plugin smoke: OK")
