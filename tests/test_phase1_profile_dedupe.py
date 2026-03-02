from octoprint_nozzlelifetracker.phase1_settings import dedupe_profiles


def test_dedupe_profiles_equivalent_alias_removed_and_tools_remapped():
    profiles = {
        "default_0_4_brass": {
            "id": "default_0_4_brass",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
            "notes": "",
        },
        "default_brass_0_4": {
            "id": "default_brass_0_4",
            "name": " 0.4 BRASS ",
            "interval_hours": 100.0,
            "notes": "legacy",
        },
    }
    tool_state = {
        "T0": {"tool_id": "T0", "profile_id": "default_brass_0_4", "accumulated_seconds": 1},
        "T1": {"tool_id": "T1", "profile_id": "default_0_4_brass", "accumulated_seconds": 2},
    }

    profiles_fixed, tool_state_fixed, changed = dedupe_profiles(profiles, tool_state)

    assert changed is True
    assert "default_0_4_brass" in profiles_fixed
    assert "default_brass_0_4" not in profiles_fixed
    assert tool_state_fixed["T0"]["profile_id"] == "default_0_4_brass"


def test_dedupe_profiles_alias_only_is_moved_to_canonical():
    profiles = {
        "default_brass_0_4": {
            "id": "default_brass_0_4",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
            "notes": "",
        }
    }
    tool_state = {
        "T0": {"tool_id": "T0", "profile_id": "default_brass_0_4", "accumulated_seconds": 0}
    }

    profiles_fixed, tool_state_fixed, changed = dedupe_profiles(profiles, tool_state)

    assert changed is True
    assert "default_0_4_brass" in profiles_fixed
    assert "default_brass_0_4" not in profiles_fixed
    assert profiles_fixed["default_0_4_brass"]["id"] == "default_0_4_brass"
    assert tool_state_fixed["T0"]["profile_id"] == "default_0_4_brass"


def test_dedupe_profiles_non_equivalent_profiles_kept_but_tools_remapped():
    profiles = {
        "default_0_4_brass": {
            "id": "default_0_4_brass",
            "name": "0.4 Brass",
            "interval_hours": 120.0,
            "notes": "",
        },
        "default_brass_0_4": {
            "id": "default_brass_0_4",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
            "notes": "",
        },
    }
    tool_state = {
        "T0": {"tool_id": "T0", "profile_id": "default_brass_0_4", "accumulated_seconds": 7}
    }

    profiles_fixed, tool_state_fixed, changed = dedupe_profiles(profiles, tool_state)

    assert changed is True
    assert "default_0_4_brass" in profiles_fixed
    assert "default_brass_0_4" in profiles_fixed
    assert tool_state_fixed["T0"]["profile_id"] == "default_0_4_brass"


def test_dedupe_profiles_is_idempotent():
    profiles = {
        "default_0_4_brass": {
            "id": "default_0_4_brass",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
            "notes": "",
        },
        "default_brass_0_4": {
            "id": "default_brass_0_4",
            "name": "0.4 Brass",
            "interval_hours": 100.0,
            "notes": "",
        },
    }
    tool_state = {
        "T0": {"tool_id": "T0", "profile_id": "default_brass_0_4", "accumulated_seconds": 0}
    }

    first_profiles, first_tool_state, first_changed = dedupe_profiles(profiles, tool_state)
    second_profiles, second_tool_state, second_changed = dedupe_profiles(first_profiles, first_tool_state)

    assert first_changed is True
    assert second_changed is False
    assert second_profiles == first_profiles
    assert second_tool_state == first_tool_state
