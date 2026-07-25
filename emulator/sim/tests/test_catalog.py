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
