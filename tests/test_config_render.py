import tomlkit

from device.config import _Config


def make_config():
    cfg = _Config.__new__(_Config)
    cfg.path_to_dat = "/tmp/unused.toml"
    cfg._dict = {"network": {"port": 5555}}
    return cfg


def test_render_text_numeric_required():
    cfg = make_config()
    html = cfg.render_text("port", "Port", tomlkit.integer(5555), required=True)
    assert 'type="number"' in html
    assert "required" in html
    assert 'name="port"' in html


def test_render_checkbox_variants():
    cfg = make_config()
    visible = cfg.render_checkbox("feature", "Feature", True)
    assert 'type="checkbox"' in visible
    assert "checked" in visible

    hidden = cfg.render_checkbox("feature_hidden", "Feature", False, hidden=True)
    assert 'type="hidden"' in hidden


def test_render_select_marks_default_option():
    cfg = make_config()
    html = cfg.render_select("theme", "Theme", ["dark", "light"], "light")
    assert '<option value="light" selected>' in html
    assert '<option value="dark" ' in html


def test_set_toml_and_save_toml(tmp_path):
    cfg = make_config()
    cfg.path_to_dat = str(tmp_path / "config.toml")
    cfg.set_toml("network", "port", 6000)
    cfg.save_toml()

    content = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "port = 6000" in content
