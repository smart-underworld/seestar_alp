import io
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from emulator.firmware.provision import download_xapk, provision_firmware


def test_download_xapk_reuses_existing_cached_file(tmp_path):
    dest_dir = tmp_path / "cache"
    dest_dir.mkdir()
    cached = dest_dir / "firmware-2732.xapk"
    cached.write_bytes(b"cached-bytes")

    with patch("emulator.firmware.provision._fetch_xapk_bytes") as mock_fetch:
        result = download_xapk(version="3.1.2", version_code="2732", dest_dir=dest_dir)

    mock_fetch.assert_not_called()
    assert result == cached
    assert result.read_bytes() == b"cached-bytes"


def test_download_xapk_fetches_on_cache_miss(tmp_path):
    dest_dir = tmp_path / "cache"

    with patch("emulator.firmware.provision._fetch_xapk_bytes", return_value=b"fresh-bytes") as mock_fetch:
        result = download_xapk(version="3.1.2", version_code="2732", dest_dir=dest_dir)

    mock_fetch.assert_called_once_with("2732")
    assert result == dest_dir / "firmware-2732.xapk"
    assert result.read_bytes() == b"fresh-bytes"


def test_provision_firmware_extracts_and_unpacks_debs(tmp_path):
    # Build a minimal fake XAPK containing one tiny .deb so dpkg -x has
    # something real to unpack, exercising the full provision_firmware path
    # without touching the network.
    import tarfile
    import zipfile

    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # A trivial .deb: dpkg-deb needs a real archive, so build one with
    # dpkg-deb if available; otherwise skip (CI/dev machines running this
    # test are expected to have dpkg-deb, same as the emulator provisioning
    # step itself requires dpkg -x).
    if subprocess.run(["which", "dpkg-deb"], capture_output=True).returncode != 0:
        pytest.skip("dpkg-deb not available on this machine")

    pkg_root = tmp_path / "pkg_root"
    (pkg_root / "DEBIAN").mkdir(parents=True)
    (pkg_root / "DEBIAN" / "control").write_text(
        "Package: testpkg\nVersion: 1.0\nArchitecture: armhf\nMaintainer: test\nDescription: test\n"
    )
    (pkg_root / "usr" / "bin").mkdir(parents=True)
    (pkg_root / "usr" / "bin" / "hello").write_text("#!/bin/sh\necho hi\n")
    deb_path = tmp_path / "testpkg.deb"
    subprocess.run(["dpkg-deb", "--build", str(pkg_root), str(deb_path)], check=True)

    iscope_dir = tmp_path / "iscope_src"
    (iscope_dir / "deb").mkdir(parents=True)
    (iscope_dir / "deb" / "testpkg.deb").write_bytes(deb_path.read_bytes())

    tar_path = tmp_path / "iscope.tar.bz2"
    with tarfile.open(tar_path, "w:bz2") as tar:
        tar.add(iscope_dir / "deb", arcname="deb")

    xapk_path = tmp_path / "firmware-9999.xapk"
    with zipfile.ZipFile(xapk_path, "w") as z:
        z.writestr("manifest.json", "{}")
        io_buf = io.BytesIO()
        with zipfile.ZipFile(io_buf, "w") as inner:
            inner.writestr("assets/iscope", tar_path.read_bytes())
        z.writestr("base.apk", io_buf.getvalue())

    with patch("emulator.firmware.provision.download_xapk", return_value=xapk_path):
        deb_out = provision_firmware(version="9.9.9", version_code="9999", work_dir=work_dir)

    assert deb_out == work_dir / "9.9.9" / "iscope" / "deb" / "out"
    assert (deb_out / "usr" / "bin" / "hello").exists()
