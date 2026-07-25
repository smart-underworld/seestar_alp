import io
import shutil
import subprocess
from unittest.mock import patch

import pytest

from emulator.firmware.provision import (
    _extract_download_url,
    _fetch_xapk_bytes,
    _unpack_debs,
    download_xapk,
    provision_firmware,
)


def test_download_xapk_reuses_existing_cached_file(tmp_path):
    dest_dir = tmp_path / "cache"
    dest_dir.mkdir()
    cached = dest_dir / "firmware-3.1.2.xapk"
    cached.write_bytes(b"cached-bytes")

    with patch("emulator.firmware.provision._fetch_xapk_bytes") as mock_fetch:
        result = download_xapk(version="3.1.2", dest_dir=dest_dir)

    mock_fetch.assert_not_called()
    assert result == cached
    assert result.read_bytes() == b"cached-bytes"


def test_download_xapk_fetches_on_cache_miss(tmp_path):
    dest_dir = tmp_path / "cache"

    with patch(
        "emulator.firmware.provision._fetch_xapk_bytes", return_value=b"fresh-bytes"
    ) as mock_fetch:
        result = download_xapk(version="3.1.2", dest_dir=dest_dir)

    mock_fetch.assert_called_once_with("3.1.2")
    assert result == dest_dir / "firmware-3.1.2.xapk"
    assert result.read_bytes() == b"fresh-bytes"


def test_extract_download_url_finds_url_for_matching_version():
    # Synthetic blob shaped like the real api.pureapk.com response: for each
    # version, a "<version>:" marker (preceded by a non-digit byte, matching
    # the app_version API's protobuf-ish framing) followed by padding bytes,
    # then an "XAPKJ"-prefixed download URL two bytes later.
    blob = (
        b"\x08\x011.2.0:\x00\x00garbage-between-fieldsXAPKJ\x01\x02"
        b"https://download.pureapk.com/old-url?x=1"
        b"\x08\x023.3.0:\x00\x00more-binary-noiseXAPKJ\x03\x04"
        b"https://download.pureapk.com/b/XAPK/newversion?y=2"
    )

    url = _extract_download_url(blob, "3.3.0")

    assert url == "https://download.pureapk.com/b/XAPK/newversion?y=2"


def test_extract_download_url_raises_when_version_not_found():
    blob = b"\x081.0.0:\x00\x00XAPKJ\x01\x02https://download.pureapk.com/x"

    with pytest.raises(RuntimeError, match="9.9.9"):
        _extract_download_url(blob, "9.9.9")


def test_fetch_xapk_bytes_queries_app_version_api_and_downloads_file(monkeypatch):
    blob = b"\x08\x023.3.0:\x00\x00noiseXAPKJ\x01\x02https://download.pureapk.com/fake?token=abc"

    class FakeResponse:
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code

    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        if "api.pureapk.com" in url:
            return FakeResponse(blob)
        return FakeResponse(b"fake-xapk-bytes")

    monkeypatch.setattr("emulator.firmware.provision.requests.get", fake_get)

    data = _fetch_xapk_bytes("3.3.0")

    assert data == b"fake-xapk-bytes"
    assert any("api.pureapk.com" in c for c in calls)
    assert any("download.pureapk.com/fake" in c for c in calls)


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

    interop_key = (
        "-----BEGIN PRIVATE KEY-----\nFAKEKEYFORTESTING\n-----END PRIVATE KEY-----"
    )
    fake_so = b"\x7fELF\x00\x00noise" + interop_key.encode() + b"\x00trailing"

    xapk_path = tmp_path / "firmware-9.9.9.xapk"
    with zipfile.ZipFile(xapk_path, "w") as z:
        z.writestr("manifest.json", "{}")
        io_buf = io.BytesIO()
        with zipfile.ZipFile(io_buf, "w") as inner:
            inner.writestr("assets/iscope", tar_path.read_bytes())
            inner.writestr("lib/armeabi-v7a/libopenssllib.so", fake_so)
        z.writestr("base.apk", io_buf.getvalue())

    with patch("emulator.firmware.provision.download_xapk", return_value=xapk_path):
        deb_out = provision_firmware(version="9.9.9", work_dir=work_dir)

    assert deb_out == work_dir / "9.9.9" / "iscope" / "deb" / "out"
    assert (deb_out / "usr" / "bin" / "hello").exists()

    pem_path = work_dir / "9.9.9" / "interop.pem"
    assert pem_path.read_text().strip() == interop_key


def test_unpack_debs_raises_when_a_package_fails_to_unpack(tmp_path):
    if shutil.which("dpkg") is None:
        pytest.skip("dpkg not available on this machine")

    deb_dir = tmp_path / "deb"
    deb_dir.mkdir()
    # Not a real .deb archive, so `dpkg -x` will fail against it.
    (deb_dir / "broken.deb").write_bytes(b"not a deb archive")

    with pytest.raises(RuntimeError, match="broken.deb"):
        _unpack_debs(deb_dir, tmp_path / "out")
