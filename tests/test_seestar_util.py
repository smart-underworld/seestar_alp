import math

from device.seestar_util import Util


def test_trim_seconds_formats_to_one_decimal():
    assert Util.trim_seconds("12h34m56.789s") == "12h34m56.8s"


def test_trim_seconds_non_time_passthrough():
    assert Util.trim_seconds("not-a-time") == "not-a-time"
    assert Util.trim_seconds(123) == 123


def test_mosaic_spacing_near_pole_uses_safe_ra_step():
    ra_step, dec_step = Util.mosaic_next_center_spacing(0.0, 86.0, 10)
    assert ra_step == 1.0
    assert math.isclose(dec_step, 1.161, rel_tol=1e-6)


def test_mosaic_spacing_at_equator():
    ra_step, dec_step = Util.mosaic_next_center_spacing(0.0, 0.0, 0)
    assert math.isclose(ra_step, 0.05, rel_tol=1e-6)
    assert math.isclose(dec_step, 1.29, rel_tol=1e-6)
