"""metrics.py is a measurement instrument — its arithmetic gets tested against hand-built timelines."""

from voxprobe.metrics import SegmentationPolicy, compute, render_md


def seg(speaker: str, start: float, end: float, text: str = "x") -> dict:
    return {"speaker": speaker, "start": start, "end": end, "text": text}


def test_response_gaps_are_split_by_direction_and_dead_air_is_a_labelled_subset():
    timeline = [
        seg("AGENT", 0.0, 3.0),  # agent speaks
        seg("PATIENT", 3.8, 6.0),  # caller replies after 0.8 s
        seg("AGENT", 19.24, 22.0),  # agent replies after 13.24 s  -> dead air, agent slow
        seg("PATIENT", 22.9, 24.0),  # caller replies after 0.9 s
    ]
    m = compute(timeline)
    assert m["turns"] == {"AGENT": 2, "PATIENT": 2}
    assert m["patient_response"]["n"] == 2 and m["patient_response"]["max_s"] == 0.9
    assert m["agent_response"]["n"] == 1 and m["agent_response"]["max_s"] == 13.24
    # the 13.24 s gap is ONE event: in the agent-response distribution AND flagged as dead air, attributed to the agent
    assert len(m["dead_air"]) == 1
    assert m["dead_air"][0]["slow_party"] == "AGENT" and m["dead_air"][0]["gap_s"] == 13.24
    assert m["intra_turn_pauses"] == []  # not an intra-turn pause
    assert m["overlaps"] == []


def test_overlap_and_intra_turn_pause_are_distinct_phenomena():
    timeline = [
        seg("AGENT", 0.0, 4.0),
        seg("PATIENT", 3.4, 6.0),  # started 0.6 s before the agent finished -> overlap
        seg("AGENT", 6.5, 8.0),
        seg("AGENT", 10.9, 12.0),  # same speaker, 2.9 s pause inside the turn (< merge gap? no: 2.9 > 1.5)
    ]
    m = compute(timeline, policy=SegmentationPolicy(merge_gap_s=3.0))
    assert len(m["overlaps"]) == 1
    assert m["overlaps"][0]["who_started"] == "PATIENT" and m["overlaps"][0]["overlap_s"] == 0.6
    # with merge_gap 3.0 the two agent segments merge into one turn with a 2.9 s internal pause
    assert m["turns"]["AGENT"] == 2
    assert m["intra_turn_pauses"] == [{"speaker": "AGENT", "at": 6.5, "pause_s": 2.9}]


def test_p95_is_only_reported_with_enough_samples():
    few = [seg("AGENT", i * 10.0, i * 10.0 + 2) for i in range(4)]
    few_p = [seg("PATIENT", i * 10.0 + 3, i * 10.0 + 4) for i in range(4)]
    timeline = sorted(few + few_p, key=lambda s: s["start"])
    m = compute(timeline)
    assert m["patient_response"]["n"] == 4 and "p95_s" not in m["patient_response"]
    many = [seg("AGENT", i * 10.0, i * 10.0 + 2) for i in range(6)]
    many_p = [seg("PATIENT", i * 10.0 + 3, i * 10.0 + 4) for i in range(6)]
    m2 = compute(sorted(many + many_p, key=lambda s: s["start"]))
    assert m2["patient_response"]["n"] == 6 and "p95_s" in m2["patient_response"]


def test_same_speaker_back_to_back_is_not_a_response():
    timeline = [seg("AGENT", 0, 2), seg("AGENT", 5, 6), seg("PATIENT", 7, 8)]
    m = compute(timeline)
    assert m["agent_response"]["n"] == 0
    assert m["patient_response"]["n"] == 1


def test_render_mentions_dead_air_and_policy_thresholds():
    timeline = [seg("AGENT", 0, 2), seg("PATIENT", 6.5, 8)]
    md = render_md(compute(timeline))
    assert "Dead air (response gap ≥ 3.0 s) | 1" in md
    assert "PATIENT slow" in md
