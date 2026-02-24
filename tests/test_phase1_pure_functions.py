import pytest

from octoprint_nozzlelifetracker import (
    compute_elapsed_seconds,
    extract_tool_id_from_command,
    accumulate_tool_seconds,
)


def test_compute_elapsed_seconds_normal_floors_to_int():
    assert compute_elapsed_seconds(100.0, 105.4) == 5


def test_compute_elapsed_seconds_zero_delta():
    assert compute_elapsed_seconds(100.0, 100.0) == 0


def test_compute_elapsed_seconds_negative_clamped():
    assert compute_elapsed_seconds(105.0, 100.0) == 0


@pytest.mark.parametrize(
    "cmd, expected",
    [
        ("T0", "T0"),
        ("t1", "T1"),
        ("T2 ; tool change", "T2"),
        ("G1 X10", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_tool_id_from_command(cmd, expected):
    assert extract_tool_id_from_command(cmd) == expected


def test_accumulate_tool_seconds_creates_missing_tool():
    updated, changed = accumulate_tool_seconds({}, "T0", 10, default_profile_id="p1")

    assert changed is True
    assert updated["T0"]["tool_id"] == "T0"
    assert updated["T0"]["profile_id"] == "p1"
    assert updated["T0"]["accumulated_seconds"] == 10


def test_accumulate_tool_seconds_adds_to_existing_tool():
    tool_state = {"T0": {"tool_id": "T0", "profile_id": "p1", "accumulated_seconds": 12}}

    updated, changed = accumulate_tool_seconds(tool_state, "T0", 8)

    assert changed is True
    assert updated["T0"]["accumulated_seconds"] == 20
    assert tool_state["T0"]["accumulated_seconds"] == 12


def test_accumulate_tool_seconds_two_tools_independent():
    state = {}
    state, changed_0 = accumulate_tool_seconds(state, "T0", 10, default_profile_id="p0")
    state, changed_1 = accumulate_tool_seconds(state, "T1", 7, default_profile_id="p1")

    assert changed_0 is True
    assert changed_1 is True
    assert state["T0"]["accumulated_seconds"] == 10
    assert state["T1"]["accumulated_seconds"] == 7
    assert state["T0"]["profile_id"] == "p0"
    assert state["T1"]["profile_id"] == "p1"


@pytest.mark.parametrize("delta_seconds", [0, -1])
def test_accumulate_tool_seconds_non_positive_delta_noop(delta_seconds):
    original = {"T0": {"tool_id": "T0", "profile_id": "p1", "accumulated_seconds": 3}}

    updated, changed = accumulate_tool_seconds(original, "T0", delta_seconds)

    assert changed is False
    assert updated == original
