from jaeger_ai.features.droid.conversation import InterruptionKind, SpeechPlanController, classify_interruption


def test_interruption_classification_separates_backchannel_from_changes():
    assert classify_interruption("yeah").kind is InterruptionKind.BACKCHANNEL
    assert classify_interruption("actually use the physical camera").kind is InterruptionKind.CORRECTION
    assert classify_interruption("why are you doing that?").kind is InterruptionKind.QUESTION
    assert classify_interruption("let me finish").kind is InterruptionKind.TAKEOVER
    stop = classify_interruption("stop moving")
    assert stop.kind is InterruptionKind.STOP
    assert stop.cancel_task and stop.route_to_agent


def test_backchannel_pauses_then_resumes_the_same_thought():
    sent, stopped = [], []
    plan = SpeechPlanController(sent.append, lambda: stopped.append(True))
    plan.enqueue("I found the physical camera.", source_id="turn-1")
    first = sent[-1]
    plan.playback_started()
    assert plan.pause_for_overlap()
    decision = plan.resolve("yeah")
    assert decision.resume and not decision.route_to_agent
    assert stopped == [True]
    assert sent[-1].id == first.id
    assert sent[-1].attempts == 2


def test_correction_discards_old_speech_until_steer_is_applied():
    sent = []
    plan = SpeechPlanController(sent.append, lambda: None)
    plan.enqueue("I found the Logitech camera.", source_id="turn-1")
    plan.enqueue("I will move it now.", source_id="turn-1")
    plan.pause_for_overlap()
    decision = plan.resolve("actually it is the Insta360")
    assert decision.route_to_agent and not decision.resume
    assert plan.snapshot()["state"] == "idle"
    assert plan.enqueue("stale continuation", source_id="turn-1") is False
    plan.unblock_source("turn-1")
    assert plan.enqueue("Right, the physical Insta360.", source_id="turn-1") is True


def test_only_playback_completion_counts_as_delivered():
    sent = []
    plan = SpeechPlanController(sent.append, lambda: None)
    plan.enqueue("One thought.")
    plan.pause_for_overlap()
    plan.resolve("let me finish")
    assert plan.snapshot()["delivered"][0]["state"] == "interrupted"
    plan.enqueue("A completed thought.")
    plan.playback_started()
    plan.playback_finished()
    delivered = plan.snapshot()["delivered"]
    assert delivered[-1]["state"] == "delivered"


def test_speech_units_are_serialized():
    sent = []
    plan = SpeechPlanController(sent.append, lambda: None)
    plan.enqueue("First.")
    plan.enqueue("Second.")
    assert [unit.text for unit in sent] == ["First."]
    plan.playback_finished()
    assert [unit.text for unit in sent] == ["First.", "Second."]
