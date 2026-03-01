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


def test_get_current_gps_coordinates(monkeypatch):
    class Geo:
        def __init__(self, latlng):
            self.latlng = latlng

    monkeypatch.setattr("device.seestar_util.geocoder.ip", lambda _x: Geo([1.0, 2.0]))
    assert Util.get_current_gps_coordinates() == [1.0, 2.0]

    monkeypatch.setattr("device.seestar_util.geocoder.ip", lambda _x: Geo(None))
    assert Util.get_current_gps_coordinates() is None


def test_parse_coordinate_string_and_numeric_paths(monkeypatch):
    created = []

    class FakeCoord:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created.append(kwargs)

        def transform_to(self, _fk5):
            return "transformed"

    monkeypatch.setattr("device.seestar_util.SkyCoord", FakeCoord)

    result1 = Util.parse_coordinate(False, "12h00m00s", "+10d00m00s")
    assert isinstance(result1, FakeCoord)
    assert result1.kwargs["ra"] == "12h00m00s"

    result2 = Util.parse_coordinate(False, 12.0, 10.0)
    assert isinstance(result2, FakeCoord)
    assert "frame" in result2.kwargs

    result3 = Util.parse_coordinate(True, "12h00m00s", "+10d00m00s")
    assert result3 == "transformed"
    assert len(created) == 3


def test_get_altaz_helpers(monkeypatch):
    class Coord:
        def __init__(self):
            self.alt = type("Alt", (), {"deg": 11.1})()
            self.az = type("Az", (), {"deg": 22.2})()

        def transform_to(self, _frame):
            return self

    class Helper:
        @staticmethod
        def get_JNow(_ra, _dec):
            return Coord()

        @staticmethod
        def get_altaz(ra, dec, frame):
            return Util.get_altaz(Helper, ra, dec, frame)

    altaz = Util.get_altaz(Helper, 1.0, 2.0, object())
    assert altaz.alt.deg == 11.1

    arr = Util.get_altaz_deg(Helper, 1.0, 2.0, object())
    assert arr.tolist() == [11.1, 22.2]

    monkeypatch.setattr(
        "device.seestar_util.AltAz", lambda location: ("altaz", location)
    )
    frame = Util.get_altaz_frame(Helper, 3.0, 4.0)
    assert frame[0] == "altaz"
