"""Core output routing is typed, host-independent, and turn-scoped."""

from __future__ import annotations

from jaeger_agent.core.availability import _slot_ready_for_tool
from jaeger_agent.core.outputs import (
    decide_output,
    multimodal_output_active,
    multimodal_output_scope,
    transform_output_content,
)


def test_multimodal_output_scope_is_strictly_turn_local() -> None:
    assert multimodal_output_active() is False
    with multimodal_output_scope():
        assert multimodal_output_active() is True
    assert multimodal_output_active() is False


def test_active_face_hides_external_speech_tools() -> None:
    with multimodal_output_scope():
        assert _slot_ready_for_tool("text_to_speech") is False
        assert _slot_ready_for_tool("speak") is False


def test_hallucinated_speech_tool_fails_closed_inside_multimodal_turn() -> None:
    from jaeger_agent.tools.speak import speak

    with multimodal_output_scope():
        result = speak("must not reach the external module")

    assert result["spoken"] is False
    assert "engine-owned" in result["reason"]


def test_dynamic_directives_select_text_speech_both_and_silence() -> None:
    expected = {
        "[OUTPUT:TEXT] visible": (("text",), "visible", ""),
        "[OUTPUT:SPEECH] audible": (("speech",), "", "audible"),
        "[OUTPUT:BOTH] shared": (("text", "speech"), "shared", "shared"),
        "[OUTPUT:SILENT]": ((), "", ""),
    }
    for reply, (channels, display, speech) in expected.items():
        decision = decide_output(
            mode="dynamic", input_modality="speech", reply=reply
        )
        assert decision.channels == channels
        assert decision.display_text == display
        assert decision.speech_text == speech


def test_dynamic_trailing_directive_after_tool_result_is_routed() -> None:
    decision = decide_output(
        mode="dynamic",
        input_modality="text",
        reply="The calculated result is 437.\n[OUTPUT:SPEECH]",
    )
    assert decision.display_text == ""
    assert decision.speech_text == "The calculated result is 437."
    assert decision.channels == ("speech",)
    assert decision.source == "model-output-directive"


def test_untagged_dynamic_reply_falls_back_to_the_input_channel() -> None:
    spoken = decide_output(
        mode="dynamic", input_modality="speech", reply="ordinary answer"
    )
    typed = decide_output(
        mode="dynamic", input_modality="text", reply="ordinary answer"
    )
    assert spoken.channels == ("speech",)
    assert spoken.display_text == ""
    assert spoken.speech_text == "ordinary answer"
    assert spoken.source == "input-modality-fallback"
    assert typed.channels == ("text",)
    assert typed.display_text == "ordinary answer"
    assert typed.speech_text == ""


def test_persona_style_transform_cannot_strip_the_output_channel() -> None:
    transformed = transform_output_content(
        "[OUTPUT:SPEECH] plain answer",
        lambda body: f"styled {body}",
    )
    assert transformed == "[OUTPUT:SPEECH] styled plain answer"
    assert transform_output_content(
        "[OUTPUT:SILENT] ignored", lambda _body: "must not appear"
    ) == "[OUTPUT:SILENT]"


def test_mirror_mode_follows_the_input_channel() -> None:
    typed_decision = decide_output(
        mode="mirror", input_modality="text", reply="typed"
    )
    spoken_decision = decide_output(
        mode="mirror", input_modality="speech", reply="heard"
    )
    assert typed_decision.channels == ("text",)
    assert spoken_decision.channels == ("text", "speech")


def test_fixed_output_modes_strip_control_directives_after_mode_switch():
    from jaeger_agent.core.outputs import decide_output
    for mode in ('text', 'speech', 'mirror'):
        result = decide_output(mode=mode, input_modality='speech', reply='[OUTPUT:BOTH] Hello')
        assert result.display_text == 'Hello'
        assert '[OUTPUT:' not in result.speech_text
        silent = decide_output(mode=mode, input_modality='text', reply='[OUTPUT:SILENT]')
        assert not silent.display_text and not silent.speech_text
