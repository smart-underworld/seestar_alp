from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any
from urllib.parse import urlparse

import click

from ..client import SSAlpApiClient
from ..config import load_config
from ..exceptions import SSAlpConnectionError, SSAlpError
from .output import print_result

try:
    from ...tools.bru_parser import load_env as _load_bru_env
except ImportError:
    # tools/ may not be on sys.path when installed as a wheel
    _load_bru_env = None  # type: ignore[assignment]


def _setup_logging(log_level: str, log_file: str | None) -> None:
    handler: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handler.append(logging.FileHandler(log_file))
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    root = logging.getLogger("ssalp_api_client")
    root.setLevel(log_level)
    for h in handler:
        h.setFormatter(fmt)
        root.addHandler(h)


def _run(ctx: click.Context, coro: Any) -> None:
    """Run *coro*, print the result, and handle errors uniformly."""
    obj = ctx.obj
    try:
        result = asyncio.run(coro)
        print_result(result, obj["config"].output)
    except SSAlpError as exc:
        click.echo(f"Error [{exc.error_number}]: {exc}", err=True)
        sys.exit(1)
    except SSAlpConnectionError as exc:
        click.echo(f"Connection error: {exc}", err=True)
        click.echo(
            "Check that seestar_alp is running and --host/--port are correct.", err=True
        )
        sys.exit(1)


# ── root group ────────────────────────────────────────────────────────────

@click.group()
@click.option("--host", "-H", default=None, help="Device host.")
@click.option("--port", "-p", default=None, type=int, help="Device port.")
@click.option("--device", "-d", default=None, type=int, help="Alpaca device number.")
@click.option("--timeout", default=None, type=float, help="Request timeout in seconds.")
@click.option(
    "--output",
    "-o",
    default=None,
    type=click.Choice(["json", "table", "pretty"]),
    help="Output format.",
)
@click.option(
    "--log-level",
    default=None,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    help="Log level (default: WARNING).",
)
@click.option("--log-file", default=None, type=click.Path(), help="Write logs to file.")
@click.option(
    "--config",
    "config_file",
    default=None,
    type=click.Path(exists=True),
    help="Config file path (overrides search path).",
)
@click.option("--profile", default="default", help="Config file profile name.")
@click.option(
    "--env",
    "bru_env_file",
    default=None,
    type=click.Path(exists=True),
    help="Bruno .bru environment file (sets host/port/device).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    host: str | None,
    port: int | None,
    device: int | None,
    timeout: float | None,
    output: str | None,
    log_level: str | None,
    log_file: str | None,
    config_file: str | None,
    profile: str,
    bru_env_file: str | None,
) -> None:
    """ssalp — command-line interface for seestar_alp.

    Settings are resolved in priority order (highest wins):

    \b
        CLI flags  >  environment variables  >  config file  >  built-in defaults

    Config file is searched in order:

    \b
        1. --config FILE  or  SSALP_CONFIG env var
        2. ./ssalp.toml          (project-local)
        3. ~/.config/ssalp/config.toml  (user-level)

    Config file format (TOML):

    \b
        [default]
        host       = "localhost"
        port       = 5555
        device     = 1
        timeout    = 10.0
        log_level  = "WARNING"   # DEBUG | INFO | WARNING | ERROR
        output     = "pretty"    # pretty | json | table
        #
        [profiles.home]
        host   = "192.168.1.51"
        #
        [profiles.observatory]
        host      = "10.0.0.100"
        device    = 2
        log_level = "INFO"

    Select a profile with --profile NAME or SSALP_PROFILE.

    Environment variables:

    \b
        SSALP_HOST        --host
        SSALP_PORT        --port
        SSALP_DEVICE      --device
        SSALP_TIMEOUT     --timeout
        SSALP_LOG_LEVEL   --log-level
        SSALP_LOG_FILE    --log-file
        SSALP_OUTPUT      --output
        SSALP_PROFILE     --profile
        SSALP_CONFIG      --config
    """
    ctx.ensure_object(dict)

    overrides: dict = {}

    if bru_env_file:
        if _load_bru_env is None:
            click.echo(
                "Warning: bru_parser not available in this installation; --env ignored.",
                err=True,
            )
        else:
            bru_vars = _load_bru_env(bru_env_file)
            if "base_url" in bru_vars:
                parsed = urlparse(bru_vars["base_url"])
                overrides["host"] = parsed.hostname
                if parsed.port:
                    overrides["port"] = parsed.port
            if "dev_num" in bru_vars:
                overrides["device"] = int(bru_vars["dev_num"])

    # CLI flags override the Bruno env file
    for key, val in {
        "host": host,
        "port": port,
        "device": device,
        "timeout": timeout,
        "output": output,
        "log_level": log_level,
        "log_file": log_file,
    }.items():
        if val is not None:
            overrides[key] = val

    config = load_config(config_file=config_file, profile=profile, overrides=overrides)
    _setup_logging(config.log_level, config.log_file)

    ctx.obj["config"] = config
    ctx.obj["client"] = SSAlpApiClient(config=config)


# ── info ──────────────────────────────────────────────────────────────────

@cli.group()
def info() -> None:
    """Query device state and settings."""


@info.command("test-connection")
@click.pass_context
def info_test_connection(ctx: click.Context) -> None:
    """Test connectivity to the device."""
    _run(ctx, ctx.obj["client"].test_connection())


@info.command("device-state")
@click.pass_context
def info_device_state(ctx: click.Context) -> None:
    """Get the full device state."""
    _run(ctx, ctx.obj["client"].get_device_state())


@info.command("camera-info")
@click.pass_context
def info_camera_info(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_camera_info())


@info.command("camera-state")
@click.pass_context
def info_camera_state(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_camera_state())


@info.command("camera-exp-bin")
@click.pass_context
def info_camera_exp_bin(ctx: click.Context) -> None:
    """Get camera exposure and bin settings."""
    _run(ctx, ctx.obj["client"].get_camera_exp_and_bin())


@info.command("controls")
@click.pass_context
def info_controls(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_controls())


@info.command("control-value")
@click.argument("name")
@click.pass_context
def info_control_value(ctx: click.Context, name: str) -> None:
    """Get a control value by NAME (e.g. gain, exposure)."""
    _run(ctx, ctx.obj["client"].get_control_value(name))


@info.command("setting")
@click.pass_context
def info_setting(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_setting())


@info.command("stack-info")
@click.pass_context
def info_stack_info(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_stack_info())


@info.command("stack-setting")
@click.pass_context
def info_stack_setting(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_stack_setting())


@info.command("disk-volume")
@click.pass_context
def info_disk_volume(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_disk_volume())


@info.command("view-state")
@click.pass_context
def info_view_state(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_view_state())


@info.command("location")
@click.pass_context
def info_location(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_user_location())


@info.command("event-state")
@click.pass_context
def info_event_state(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_event_state())


@info.command("app-setting")
@click.pass_context
def info_app_setting(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_app_setting())


@info.command("app-state")
@click.pass_context
def info_app_state(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].iscope_get_app_state())


@info.command("image-save-path")
@click.pass_context
def info_image_save_path(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_image_save_path())


@info.command("is-stacked")
@click.pass_context
def info_is_stacked(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].is_stacked())


@info.command("time")
@click.pass_context
def info_time(ctx: click.Context) -> None:
    """Get the device system time."""
    _run(ctx, ctx.obj["client"].pi_get_time())


@info.command("ap")
@click.pass_context
def info_ap(ctx: click.Context) -> None:
    """Get Wi-Fi access-point settings."""
    _run(ctx, ctx.obj["client"].pi_get_ap())


@info.command("sequence-setting")
@click.pass_context
def info_sequence_setting(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_sequence_setting())


# ── mount ─────────────────────────────────────────────────────────────────

@cli.group()
def mount() -> None:
    """Mount control: slew, park, solve, track."""


@mount.command("goto")
@click.option("--ra", required=True, type=float, help="Right ascension (hours).")
@click.option("--dec", required=True, type=float, help="Declination (degrees).")
@click.pass_context
def mount_goto(ctx: click.Context, ra: float, dec: float) -> None:
    """Slew to equatorial coordinates."""
    _run(ctx, ctx.obj["client"].scope_goto(ra=ra, dec=dec))


@mount.command("goto-target")
@click.option("--name", required=True, help="Target name.")
@click.option("--ra", required=True, help="RA (decimal hours or sexagesimal string).")
@click.option("--dec", required=True, help="Dec (decimal degrees or sexagesimal string).")
@click.option("--j2000/--no-j2000", default=True, help="Treat coordinates as J2000.")
@click.pass_context
def mount_goto_target(
    ctx: click.Context, name: str, ra: str, dec: str, j2000: bool
) -> None:
    """Slew to a named target."""
    _run(ctx, ctx.obj["client"].goto_target(target_name=name, ra=ra, dec=dec, is_j2000=j2000))


@mount.command("park")
@click.pass_context
def mount_park(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].scope_park())


@mount.command("park-horizon")
@click.pass_context
def mount_park_horizon(ctx: click.Context) -> None:
    """Move the mount to the horizon position."""
    _run(ctx, ctx.obj["client"].scope_move_to_horizon())


@mount.command("equ-coord")
@click.pass_context
def mount_equ_coord(ctx: click.Context) -> None:
    """Get current equatorial coordinates."""
    _run(ctx, ctx.obj["client"].scope_get_equ_coord())


@mount.command("horiz-coord")
@click.pass_context
def mount_horiz_coord(ctx: click.Context) -> None:
    """Get current horizontal (Alt/Az) coordinates."""
    _run(ctx, ctx.obj["client"].scope_get_horiz_coord())


@mount.command("ra-dec")
@click.pass_context
def mount_ra_dec(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].scope_get_ra_dec())


@mount.command("track-state")
@click.pass_context
def mount_track_state(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].scope_get_track_state())


@mount.command("set-track")
@click.option("--on/--off", "enabled", default=True, help="Enable or disable tracking.")
@click.pass_context
def mount_set_track(ctx: click.Context, enabled: bool) -> None:
    _run(ctx, ctx.obj["client"].scope_set_track_state(enabled))


@mount.command("sync")
@click.option("--ra", required=True, type=float)
@click.option("--dec", required=True, type=float)
@click.pass_context
def mount_sync(ctx: click.Context, ra: float, dec: float) -> None:
    """Sync the mount to the given RA/Dec."""
    _run(ctx, ctx.obj["client"].scope_sync(ra=ra, dec=dec))


@mount.command("speed-move")
@click.option("--speed", required=True, type=int, help="Move speed (0 = stop).")
@click.option("--angle", required=True, type=float, help="Direction angle in degrees.")
@click.option("--dur", required=True, type=float, help="Duration in seconds.")
@click.pass_context
def mount_speed_move(ctx: click.Context, speed: int, angle: float, dur: float) -> None:
    """Move the mount at a given speed and angle."""
    _run(ctx, ctx.obj["client"].scope_speed_move(speed=speed, angle=angle, dur_sec=dur))


@mount.command("solve")
@click.pass_context
def mount_solve(ctx: click.Context) -> None:
    """Start a plate-solve."""
    _run(ctx, ctx.obj["client"].start_solve())


@mount.command("solve-result")
@click.pass_context
def mount_solve_result(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_solve_result())


@mount.command("last-solve-result")
@click.pass_context
def mount_last_solve_result(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_last_solve_result())


@mount.command("stop-solve-loop")
@click.pass_context
def mount_stop_solve_loop(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].stop_plate_solve_loop())


@mount.command("polar-align")
@click.pass_context
def mount_polar_align(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].start_polar_align())


@mount.command("pa-error")
@click.pass_context
def mount_pa_error(ctx: click.Context) -> None:
    """Get the polar alignment error."""
    _run(ctx, ctx.obj["client"].get_pa_error())


@mount.command("is-goto")
@click.pass_context
def mount_is_goto(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].is_goto())


@mount.command("is-goto-ok")
@click.pass_context
def mount_is_goto_ok(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].is_goto_completed_ok())


@mount.command("stop-goto")
@click.pass_context
def mount_stop_goto(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].stop_goto_target())


@mount.command("adjust-declination")
@click.option("--adjust/--no-adjust", default=True)
@click.option("--fudge", default=0.0, type=float)
@click.pass_context
def mount_adjust_dec(ctx: click.Context, adjust: bool, fudge: float) -> None:
    _run(ctx, ctx.obj["client"].adjust_mag_declination(adjust=adjust, fudge_angle=fudge))


@mount.command("set-horizon-offset")
@click.option("--offset", default=0.0, type=float)
@click.pass_context
def mount_set_horizon_offset(ctx: click.Context, offset: float) -> None:
    _run(ctx, ctx.obj["client"].set_below_horizon_dec_offset(offset=offset))


@mount.command("set-dither")
@click.option("--pix", required=True, type=int, help="Dither pixels.")
@click.option("--interval", required=True, type=int, help="Dither interval (frames).")
@click.option("--enable/--no-enable", default=True)
@click.pass_context
def mount_set_dither(ctx: click.Context, pix: int, interval: int, enable: bool) -> None:
    _run(ctx, ctx.obj["client"].set_dither(pix=pix, interval=interval, enable=enable))


@mount.command("set-3ppa")
@click.option("--enable/--no-enable", default=True)
@click.pass_context
def mount_set_3ppa(ctx: click.Context, enable: bool) -> None:
    """Enable or disable 3-point polar alignment calibration."""
    _run(ctx, ctx.obj["client"].set_3ppa_calibration(enabled=enable))


# ── camera ────────────────────────────────────────────────────────────────

@cli.group()
def camera() -> None:
    """Camera control: expose, gain, stacking."""


@camera.command("expose")
@click.option(
    "--type",
    "exp_type",
    default="light",
    type=click.Choice(["light", "dark", "flat", "bias"]),
)
@click.option("--stack/--no-stack", default=False)
@click.pass_context
def camera_expose(ctx: click.Context, exp_type: str, stack: bool) -> None:
    _run(ctx, ctx.obj["client"].start_exposure(exp_type=exp_type, stack=stack))


@camera.command("stop-expose")
@click.pass_context
def camera_stop_expose(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].stop_exposure())


@camera.command("start-stack")
@click.option("--gain", required=True, type=int)
@click.option("--restart/--no-restart", default=True)
@click.pass_context
def camera_start_stack(ctx: click.Context, gain: int, restart: bool) -> None:
    _run(ctx, ctx.obj["client"].start_stack(gain=gain, restart=restart))


@camera.command("stop-view")
@click.option("--stage", default=None, help="Stage name, e.g. DarkLibrary, AutoGoto.")
@click.pass_context
def camera_stop_view(ctx: click.Context, stage: str | None) -> None:
    _run(ctx, ctx.obj["client"].stop_view(stage=stage))


@camera.command("set-gain")
@click.argument("gain", type=int)
@click.pass_context
def camera_set_gain(ctx: click.Context, gain: int) -> None:
    _run(ctx, ctx.obj["client"].set_gain(gain))


@camera.command("set-exposure")
@click.option("--stack-l", required=True, type=int, help="Stacking exposure (ms).")
@click.option("--continuous", required=True, type=int, help="Live view exposure (ms).")
@click.pass_context
def camera_set_exposure(ctx: click.Context, stack_l: int, continuous: int) -> None:
    _run(ctx, ctx.obj["client"].set_exposure(stack_l_ms=stack_l, continuous_ms=continuous))


@camera.command("set-brightness")
@click.argument("percent", type=int)
@click.pass_context
def camera_set_brightness(ctx: click.Context, percent: int) -> None:
    """Set auto-exposure brightness target (0-100)."""
    _run(ctx, ctx.obj["client"].set_brightness(percent=percent))


@camera.command("dark-frame")
@click.pass_context
def camera_dark_frame(ctx: click.Context) -> None:
    """Start dark frame creation."""
    _run(ctx, ctx.obj["client"].start_create_dark())


# ── focuser ───────────────────────────────────────────────────────────────

@cli.group()
def focuser() -> None:
    """Focuser control."""


@focuser.command("position")
@click.option("--ret-obj", is_flag=True, default=False)
@click.pass_context
def focuser_position(ctx: click.Context, ret_obj: bool) -> None:
    _run(ctx, ctx.obj["client"].get_focuser_position(ret_obj=ret_obj))


@focuser.command("set")
@click.option("--steps", required=True, type=int, help="Relative steps (positive or negative).")
@click.pass_context
def focuser_set(ctx: click.Context, steps: int) -> None:
    _run(ctx, ctx.obj["client"].adjust_focus(steps=steps))


@focuser.command("auto-focus")
@click.pass_context
def focuser_auto_focus(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].start_auto_focus())


@focuser.command("stop-auto-focus")
@click.pass_context
def focuser_stop_auto_focus(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].stop_auto_focus())


# ── filter ────────────────────────────────────────────────────────────────

@cli.group()
def filter() -> None:
    """Filter wheel control."""


@filter.command("position")
@click.pass_context
def filter_position(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_wheel_position())


@filter.command("state")
@click.pass_context
def filter_state(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_wheel_state())


@filter.command("setting")
@click.pass_context
def filter_setting(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_wheel_setting())


@filter.command("set")
@click.argument("position", type=int)
@click.pass_context
def filter_set(ctx: click.Context, position: int) -> None:
    """Move filter wheel to POSITION (1-based)."""
    _run(ctx, ctx.obj["client"].set_wheel_position(position=position))


@filter.command("lp-filter")
@click.option("--on/--off", "enabled", default=True)
@click.pass_context
def filter_lp(ctx: click.Context, enabled: bool) -> None:
    """Enable or disable the light-pollution filter."""
    _run(ctx, ctx.obj["client"].set_lp_filter(enabled=enabled))


# ── schedule ──────────────────────────────────────────────────────────────

@cli.group()
def schedule() -> None:
    """Scheduler management."""


@schedule.command("get")
@click.pass_context
def schedule_get(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_schedule())


@schedule.command("create")
@click.pass_context
def schedule_create(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].create_schedule())


@schedule.command("start")
@click.pass_context
def schedule_start(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].start_scheduler())


@schedule.command("stop")
@click.pass_context
def schedule_stop(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].stop_scheduler())


@schedule.command("pause")
@click.pass_context
def schedule_pause(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].pause_scheduler())


@schedule.command("continue")
@click.pass_context
def schedule_continue(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].continue_scheduler())


@schedule.command("reset")
@click.pass_context
def schedule_reset(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].reset_scheduler_cur_item())


@schedule.command("skip")
@click.pass_context
def schedule_skip(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].skip_scheduler_cur_item())


@schedule.command("remove")
@click.option("--id", "item_id", required=True, help="Schedule item ID to remove.")
@click.pass_context
def schedule_remove(ctx: click.Context, item_id: str) -> None:
    _run(ctx, ctx.obj["client"].remove_schedule_item(item_id))


@schedule.command("add-mosaic")
@click.option("--target", required=True)
@click.option("--ra", required=True)
@click.option("--dec", required=True)
@click.option("--time", "session_time_sec", required=True, type=int, help="Session time (s).")
@click.option("--panels-ra", default=1, type=int)
@click.option("--panels-dec", default=1, type=int)
@click.option("--overlap", default=20, type=int, help="Panel overlap %.")
@click.option("--gain", default=80, type=int)
@click.option("--lp-filter/--no-lp-filter", default=False)
@click.option("--autofocus/--no-autofocus", default=False)
@click.option("--j2000/--no-j2000", default=False)
@click.pass_context
def schedule_add_mosaic(
    ctx: click.Context,
    target: str,
    ra: str,
    dec: str,
    session_time_sec: int,
    panels_ra: int,
    panels_dec: int,
    overlap: int,
    gain: int,
    lp_filter: bool,
    autofocus: bool,
    j2000: bool,
) -> None:
    """Add a mosaic item to the schedule."""
    _run(
        ctx,
        ctx.obj["client"].schedule_mosaic(
            target_name=target,
            ra=ra,
            dec=dec,
            session_time_sec=session_time_sec,
            ra_num=panels_ra,
            dec_num=panels_dec,
            panel_overlap_percent=overlap,
            gain=gain,
            is_use_lp_filter=lp_filter,
            is_use_autofocus=autofocus,
            is_j2000=j2000,
        ),
    )


@schedule.command("add-wait-until")
@click.option("--time", "local_time", required=True, help="Local time HH:MM.")
@click.pass_context
def schedule_add_wait_until(ctx: click.Context, local_time: str) -> None:
    _run(ctx, ctx.obj["client"].schedule_wait_until(local_time=local_time))


@schedule.command("add-wait-for")
@click.option("--sec", required=True, type=int)
@click.pass_context
def schedule_add_wait_for(ctx: click.Context, sec: int) -> None:
    _run(ctx, ctx.obj["client"].schedule_wait_for(timer_sec=sec))


@schedule.command("add-auto-focus")
@click.option("--tries", default=2, type=int)
@click.pass_context
def schedule_add_auto_focus(ctx: click.Context, tries: int) -> None:
    _run(ctx, ctx.obj["client"].schedule_auto_focus(try_count=tries))


@schedule.command("add-focus")
@click.option("--steps", required=True, type=int)
@click.pass_context
def schedule_add_focus(ctx: click.Context, steps: int) -> None:
    _run(ctx, ctx.obj["client"].schedule_adjust_focus(steps=steps))


@schedule.command("add-shutdown")
@click.pass_context
def schedule_add_shutdown(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].schedule_shutdown())


@schedule.command("add-exposure")
@click.option("--stack-l", required=True, type=int, help="Stack exposure (ms).")
@click.option("--continuous", required=True, type=int, help="Live view exposure (ms).")
@click.pass_context
def schedule_add_exposure(ctx: click.Context, stack_l: int, continuous: int) -> None:
    _run(
        ctx,
        ctx.obj["client"].schedule_set_exposure(
            stack_l_ms=stack_l, continuous_ms=continuous
        ),
    )


@schedule.command("export")
@click.option("--path", required=True, help="Device-side file path.")
@click.pass_context
def schedule_export(ctx: click.Context, path: str) -> None:
    _run(ctx, ctx.obj["client"].export_schedule(filepath=path))


@schedule.command("import")
@click.option("--path", required=True, help="Device-side file path.")
@click.option("--retain-state/--no-retain-state", default=False)
@click.pass_context
def schedule_import(ctx: click.Context, path: str, retain_state: bool) -> None:
    _run(ctx, ctx.obj["client"].import_schedule(filepath=path, retain_state=retain_state))


# ── mosaic ────────────────────────────────────────────────────────────────

@cli.group()
def mosaic() -> None:
    """Direct mosaic and spectra capture (outside the scheduler)."""


@mosaic.command("start")
@click.option("--target", required=True)
@click.option("--ra", required=True)
@click.option("--dec", required=True)
@click.option("--time", "session_time_sec", required=True, type=int)
@click.option("--panels-ra", default=1, type=int)
@click.option("--panels-dec", default=1, type=int)
@click.option("--overlap", default=20, type=int)
@click.option("--gain", default=80, type=int)
@click.option("--lp-filter/--no-lp-filter", default=False)
@click.option("--autofocus/--no-autofocus", default=False)
@click.option("--j2000/--no-j2000", default=False)
@click.pass_context
def mosaic_start(
    ctx: click.Context,
    target: str,
    ra: str,
    dec: str,
    session_time_sec: int,
    panels_ra: int,
    panels_dec: int,
    overlap: int,
    gain: int,
    lp_filter: bool,
    autofocus: bool,
    j2000: bool,
) -> None:
    """Start a mosaic capture immediately."""
    _run(
        ctx,
        ctx.obj["client"].start_mosaic(
            target_name=target,
            ra=ra,
            dec=dec,
            session_time_sec=session_time_sec,
            ra_num=panels_ra,
            dec_num=panels_dec,
            panel_overlap_percent=overlap,
            gain=gain,
            is_use_lp_filter=lp_filter,
            is_use_autofocus=autofocus,
            is_j2000=j2000,
        ),
    )


@mosaic.command("spectra")
@click.option("--target", required=True)
@click.option("--ra", required=True)
@click.option("--dec", required=True)
@click.option("--time", "session_time_sec", required=True, type=int)
@click.option("--gain", default=120, type=int)
@click.option("--grating", default=300, type=int)
@click.option("--j2000/--no-j2000", default=False)
@click.pass_context
def mosaic_spectra(
    ctx: click.Context,
    target: str,
    ra: str,
    dec: str,
    session_time_sec: int,
    gain: int,
    grating: int,
    j2000: bool,
) -> None:
    """Start a spectrography session immediately."""
    _run(
        ctx,
        ctx.obj["client"].start_spectra(
            target_name=target,
            ra=ra,
            dec=dec,
            session_time_sec=session_time_sec,
            gain=gain,
            grating_lines=grating,
            is_j2000=j2000,
        ),
    )


# ── files ─────────────────────────────────────────────────────────────────

@cli.group()
def files() -> None:
    """Image and album management."""


@files.command("albums")
@click.pass_context
def files_albums(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_albums())


@files.command("last-image")
@click.option("--subframe/--no-subframe", default=True)
@click.option("--thumb/--no-thumb", default=False)
@click.option("--download", "download_path", default=None, type=click.Path())
@click.pass_context
def files_last_image(
    ctx: click.Context,
    subframe: bool,
    thumb: bool,
    download_path: str | None,
) -> None:
    """Get info about the last captured image, optionally downloading it."""

    async def _run_last_image() -> Any:
        client = ctx.obj["client"]
        meta = await client.get_last_image(is_subframe=subframe, is_thumb=thumb)
        if download_path and isinstance(meta, dict) and "url" in meta:
            data = await client.download_image(meta["url"])
            with open(download_path, "wb") as fh:
                fh.write(data)
            click.echo(f"Saved {len(data)} bytes → {download_path}", err=True)
        return meta

    _run(ctx, _run_last_image())


@files.command("img-name-field")
@click.pass_context
def files_img_name_field(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].get_img_name_field())


@files.command("set-img-name")
@click.option("--bin/--no-bin", default=True)
@click.option("--date-time/--no-date-time", default=True)
@click.option("--temp/--no-temp", default=True)
@click.option("--gain/--no-gain", default=True)
@click.option("--camera-name/--no-camera-name", default=False)
@click.pass_context
def files_set_img_name(
    ctx: click.Context,
    bin: bool,
    date_time: bool,
    temp: bool,
    gain: bool,
    camera_name: bool,
) -> None:
    _run(
        ctx,
        ctx.obj["client"].set_img_name_field(
            bin=bin, date_time=date_time, temp=temp, gain=gain, camera_name=camera_name
        ),
    )


@files.command("sequence-group")
@click.option("--name", required=True, help="Group name.")
@click.pass_context
def files_sequence_group(ctx: click.Context, name: str) -> None:
    _run(ctx, ctx.obj["client"].set_sequence_group_name(group_name=name))


@files.command("download")
@click.option("--url", required=True, help="Full image URL on the device.")
@click.option("--out", required=True, type=click.Path(), help="Local output path.")
@click.pass_context
def files_download(ctx: click.Context, url: str, out: str) -> None:
    """Download an image by URL and save locally."""

    async def _dl() -> dict:
        data = await ctx.obj["client"].download_image(url)
        with open(out, "wb") as fh:
            fh.write(data)
        return {"bytes": len(data), "path": out}

    _run(ctx, _dl())


# ── system ────────────────────────────────────────────────────────────────

@cli.group()
def system() -> None:
    """System control: startup, reboot, shutdown, heater."""


@system.command("startup")
@click.option("--lat", required=True, type=float)
@click.option("--lon", required=True, type=float)
@click.pass_context
def system_startup(ctx: click.Context, lat: float, lon: float) -> None:
    """Run the device startup sequence."""
    _run(ctx, ctx.obj["client"].startup_sequence(lat=lat, lon=lon))


@system.command("reboot")
@click.pass_context
def system_reboot(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].pi_reboot())


@system.command("shutdown")
@click.pass_context
def system_shutdown(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].pi_shutdown())


@system.command("is-verified")
@click.pass_context
def system_is_verified(ctx: click.Context) -> None:
    _run(ctx, ctx.obj["client"].pi_is_verified())


@system.command("heater")
@click.option("--on/--off", "state", default=True)
@click.option("--value", default=90, type=int, help="Heater power level (0-100).")
@click.pass_context
def system_heater(ctx: click.Context, state: bool, value: int) -> None:
    _run(ctx, ctx.obj["client"].set_heater(state=state, value=value))


@system.command("play-sound")
@click.option("--id", "sound_id", required=True, type=int, help="Sound ID.")
@click.pass_context
def system_play_sound(ctx: click.Context, sound_id: int) -> None:
    _run(ctx, ctx.obj["client"].play_sound(sound_id=sound_id))


@system.command("set-time")
@click.option("--time", "iso_time", required=True, help="ISO 8601 datetime string.")
@click.pass_context
def system_set_time(ctx: click.Context, iso_time: str) -> None:
    _run(ctx, ctx.obj["client"].pi_set_time(iso_time=iso_time))


@system.command("set-location")
@click.option("--lat", required=True, type=float)
@click.option("--lon", required=True, type=float)
@click.option("--alt", default=0.0, type=float)
@click.pass_context
def system_set_location(ctx: click.Context, lat: float, lon: float, alt: float) -> None:
    _run(ctx, ctx.obj["client"].set_user_location(lat=lat, lon=lon, alt=alt))
