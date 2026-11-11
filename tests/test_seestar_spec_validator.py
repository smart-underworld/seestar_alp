"""The request validator that checks seestar_alp traffic against seestar-spec."""

import pytest

from tests.seestar_spec import validate_request


@pytest.mark.parametrize(
    "request_",
    [
        {"id": 1, "method": "test_connection"},
        {"id": 1, "method": "set_wheel_position", "params": [0]},
        {"id": 1, "method": "set_wheel_position", "params": 2},
        {"id": 1, "method": "get_annotate_result", "params": {"img_id": 7}},
        {
            "id": 1,
            "method": "iscope_start_view",
            "params": {"mode": "star", "target_ra_dec": [10.5, -20.25]},
        },
        # The firmware compares the view mode case-insensitively.
        {"id": 1, "method": "iscope_start_view", "params": {"mode": "Star"}},
        {
            "id": 1,
            "method": "scope_speed_move",
            "params": {"speed": 0, "angle": 0, "dur_sec": 3},
        },
        {
            "id": 1,
            "method": "set_setting",
            "params": {"stack": {"save_discrete_frame": True}},
        },
        {"id": 1, "method": "get_device_state", "params": {"keys": ["device"]}},
    ],
)
def test_conforming_requests_have_no_problems(request_):
    assert validate_request(request_) == []


@pytest.mark.parametrize(
    "method", ["set_stack_setting", "set_stack_settings", "get_stack_setting"]
)
def test_legacy_stack_setting_fallbacks_are_allowed(method):
    # Not in any analyzed firmware table, but AGENTS.md requires keeping
    # these compatibility paths, so they are allowlisted by name.
    request_ = {"id": 1, "method": method, "params": {"save_discrete_frame": True}}
    assert validate_request(request_) == []


def test_unknown_method_is_reported():
    problems = validate_request({"id": 1, "method": "get_device_state, telescope_id"})
    assert len(problems) == 1
    assert "not in seestar-spec" in problems[0]


def test_out_of_range_array_element_is_reported():
    problems = validate_request(
        {"id": 1, "method": "set_wheel_position", "params": [3]}
    )
    assert problems
    assert any("maximum 2" in p for p in problems)


def test_undocumented_key_is_reported():
    problems = validate_request(
        {"id": 1, "method": "get_annotate_result", "params": {"image_id": 7}}
    )
    assert problems
    assert any("image_id" in p for p in problems)


def test_undocumented_nested_key_is_reported():
    problems = validate_request(
        {"id": 1, "method": "set_setting", "params": {"stack": {"bogus": 1}}}
    )
    assert any("stack.bogus" in p for p in problems)


def test_missing_required_params_is_reported():
    problems = validate_request({"id": 1, "method": "iscope_start_view"})
    assert any("params" in p and "required" in p for p in problems)


def test_missing_required_key_is_reported():
    problems = validate_request(
        {"id": 1, "method": "iscope_start_view", "params": {"target_name": "M31"}}
    )
    assert any("mode" in p and "required" in p for p in problems)


def test_wrong_value_type_is_reported():
    problems = validate_request(
        {"id": 1, "method": "start_polar_align", "params": {"dec_pos_index": "3"}}
    )
    assert any("dec_pos_index" in p for p in problems)


def test_boolean_is_not_accepted_as_integer():
    problems = validate_request(
        {"id": 1, "method": "set_wheel_position", "params": [True]}
    )
    assert problems


def test_unknown_placeholder_matches_any_value():
    # Static source scans substitute UNKNOWN for values computed at runtime;
    # only the literal structure around them is checked.
    from tests.seestar_spec import UNKNOWN

    assert (
        validate_request({"id": 1, "method": "set_wheel_position", "params": [UNKNOWN]})
        == []
    )
    problems = validate_request(
        {"id": 1, "method": "get_annotate_result", "params": {"image_id": UNKNOWN}}
    )
    assert any("image_id" in p for p in problems)


@pytest.mark.parametrize(
    "request_",
    [
        # seestar_device.transform_message_for_verify adds an auth marker that
        # seestar-spec does not describe; it is a deliberate compatibility path
        # (issues #748/#758), so the validator checks the request without it.
        {"id": 1, "method": "get_device_state", "params": ["verify"]},
        {"id": 1, "method": "scope_goto", "params": [1.5, 20.0, "verify"]},
        {
            "id": 1,
            "method": "iscope_start_view",
            "params": {"mode": "star", "verify": True},
        },
    ],
)
def test_injected_verify_marker_is_ignored(request_):
    assert validate_request(request_) == []


def test_verify_marker_does_not_hide_other_problems():
    problems = validate_request(
        {"id": 1, "method": "set_wheel_position", "params": [3, "verify"]}
    )
    assert any("maximum 2" in p for p in problems)
