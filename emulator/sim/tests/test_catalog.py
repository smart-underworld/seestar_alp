from sim import catalog, gen_catalog


def test_build_and_near(tmp_path):
    csv = tmp_path / "src.csv"
    csv.write_text(
        "ra_deg,dec_deg,mag\n10.0,20.0,5\n10.1,20.05,9\n200.0,-40.0,7\n10.2,20.1,13\n"
    )
    out = tmp_path / "c.npy"
    gen_catalog.build(str(csv), str(out), mag_limit=11.0)
    cat = catalog.load(str(out))
    assert cat.shape[1] == 3 and len(cat) == 3  # mag 13 dropped
    assert len(catalog.near(cat, 10.05, 20.05, 1.0)) == 2


def test_find_libastrometry_uses_whichever_multiarch_dir_the_image_has(monkeypatch):
    # armhf installs it under arm-linux-gnueabihf, arm64 under aarch64-linux-gnu;
    # a hardcoded armhf path made the arm64 lane's catalog step fail.
    from sim import build_catalog

    arm64 = "/usr/lib/aarch64-linux-gnu/libastrometry.so.0"
    monkeypatch.setattr(
        build_catalog.glob,
        "glob",
        lambda pat: [arm64] if pat == "/usr/lib/*/libastrometry.so.0" else [],
    )
    assert build_catalog.find_libastrometry() == arm64


def test_find_libastrometry_falls_back_to_the_armhf_path(monkeypatch):
    from sim import build_catalog

    monkeypatch.setattr(build_catalog.glob, "glob", lambda pat: [])
    assert build_catalog.find_libastrometry() == build_catalog.DEFAULT_LIB
