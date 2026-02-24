import pytest

from octoprint_nozzlelifetracker.phase1_settings import reset_tool_state


def test_reset_existing_tool_sets_zero_and_logs_prior_seconds():
    tool_state = {"T0": {"tool_id": "T0", "profile_id": "p1", "accumulated_seconds": 37}}
    replacement_log = []

    new_tool_state, new_replacement_log = reset_tool_state(
        tool_state,
        replacement_log,
        tool_id="T0",
        timestamp="2026-02-24 12:00:00",
    )

    assert new_tool_state["T0"]["accumulated_seconds"] == 0
    assert new_tool_state["T0"]["profile_id"] == "p1"
    assert new_replacement_log[-1] == {
        "timestamp": "2026-02-24 12:00:00",
        "tool_id": "T0",
        "profile_id": "p1",
        "accumulated_seconds_at_reset": 37,
    }


def test_reset_missing_tool_creates_entry_and_logs_zero_seconds():
    new_tool_state, new_replacement_log = reset_tool_state(
        {},
        [],
        tool_id="t1",
        timestamp="2026-02-24 12:05:00",
        default_profile_id="p_default",
    )

    assert new_tool_state["T1"] == {
        "tool_id": "T1",
        "profile_id": "p_default",
        "accumulated_seconds": 0,
    }
    assert new_replacement_log[-1] == {
        "timestamp": "2026-02-24 12:05:00",
        "tool_id": "T1",
        "profile_id": "p_default",
        "accumulated_seconds_at_reset": 0,
    }


def test_reset_invalid_tool_id_raises():
    with pytest.raises(ValueError):
        reset_tool_state({}, [], tool_id="X0", timestamp="2026-02-24 12:10:00")
