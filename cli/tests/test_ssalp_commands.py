"""Exhaustive smoke tests for every command mixin method.

Each test verifies that the correct Alpaca action/method name is sent on the wire.
"""

from __future__ import annotations

import pytest

from ssalp_api_client.client import SSAlpApiClient
from ssalp_api_client.config import Config

from .conftest import make_alpaca_response

ACTION_URL = "http://localhost:5555/api/v1/telescope/1/action"


@pytest.fixture
def client() -> SSAlpApiClient:
    return SSAlpApiClient(config=Config(host="localhost", port=5555, device=1))


def _stub(httpx_mock, value=None):
    httpx_mock.add_response(
        method="PUT", url=ACTION_URL, json=make_alpaca_response(value=value)
    )


def _body(httpx_mock) -> str:
    return httpx_mock.get_request().content.decode()


async def _check_method(httpx_mock, coro, expected_method: str):
    _stub(httpx_mock)
    await coro
    body = _body(httpx_mock)
    assert "Action=method_sync" in body
    assert expected_method in body


async def _check_action(httpx_mock, coro, expected_action: str):
    _stub(httpx_mock)
    await coro
    body = _body(httpx_mock)
    assert f"Action={expected_action}" in body


# ── InfoMixin ─────────────────────────────────────────────────────────────


class TestInfoMixinCoverage:
    async def test_test_connection(self, client, httpx_mock):
        await _check_method(httpx_mock, client.test_connection(), "test_connection")

    async def test_get_device_state(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_device_state(), "get_device_state")

    async def test_get_camera_info(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_camera_info(), "get_camera_info")

    async def test_get_camera_state(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_camera_state(), "get_camera_state")

    async def test_get_camera_exp_and_bin(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_camera_exp_and_bin(), "get_camera_exp_and_bin"
        )

    async def test_get_controls(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_controls(), "get_controls")

    async def test_get_control_value(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_control_value("gain"), "get_control_value"
        )

    async def test_get_setting(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_setting(), "get_setting")

    async def test_get_stack_info(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_stack_info(), "get_stack_info")

    async def test_get_stack_setting(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_stack_setting(), "get_stack_setting")

    async def test_get_test_setting(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_test_setting(), "get_test_setting")

    async def test_get_disk_volume(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_disk_volume(), "get_disk_volume")

    async def test_get_view_state(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_view_state(), "get_view_state")

    async def test_get_user_location(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_user_location(), "get_user_location")

    async def test_set_user_location(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.set_user_location(51.5, -0.12), "set_user_location"
        )

    async def test_get_app_setting(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_app_setting(), "get_app_setting")

    async def test_set_app_setting(self, client, httpx_mock):
        await _check_method(
            httpx_mock,
            client.set_app_setting(goto_target_name="M42"),
            "set_app_setting",
        )

    async def test_get_sequence_setting(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_sequence_setting(), "get_sequence_setting"
        )

    async def test_set_sequence_setting(self, client, httpx_mock):
        await _check_method(
            httpx_mock,
            client.set_sequence_setting(group_name="g"),
            "set_sequence_setting",
        )

    async def test_iscope_get_app_state(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.iscope_get_app_state(), "iscope_get_app_state"
        )

    async def test_get_event_state(self, client, httpx_mock):
        await _check_action(httpx_mock, client.get_event_state(), "get_event_state")

    async def test_get_image_save_path(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_image_save_path(), "get_image_save_path"
        )

    async def test_get_annotate_result(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_annotate_result(42), "get_annotate_result"
        )

    async def test_is_stacked(self, client, httpx_mock):
        await _check_method(httpx_mock, client.is_stacked(), "is_stacked")

    async def test_pi_get_ap(self, client, httpx_mock):
        await _check_method(httpx_mock, client.pi_get_ap(), "pi_get_ap")

    async def test_pi_get_time(self, client, httpx_mock):
        await _check_method(httpx_mock, client.pi_get_time(), "pi_get_time")

    async def test_pi_set_time(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.pi_set_time("2024-01-01T00:00:00Z"), "pi_set_time"
        )


# ── SystemMixin ───────────────────────────────────────────────────────────


class TestSystemMixinCoverage:
    async def test_startup_sequence(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.startup_sequence(0.0, 0.0), "action_start_up_sequence"
        )

    async def test_pi_reboot(self, client, httpx_mock):
        await _check_method(httpx_mock, client.pi_reboot(), "pi_reboot")

    async def test_pi_shutdown(self, client, httpx_mock):
        await _check_method(httpx_mock, client.pi_shutdown(), "pi_shutdown")

    async def test_pi_is_verified(self, client, httpx_mock):
        await _check_method(httpx_mock, client.pi_is_verified(), "pi_is_verified")

    async def test_play_sound(self, client, httpx_mock):
        await _check_action(httpx_mock, client.play_sound(81), "play_sound")

    async def test_set_heater_on(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_heater(True, 90), "pi_output_set2")

    async def test_set_heater_off(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_heater(False, 0), "pi_output_set2")

    async def test_set_heater_invalid_value(self, client):
        with pytest.raises(ValueError):
            await client.set_heater(True, 101)


# ── MountMixin ────────────────────────────────────────────────────────────


class TestMountMixinCoverage:
    async def test_scope_goto(self, client, httpx_mock):
        await _check_method(httpx_mock, client.scope_goto(1.0, 2.0), "scope_goto")

    async def test_goto_target(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.goto_target("M42", 1.0, 2.0), "goto_target"
        )

    async def test_scope_park(self, client, httpx_mock):
        await _check_method(httpx_mock, client.scope_park(), "scope_park")

    async def test_scope_move_to_horizon(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.scope_move_to_horizon(), "scope_move_to_horizon"
        )

    async def test_scope_get_equ_coord(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.scope_get_equ_coord(), "scope_get_equ_coord"
        )

    async def test_scope_get_horiz_coord(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.scope_get_horiz_coord(), "scope_get_horiz_coord"
        )

    async def test_scope_get_ra_dec(self, client, httpx_mock):
        await _check_method(httpx_mock, client.scope_get_ra_dec(), "scope_get_ra_dec")

    async def test_scope_get_track_state(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.scope_get_track_state(), "scope_get_track_state"
        )

    async def test_scope_set_track_state(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.scope_set_track_state(True), "scope_set_track_state"
        )

    async def test_scope_speed_move(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.scope_speed_move(100, 90, 2.0), "scope_speed_move"
        )

    async def test_scope_sync(self, client, httpx_mock):
        await _check_method(httpx_mock, client.scope_sync(1.0, 2.0), "scope_sync")

    async def test_start_solve(self, client, httpx_mock):
        await _check_method(httpx_mock, client.start_solve(), "start_solve")

    async def test_get_solve_result(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_solve_result(), "get_solve_result")

    async def test_get_last_solve_result(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_last_solve_result(), "get_last_solve_result"
        )

    async def test_stop_plate_solve_loop(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.stop_plate_solve_loop(), "stop_plate_solve_loop"
        )

    async def test_start_polar_align(self, client, httpx_mock):
        await _check_method(httpx_mock, client.start_polar_align(), "start_polar_align")

    async def test_get_pa_error(self, client, httpx_mock):
        await _check_action(httpx_mock, client.get_pa_error(), "get_pa_error")

    async def test_adjust_mag_declination(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.adjust_mag_declination(), "adjust_mag_declination"
        )

    async def test_is_goto(self, client, httpx_mock):
        await _check_action(httpx_mock, client.is_goto(), "is_goto")

    async def test_is_goto_completed_ok(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.is_goto_completed_ok(), "is_goto_completed_ok"
        )

    async def test_stop_goto_target(self, client, httpx_mock):
        await _check_action(httpx_mock, client.stop_goto_target(), "stop_goto_target")

    async def test_set_below_horizon_dec_offset(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.set_below_horizon_dec_offset(5.0),
            "set_below_horizon_dec_offset",
        )

    async def test_set_dither(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_dither(50, 10), "set_setting")

    async def test_set_3ppa_calibration(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_3ppa_calibration(), "set_setting")

    async def test_set_stack_setting(self, client, httpx_mock):
        await _check_method(
            httpx_mock,
            client.set_stack_setting(save_discrete_frame=True),
            "set_stack_setting",
        )


# ── CameraMixin ───────────────────────────────────────────────────────────


class TestCameraMixinCoverage:
    async def test_start_exposure(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.start_exposure("light", False), "start_exposure"
        )

    async def test_stop_exposure(self, client, httpx_mock):
        await _check_method(httpx_mock, client.stop_exposure(), "stop_exposure")

    async def test_start_stack(self, client, httpx_mock):
        await _check_action(httpx_mock, client.start_stack(80), "start_stack")

    async def test_stop_view_no_stage(self, client, httpx_mock):
        await _check_method(httpx_mock, client.stop_view(), "iscope_stop_view")

    async def test_stop_view_with_stage(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.stop_view("DarkLibrary"), "iscope_stop_view"
        )

    async def test_set_gain(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_gain(80), "set_control_value")

    async def test_set_exposure(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_exposure(10000, 500), "set_setting")

    async def test_set_brightness(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_brightness(80), "set_setting")

    async def test_start_create_dark(self, client, httpx_mock):
        await _check_method(httpx_mock, client.start_create_dark(), "start_create_dark")


# ── FocuserMixin ──────────────────────────────────────────────────────────


class TestFocuserMixinCoverage:
    async def test_get_focuser_position_simple(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_focuser_position(), "get_focuser_position"
        )

    async def test_get_focuser_position_ret_obj(self, client, httpx_mock):
        await _check_method(
            httpx_mock,
            client.get_focuser_position(ret_obj=True),
            "get_focuser_position",
        )

    async def test_adjust_focus(self, client, httpx_mock):
        await _check_action(httpx_mock, client.adjust_focus(100), "adjust_focus")

    async def test_start_auto_focus(self, client, httpx_mock):
        await _check_method(httpx_mock, client.start_auto_focus(), "start_auto_focuse")

    async def test_stop_auto_focus(self, client, httpx_mock):
        await _check_method(httpx_mock, client.stop_auto_focus(), "stop_auto_focuse")


# ── FilterWheelMixin ──────────────────────────────────────────────────────


class TestFilterWheelMixinCoverage:
    async def test_get_wheel_position(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_wheel_position(), "get_wheel_position"
        )

    async def test_get_wheel_state(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_wheel_state(), "get_wheel_state")

    async def test_get_wheel_setting(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_wheel_setting(), "get_wheel_setting")

    async def test_set_wheel_position(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.set_wheel_position(1), "set_wheel_position"
        )

    async def test_set_lp_filter(self, client, httpx_mock):
        await _check_method(httpx_mock, client.set_lp_filter(True), "set_setting")


# ── FilesMixin ────────────────────────────────────────────────────────────


class TestFilesMixinCoverage:
    async def test_get_albums(self, client, httpx_mock):
        await _check_method(httpx_mock, client.get_albums(), "get_albums")

    async def test_get_img_name_field(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.get_img_name_field(), "get_img_name_field"
        )

    async def test_set_img_name_field(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.set_img_name_field(), "set_img_name_field"
        )

    async def test_get_last_image(self, client, httpx_mock):
        await _check_action(httpx_mock, client.get_last_image(), "get_last_image")

    async def test_set_sequence_group_name(self, client, httpx_mock):
        await _check_method(
            httpx_mock, client.set_sequence_group_name("grp"), "set_sequence_setting"
        )

    async def test_download_image(self, client, httpx_mock):
        httpx_mock.add_response(
            method="GET",
            url="http://localhost:5555/images/x.jpg",
            content=b"\xff\xd8",
        )
        data = await client.download_image("http://localhost:5555/images/x.jpg")
        assert data == b"\xff\xd8"


# ── ScheduleMixin ─────────────────────────────────────────────────────────


class TestScheduleMixinCoverage:
    async def test_start_scheduler(self, client, httpx_mock):
        await _check_action(httpx_mock, client.start_scheduler(), "start_scheduler")

    async def test_stop_scheduler(self, client, httpx_mock):
        await _check_action(httpx_mock, client.stop_scheduler(), "stop_scheduler")

    async def test_pause_scheduler(self, client, httpx_mock):
        await _check_action(httpx_mock, client.pause_scheduler(), "pause_scheduler")

    async def test_continue_scheduler(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.continue_scheduler(), "continue_scheduler"
        )

    async def test_reset_scheduler(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.reset_scheduler_cur_item(), "reset_scheduler_cur_item"
        )

    async def test_skip_scheduler(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.skip_scheduler_cur_item(), "skip_scheduler_cur_item"
        )

    async def test_get_schedule(self, client, httpx_mock):
        await _check_action(httpx_mock, client.get_schedule(), "get_schedule")

    async def test_create_schedule(self, client, httpx_mock):
        await _check_action(httpx_mock, client.create_schedule(), "create_schedule")

    async def test_add_schedule_item(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.add_schedule_item("shutdown"), "add_schedule_item"
        )

    async def test_add_schedule_item_with_params(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.add_schedule_item("auto_focus", {"ry_count": 2}),
            "add_schedule_item",
        )

    async def test_remove_schedule_item(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.remove_schedule_item("abc-123"), "remove_schedule_item"
        )

    async def test_replace_schedule_item(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.replace_schedule_item("id1", "shutdown"),
            "replace_schedule_item",
        )

    async def test_insert_schedule_item_before(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.insert_schedule_item_before("id1", "shutdown"),
            "insert_schedule_item_before",
        )

    async def test_export_schedule(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.export_schedule("/tmp/sched.json"), "export_schedule"
        )

    async def test_import_schedule(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.import_schedule("/tmp/sched.json"), "import_schedule"
        )

    async def test_schedule_mosaic(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.schedule_mosaic("M42", 1.0, 2.0, 3600),
            "add_schedule_item",
        )

    async def test_schedule_spectra(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.schedule_spectra("Algol", 1.0, 2.0, 600),
            "add_schedule_item",
        )

    async def test_schedule_wait_until(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.schedule_wait_until("23:00"), "add_schedule_item"
        )

    async def test_schedule_wait_for(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.schedule_wait_for(60), "add_schedule_item"
        )

    async def test_schedule_auto_focus(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.schedule_auto_focus(), "add_schedule_item"
        )

    async def test_schedule_adjust_focus(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.schedule_adjust_focus(50), "add_schedule_item"
        )

    async def test_schedule_shutdown(self, client, httpx_mock):
        await _check_action(httpx_mock, client.schedule_shutdown(), "add_schedule_item")

    async def test_schedule_set_exposure(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.schedule_set_exposure(10000, 500), "add_schedule_item"
        )

    async def test_start_mosaic(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.start_mosaic("M42", 1.0, 2.0, 3600), "start_mosaic"
        )

    async def test_start_spectra(self, client, httpx_mock):
        await _check_action(
            httpx_mock, client.start_spectra("Algol", 1.0, 2.0, 600), "start_spectra"
        )

    # -- params is-not-None branches (lines 64, 73) -------------------------

    async def test_replace_schedule_item_with_params(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.replace_schedule_item("id1", "start_mosaic", {"gain": 80}),
            "replace_schedule_item",
        )

    async def test_insert_schedule_item_before_with_params(self, client, httpx_mock):
        await _check_action(
            httpx_mock,
            client.insert_schedule_item_before("id1", "auto_focus", {"ry_count": 2}),
            "insert_schedule_item_before",
        )

    # -- validation error paths (lines 106, 108, 139, 187, 216, 247) --------

    async def test_schedule_mosaic_zero_time_raises(self, client):
        with pytest.raises(ValueError):
            await client.schedule_mosaic("T", 1.0, 2.0, session_time_sec=0)

    async def test_schedule_mosaic_negative_gain_raises(self, client):
        with pytest.raises(ValueError, match="gain"):
            await client.schedule_mosaic("T", 1.0, 2.0, session_time_sec=60, gain=-1)

    async def test_schedule_spectra_zero_time_raises(self, client):
        with pytest.raises(ValueError):
            await client.schedule_spectra("T", 1.0, 2.0, session_time_sec=0)

    async def test_schedule_set_exposure_zero_raises(self, client):
        with pytest.raises(ValueError):
            await client.schedule_set_exposure(0, 500)

    async def test_start_mosaic_negative_gain_raises(self, client):
        with pytest.raises(ValueError, match="gain"):
            await client.start_mosaic("T", 1.0, 2.0, session_time_sec=60, gain=-1)

    async def test_start_spectra_zero_time_raises(self, client):
        with pytest.raises(ValueError):
            await client.start_spectra("T", 1.0, 2.0, session_time_sec=0)


# ── CameraMixin validation (missing line 33) ──────────────────────────────


class TestCameraValidationExtra:
    async def test_start_stack_negative_gain_raises(self, client):
        with pytest.raises(ValueError, match="gain"):
            await client.start_stack(gain=-1)


# ── output.py ─────────────────────────────────────────────────────────────


class TestOutput:
    """Exercise the output formatters."""

    def test_pretty_scalar(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result(42, "pretty")
        assert "42" in capsys.readouterr().out

    def test_pretty_none(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result(None, "pretty")
        assert "no data" in capsys.readouterr().out

    def test_pretty_dict(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result({"key": "value"}, "pretty")
        assert "key" in capsys.readouterr().out

    def test_pretty_nested_dict(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result({"outer": {"inner": "val"}}, "pretty")
        out = capsys.readouterr().out
        assert "outer" in out
        assert "inner" in out

    def test_pretty_list_of_scalars(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result([1, 2, 3], "pretty")
        out = capsys.readouterr().out
        assert "1" in out

    def test_pretty_list_of_dicts(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result([{"a": 1}, {"a": 2}], "pretty")
        out = capsys.readouterr().out
        assert "a" in out

    def test_json_output(self, capsys):
        import json
        from ssalp_api_client.cli.output import print_result

        print_result({"x": 1}, "json")
        parsed = json.loads(capsys.readouterr().out)
        assert parsed["x"] == 1

    def test_json_list(self, capsys):
        import json
        from ssalp_api_client.cli.output import print_result

        print_result([1, 2, 3], "json")
        parsed = json.loads(capsys.readouterr().out)
        assert parsed == [1, 2, 3]

    def test_table_dict(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result({"host": "localhost", "port": 5555}, "table")
        out = capsys.readouterr().out
        assert "host" in out
        assert "localhost" in out

    def test_table_empty_dict(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result({}, "table")
        assert "empty" in capsys.readouterr().out

    def test_table_list_of_dicts(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result([{"name": "M42", "ra": 1.0}, {"name": "M31", "ra": 2.0}], "table")
        out = capsys.readouterr().out
        assert "name" in out
        assert "M42" in out

    def test_table_scalar_falls_back_to_pretty(self, capsys):
        from ssalp_api_client.cli.output import print_result

        print_result("hello", "table")
        assert "hello" in capsys.readouterr().out
