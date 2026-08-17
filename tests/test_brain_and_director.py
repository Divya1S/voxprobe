from pathlib import Path

from voxprobe.brain import shape_reply, window_history, HISTORY_WINDOW
from voxprobe.director import CallState, director_note, looks_like_goodbye
from voxprobe.scenarios import find_scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"


def test_shape_reply_strips_markdown_and_stage_directions_and_speaker_labels():
    raw = 'Maya Thompson: **Hi there!** (laughs) I\'d like to book an appointment. "Thanks."'
    assert shape_reply(raw) == "Hi there! I'd like to book an appointment. Thanks."


def test_shape_reply_caps_sentence_count():
    raw = "One. Two. Three. Four. Five."
    assert shape_reply(raw) == "One. Two. Three."


def test_window_history_drops_system_and_keeps_tail():
    msgs = [{"role": "system", "content": "x"}] + [
        {"role": "user" if i % 2 else "assistant", "content": f"m{i}"} for i in range(30)
    ]
    out = window_history(msgs)
    assert len(out) == HISTORY_WINDOW
    assert all(m["role"] != "system" for m in out)
    assert out[-1]["content"] == "m29"


def test_director_first_turn_and_question_and_wrapup():
    s = find_scenario(SCENARIOS_DIR, "01")
    state = CallState(scenario=s)
    note = director_note(state, "Hi, can I get your first and last name?")
    assert "first line" in note and "answer it directly" in note
    state.patient_turns = s.max_turns - 2
    assert "last turn" in director_note(state, "Anything else?")


def test_director_flags_repetition():
    s = find_scenario(SCENARIOS_DIR, "01")
    state = CallState(scenario=s, patient_turns=3, previous_replies=["Yes, mornings.", "Yes, mornings."])
    assert "twice" in director_note(state, "Which day works?")


def test_goodbye_detection():
    assert looks_like_goodbye("Great, thanks so much. Bye now!")
    assert not looks_like_goodbye("Could you repeat the time, please?")
