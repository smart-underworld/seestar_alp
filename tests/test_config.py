import os
import tempfile

import tomlkit

from device.config import _Config


def make_config():
    cfg = _Config.__new__(_Config)
    cfg.path_to_dat = "/tmp/unused.toml"
    return cfg


def test_str_to_bool_variants():
    assert _Config.strToBool(True) is True
    assert _Config.strToBool("true") is True
    assert _Config.strToBool(" YES ") is True
    assert _Config.strToBool("0") is False
    assert _Config.strToBool("false") is False


def test_load_uses_defaults_when_sections_missing():
    cfg = make_config()
    cfg.load("", preloaded_dict={})

    assert cfg.ip_address == "127.0.0.1"
    assert cfg.port == 5555
    assert cfg.uiport == 5432
    assert cfg.verify_injection is True
    assert cfg.seestars[0]["name"] == "Seestar Alpha"
    assert cfg.seestars[0]["device_num"] == 1


def test_load_renumbers_invalid_device_numbers():
    cfg = make_config()
    cfg.load(
        "",
        preloaded_dict={
            "seestars": [
                {
                    "name": "A",
                    "ip_address": "10.0.0.1",
                    "is_EQ_mode": False,
                    "device_num": 99,
                },
                {
                    "name": "B",
                    "ip_address": "10.0.0.2",
                    "is_EQ_mode": True,
                    "device_num": 100,
                },
            ]
        },
    )

    assert [d["device_num"] for d in cfg.seestars] == [1, 2]


def test_load_preserves_valid_device_numbers():
    cfg = make_config()
    cfg.load(
        "",
        preloaded_dict={
            "seestars": [
                {
                    "name": "A",
                    "ip_address": "10.0.0.1",
                    "is_EQ_mode": False,
                    "device_num": 1,
                },
                {
                    "name": "B",
                    "ip_address": "10.0.0.2",
                    "is_EQ_mode": True,
                    "device_num": 2,
                },
            ]
        },
    )

    assert [d["device_num"] for d in cfg.seestars] == [1, 2]


def test_load_reads_network_section():
    cfg = make_config()
    cfg.load(
        "",
        preloaded_dict={
            "network": {"ip_address": "192.168.1.50", "port": 4444, "timeout": 10}
        },
    )
    assert cfg.ip_address == "192.168.1.50"
    assert cfg.port == 4444
    assert cfg.timeout == 10


def test_load_reads_verify_injection_from_device_section():
    cfg = make_config()
    cfg.load("", preloaded_dict={"device": {"verify_injection": False}})
    assert cfg.verify_injection is False


def test_load_fixup_save_frames_dir_bool_string():
    """save_frames_dir set to the string 'True' or 'False' must be reset to '.'."""
    cfg = make_config()
    cfg.load("", preloaded_dict={"webui_settings": {"save_frames_dir": "True"}})
    assert cfg.save_frames_dir == "."

    cfg2 = make_config()
    cfg2.load("", preloaded_dict={"webui_settings": {"save_frames_dir": "False"}})
    assert cfg2.save_frames_dir == "."


def test_load_fixup_loading_gif_bool_string():
    """loading_gif set to 'True' or 'False' must be reset to 'loading.gif'."""
    cfg = make_config()
    cfg.load("", preloaded_dict={"webui_settings": {"loading_gif": "True"}})
    assert cfg.loading_gif == "loading.gif"

    cfg2 = make_config()
    cfg2.load("", preloaded_dict={"webui_settings": {"loading_gif": "False"}})
    assert cfg2.loading_gif == "loading.gif"


def test_get_toml_returns_default_for_missing_section():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    assert cfg.get_toml("no_such_section", "no_such_key", "fallback") == "fallback"


def test_get_toml_returns_default_for_missing_key():
    cfg = make_config()
    cfg.load("", preloaded_dict={"network": {}})
    assert cfg.get_toml("network", "no_such_key", 42) == 42


def test_str_to_bool_falsy_variants():
    assert _Config.strToBool("no") is False
    assert _Config.strToBool("off") is False
    assert _Config.strToBool("") is False
    assert _Config.strToBool(False) is False


def test_str_to_bool_truthy_variants():
    assert _Config.strToBool("1") is True
    assert _Config.strToBool("on") is True
    assert _Config.strToBool("y") is True
    assert _Config.strToBool("Y") is True


# ---------------------------------------------------------------------------
# set_toml
# ---------------------------------------------------------------------------


def test_set_toml_writes_into_dict():
    cfg = make_config()
    cfg.load("", preloaded_dict={"network": {"port": 5555}})
    cfg.set_toml("network", "port", 9999)
    assert cfg._dict["network"]["port"] == 9999


# ---------------------------------------------------------------------------
# load_toml — default (None) path
# ---------------------------------------------------------------------------


def test_load_toml_uses_path_to_dat_when_none(monkeypatch, tmp_path):
    """load_toml(None) should fall through to self.path_to_dat."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text("[network]\nport = 1234\n")

    cfg = make_config()
    cfg.path_to_dat = str(toml_path)
    cfg.load_toml(None)
    assert cfg.port == 1234


# ---------------------------------------------------------------------------
# save_toml — happy path and error path
# ---------------------------------------------------------------------------


def test_save_toml_writes_file(tmp_path):
    cfg = make_config()
    cfg.load("", preloaded_dict={"network": {"port": 4242}})
    out = tmp_path / "out.toml"
    cfg.path_to_dat = str(out)
    cfg.save_toml(str(out))
    contents = out.read_text()
    assert "4242" in contents


def test_save_toml_uses_path_to_dat_when_none(tmp_path):
    cfg = make_config()
    cfg.load("", preloaded_dict={"network": {"port": 7777}})
    out = tmp_path / "cfg.toml"
    cfg.path_to_dat = str(out)
    cfg.save_toml()
    assert out.exists()
    assert "7777" in out.read_text()


def test_save_toml_cleans_up_tmp_on_error(tmp_path, monkeypatch):
    """If writing raises, the .tmp file must be removed and the exception re-raised."""
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    out = tmp_path / "cfg.toml"
    cfg.path_to_dat = str(out)

    original_open = open

    def bad_open(path, *args, **kwargs):
        fh = original_open(path, *args, **kwargs)
        # Create the file then blow up on flush/fsync
        fh.write = lambda _data: (_ for _ in ()).throw(OSError("disk full"))
        return fh

    monkeypatch.setattr("builtins.open", bad_open)
    import pytest

    with pytest.raises(OSError):
        cfg.save_toml(str(out))
    # .tmp file must not be left behind
    assert not os.path.exists(str(out) + ".tmp")


# ---------------------------------------------------------------------------
# HTML render helpers
# ---------------------------------------------------------------------------


def test_render_text_produces_text_input():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    html = cfg.render_text("myfield", "My Label", "hello")
    assert 'name="myfield"' in html
    assert 'type="text"' in html
    assert 'value="hello"' in html
    assert "My Label" in html


def test_render_text_number_type_for_tomlkit_integer():
    cfg = make_config()
    cfg.load("", preloaded_dict={"network": {"port": 5555}})
    # tomlkit.loads produces tomlkit.items.Integer for numeric values
    toml_val = tomlkit.loads("[s]\nv = 42\n")["s"]["v"]
    html = cfg.render_text("v", "V", toml_val)
    assert 'type="number"' in html


def test_render_text_required_flag():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    html = cfg.render_text("f", "F", "x", required=True)
    assert "required" in html


def test_render_checkbox_visible():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    html = cfg.render_checkbox("cb", "Check me", True)
    assert 'name="cb"' in html
    assert "checked" in html
    assert "Check me" in html


def test_render_checkbox_hidden():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    html = cfg.render_checkbox("hcb", "Hidden", False, hidden=True)
    assert 'type="hidden"' in html


def test_render_select_marks_default_selected():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    html = cfg.render_select("theme", "Theme", ["dark", "light"], "dark")
    assert 'value="dark" selected' in html
    assert 'value="light" ' in html
    assert "selected" not in html.split('value="light"')[1].split(">")[0]


def test_render_config_section_with_id():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    html = cfg.render_config_section("My Title", "<p>body</p>", id="sec1")
    assert "My Title" in html
    assert 'id="sec1"' in html
    assert "<p>body</p>" in html


def test_render_config_section_without_id():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    html = cfg.render_config_section("T", "content")
    assert "T" in html
    assert 'id="' not in html


# ---------------------------------------------------------------------------
# render_seestars
# ---------------------------------------------------------------------------


def test_render_seestars_shows_all_devices():
    cfg = make_config()
    cfg.load(
        "",
        preloaded_dict={
            "seestars": [
                {
                    "name": "Alpha",
                    "ip_address": "10.0.0.1",
                    "device_num": 1,
                    "is_EQ_mode": False,
                },
                {
                    "name": "Beta",
                    "ip_address": "10.0.0.2",
                    "device_num": 2,
                    "is_EQ_mode": True,
                },
            ]
        },
    )
    html = cfg.render_seestars()
    assert "Alpha" in html
    assert "Beta" in html
    assert "device_div_1" in html
    assert "device_div_2" in html


def test_render_seestars_eq_mode_checked():
    cfg = make_config()
    cfg.load(
        "",
        preloaded_dict={
            "seestars": [
                {
                    "name": "X",
                    "ip_address": "1.2.3.4",
                    "device_num": 1,
                    "is_EQ_mode": True,
                },
            ]
        },
    )
    html = cfg.render_seestars()
    assert "checked" in html


# ---------------------------------------------------------------------------
# convert_AOT
# ---------------------------------------------------------------------------


def test_convert_aot_returns_list_of_seestars():
    cfg = make_config()
    cfg.load("", preloaded_dict={})
    settings = {
        "seestars": [
            {"name": "A", "ip_address": "1.1.1.1", "device_num": 1},
            {"name": "B", "ip_address": "2.2.2.2", "device_num": 2},
        ]
    }
    result = cfg.convert_AOT(settings)
    assert len(result) == 2
    assert result[0]["name"] == "A"
    assert result[1]["name"] == "B"


# ---------------------------------------------------------------------------
# load_from_form
# ---------------------------------------------------------------------------


class FakeRequest:
    """Minimal stand-in for a Falcon request with a media dict."""

    def __init__(self, media):
        self.media = media


def _base_form_media(**overrides):
    """Return a complete form media dict with sensible defaults."""
    media = {
        "ss_name": "Test Scope",
        "ss_ip_address": "192.168.1.99",
        "ip_address": "127.0.0.1",
        "port": "5555",
        "imgport": "7556",
        "stport": "8090",
        "sthost": "localhost",
        "timeout": "5",
        "uiport": "5432",
        "uitheme": "dark",
        "save_frames_dir": "/tmp",
        "loading_gif": "loading.gif",
        "text_color": "",
        "font_family": "",
        "font_url": "",
        "link_color": "",
        "accent_color": "",
        "location": "Anywhere",
        "step_size": "1.0",
        "steps_per_sec": "6",
        "log_level": "INFO",
        "log_prefix": "",
        "max_size_mb": "5",
        "num_keep_logs": "10",
        "init_lat": "0.0",
        "init_long": "0.0",
        "init_gain": "80",
        "init_expo_preview_ms": "500",
        "init_expo_stack_ms": "10000",
        "init_dither_length_pixel": "50",
        "init_dither_frequency": "10",
        "init_dew_heater_power": "0",
        "dec_pos_index": "3",
        "battery_low_limit": "3",
    }
    media.update(overrides)
    return media


def make_loaded_config():
    """Return a _Config already loaded with a tomlkit-backed dict (required for set_toml)."""
    cfg = make_config()
    raw_toml = tomlkit.loads("""
[network]
ip_address = "127.0.0.1"
port = 5555
imgport = 7556
stport = 8090
sthost = "localhost"
timeout = 5
rtsp_udp = true

[webui_settings]
uiport = 5432
uitheme = "dark"
experimental = false
confirm = true
save_frames = false
save_frames_dir = "."
loading_gif = "loading.gif"
text_color = ""
font_family = ""
font_url = ""
link_color = ""
accent_color = ""

[server]
location = "Anywhere"
verbose_driver_exceptions = true

[device]
can_reverse = true
step_size = 1.0
steps_per_sec = 6
verify_injection = true

[logging]
log_level = "INFO"
log_prefix = ""
log_to_stdout = false
max_size_mb = 5
num_keep_logs = 10
log_events_in_info = false

[seestar_initialization]
save_good_frames = true
save_all_frames = true
lat = 0.0
long = 0.0
gain = 80
exposure_length_preview_ms = 500
exposure_length_stack_ms = 10000
dither_enabled = true
dither_length_pixel = 50
dither_frequency = 10
activate_LP_filter = false
dew_heater_power = 0
is_EQ_mode = false
guest_mode_init = true
dec_pos_index = 3
battery_low_limit = 3

[[seestars]]
name = "Alpha"
ip_address = "10.0.0.1"
device_num = 1
is_EQ_mode = false
""")
    cfg._dict = raw_toml
    cfg.seestars = list(raw_toml["seestars"])
    cfg.path_to_dat = "/tmp/unused_form.toml"
    return cfg


def test_load_from_form_single_device(monkeypatch, tmp_path):
    cfg = make_loaded_config()
    # Prevent actual disk write from load() at the end of load_from_form
    monkeypatch.setattr(cfg, "load", lambda path, preloaded_dict=None: None)

    req = FakeRequest(_base_form_media())
    cfg.load_from_form(req)

    assert len(cfg.seestars) == 1
    assert cfg.seestars[0]["name"] == "Test Scope"
    assert cfg.seestars[0]["ip_address"] == "192.168.1.99"
    assert cfg.seestars[0]["device_num"] == 1


def test_load_from_form_multi_device(monkeypatch):
    cfg = make_loaded_config()
    monkeypatch.setattr(cfg, "load", lambda path, preloaded_dict=None: None)

    media = _base_form_media(
        ss_name=["Scope A", "Scope B"],
        ss_ip_address=["10.0.0.1", "10.0.0.2"],
    )
    req = FakeRequest(media)
    cfg.load_from_form(req)

    assert len(cfg.seestars) == 2
    assert cfg.seestars[0]["name"] == "Scope A"
    assert cfg.seestars[1]["name"] == "Scope B"
    assert cfg.seestars[1]["device_num"] == 2


def test_load_from_form_skips_deleted_devices(monkeypatch):
    cfg = make_loaded_config()
    monkeypatch.setattr(cfg, "load", lambda path, preloaded_dict=None: None)

    media = _base_form_media(
        ss_name=["Keep", "Gone"],
        ss_ip_address=["10.0.0.1", "10.0.0.2"],
        delete_2="true",
    )
    req = FakeRequest(media)
    cfg.load_from_form(req)

    assert len(cfg.seestars) == 1
    assert cfg.seestars[0]["name"] == "Keep"


def test_load_from_form_sets_network_values(monkeypatch):
    cfg = make_loaded_config()
    monkeypatch.setattr(cfg, "load", lambda path, preloaded_dict=None: None)

    req = FakeRequest(_base_form_media(ip_address="10.1.2.3", port="6666"))
    cfg.load_from_form(req)

    assert cfg._dict["network"]["ip_address"] == "10.1.2.3"
    assert cfg._dict["network"]["port"] == 6666
