import numpy as np
from astropy.io import fits
from sim.fits_io import write_solve_fits, write_raw_frame


def test_write_solve_fits_portrait_uint16(tmp_path):
    img = np.zeros((1920, 1080), dtype=np.uint16)
    img[100, 50] = 60000
    seq = write_solve_fits(str(tmp_path), img, header={"BAYERPAT": "GRBG"})
    assert (tmp_path / "solve.seq").read_text().strip() == str(seq)
    with fits.open(tmp_path / "solve.fits") as h:
        d = h[0].data
        assert d.shape == (1920, 1080)  # (NAXIS2, NAXIS1) = height, width
        assert h[0].header["BITPIX"] == 16
        assert int(h[0].header.get("BZERO", 0)) == 32768
        assert h[0].header["BAYERPAT"].strip() == "GRBG"
        assert int(d[100, 50]) == 60000
    assert write_solve_fits(str(tmp_path), img) == seq + 1


def test_write_raw_frame_native_endian(tmp_path):
    img = np.zeros((1920, 1080), dtype=np.uint16)
    img[100, 50] = 60000
    seq = write_raw_frame(str(tmp_path), img)
    assert (tmp_path / "live.seq").read_text().strip() == str(seq)
    raw = (tmp_path / "live.raw").read_bytes()
    assert len(raw) == 1920 * 1080 * 2
    arr = np.frombuffer(raw, dtype=np.uint16).reshape(1920, 1080)
    assert int(arr[100, 50]) == 60000
    assert write_raw_frame(str(tmp_path), img) == seq + 1


def test_write_raw_frame_casts_non_uint16(tmp_path):
    img = np.full((4, 4), 70000, dtype=np.int32)  # > 0xFFFF, must clip+cast
    write_raw_frame(str(tmp_path), img)
    raw = (tmp_path / "live.raw").read_bytes()
    arr = np.frombuffer(raw, dtype=np.uint16)
    assert arr.dtype == np.uint16 and int(arr[0]) == 0xFFFF
