from sim.pointing import from_radec, write_pointing, read_pointing


def test_from_radec_convention():
    p = from_radec(12.19, 3.53)
    assert abs(p.axle0 - 12.19 * 15) < 1e-6 and abs(p.axle1 - 3.53) < 1e-6


def test_roundtrip(tmp_path):
    seq = write_pointing(str(tmp_path), from_radec(2.5, 66.1))
    p = read_pointing(str(tmp_path))
    assert (
        p.seq == seq and abs(p.ra_hours - 2.5) < 1e-9 and abs(p.dec_deg - 66.1) < 1e-9
    )
