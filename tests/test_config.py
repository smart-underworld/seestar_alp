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
