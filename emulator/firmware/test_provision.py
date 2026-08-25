import io
import shutil
import subprocess
import tarfile
import zipfile
from unittest.mock import patch

import pytest

from emulator.firmware.provision import (
    _extract_download_url,
    _fetch_xapk_bytes,
    _unpack_debs,
    download_xapk,
    provision_firmware,
)


def _build_asiair_deb(deb_path, imager_contents, extra_files=None):
    pkg_root = deb_path.parent / f"pkg_root_{deb_path.stem}"
    (pkg_root / "DEBIAN").mkdir(parents=True)
    (pkg_root / "DEBIAN" / "control").write_text(
        "Package: asiair\nVersion: 1.0\nArchitecture: armhf\nMaintainer: test\nDescription: test\n"
    )
    asiair_dir = pkg_root / "home" / "pi" / "ASIAIR"
    (asiair_dir / "bin").mkdir(parents=True)
    (asiair_dir / "bin" / "zwoair_imager").write_text(imager_contents)
    for rel, contents in (extra_files or {}).items():
        path = asiair_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    subprocess.run(["dpkg-deb", "--build", str(pkg_root), str(deb_path)], check=True)


def _build_other_deb(deb_path):
    # Stand-in for the non-asiair .debs (alpaca_libs, rsyslog, tzdata) a
    # delta release still ships alongside (or instead of) the asiair overlay.
    pkg_root = deb_path.parent / f"pkg_root_{deb_path.stem}"
    (pkg_root / "DEBIAN").mkdir(parents=True)
    (pkg_root / "DEBIAN" / "control").write_text(
        "Package: other\nVersion: 1.0\nArchitecture: armhf\nMaintainer: test\nDescription: test\n"
    )
    subprocess.run(["dpkg-deb", "--build", str(pkg_root), str(deb_path)], check=True)


def _build_iscope_xapk(xapk_path, deb_dir_builder, delta_overlay=None):
    iscope_dir = xapk_path.parent / f"iscope_src_{xapk_path.stem}"
    (iscope_dir / "deb").mkdir(parents=True)
    deb_dir_builder(iscope_dir / "deb")

    if delta_overlay is not None:
        for rel, contents in delta_overlay.items():
            path = (
                iscope_dir
                / "deb-build"
                / "asiair_armhf"
                / "home"
                / "pi"
                / "ASIAIR"
                / rel
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)

    tar_path = xapk_path.parent / f"{xapk_path.stem}.tar.bz2"
    with tarfile.open(tar_path, "w:bz2") as tar:
        tar.add(iscope_dir / "deb", arcname="deb")
        if delta_overlay is not None:
            tar.add(iscope_dir / "deb-build", arcname="deb-build")

    with zipfile.ZipFile(xapk_path, "w") as z:
        z.writestr("manifest.json", "{}")
        io_buf = io.BytesIO()
        with zipfile.ZipFile(io_buf, "w") as inner:
            inner.writestr("assets/iscope", tar_path.read_bytes())
        z.writestr("base.apk", io_buf.getvalue())


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


def test_provision_firmware_skips_pem_when_openssllib_absent(tmp_path):
    # Firmware predating the 7.18+ interop-auth requirement (e.g. an old
    # 2.x/3.0.x build) doesn't ship libopenssllib.so at all -- provisioning
    # must not fail for that, since device/seestar_device.py already treats
    # a missing/absent interop.pem as "no auth needed" (self-healing).
    import tarfile
    import zipfile

    work_dir = tmp_path / "work"
    work_dir.mkdir()

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

    # No libopenssllib.so anywhere in this XAPK.
    xapk_path = tmp_path / "firmware-1.0.0.xapk"
    with zipfile.ZipFile(xapk_path, "w") as z:
        z.writestr("manifest.json", "{}")
        io_buf = io.BytesIO()
        with zipfile.ZipFile(io_buf, "w") as inner:
            inner.writestr("assets/iscope", tar_path.read_bytes())
        z.writestr("base.apk", io_buf.getvalue())

    with patch("emulator.firmware.provision.download_xapk", return_value=xapk_path):
        deb_out = provision_firmware(version="1.0.0", work_dir=work_dir)

    assert deb_out == work_dir / "1.0.0" / "iscope" / "deb" / "out"
    assert (deb_out / "usr" / "bin" / "hello").exists()
    assert not (work_dir / "1.0.0" / "interop.pem").exists()


def test_provision_firmware_delta_release_overlays_onto_base_version(tmp_path):
    # A hypothetical delta release ships no asiair .deb at all -- just a
    # partial iscope/deb-build/asiair_armhf/home overlay containing only the
    # files that changed. provision_firmware must first provision the
    # declared base version (which has a full asiair .deb), then layer the
    # delta's overlay on top so the returned out/ tree has a complete,
    # patched home/pi/ASIAIR. (Real-world 3.3.1 looked like this at first
    # glance -- no asiair .deb -- but its deb-build/asiair_armhf/home turned
    # out to be a *complete* tree, not a partial one; see provision_firmware's
    # docstring and _merge_deb_build, which is what actually handles it.)
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    if subprocess.run(["which", "dpkg-deb"], capture_output=True).returncode != 0:
        pytest.skip("dpkg-deb not available on this machine")

    base_deb = tmp_path / "base_asiair.deb"
    _build_asiair_deb(
        base_deb,
        imager_contents="base imager binary",
        extra_files={"config": "base config"},
    )
    base_xapk = tmp_path / "firmware-1.0.0.xapk"
    _build_iscope_xapk(base_xapk, lambda deb_dir: shutil.copy(base_deb, deb_dir))

    other_deb = tmp_path / "other.deb"
    _build_other_deb(other_deb)

    delta_xapk = tmp_path / "firmware-1.0.1.xapk"
    _build_iscope_xapk(
        delta_xapk,
        lambda deb_dir: shutil.copy(other_deb, deb_dir),  # no asiair .deb here
        delta_overlay={
            "bin/zwoair_imager": "patched imager binary",
            "bin/new_tool": "new in the delta",
        },
    )

    xapks = {"1.0.0": base_xapk, "1.0.1": delta_xapk}

    with patch(
        "emulator.firmware.provision.download_xapk",
        side_effect=lambda version, dest_dir: xapks[version],
    ):
        deb_out = provision_firmware(
            version="1.0.1",
            work_dir=work_dir,
            delta_base={"1.0.1": "1.0.0"},
        )

    assert deb_out == work_dir / "1.0.1" / "iscope" / "deb" / "out"
    asiair_dir = deb_out / "home" / "pi" / "ASIAIR"
    # Delta overlay wins for a file it changed.
    assert (asiair_dir / "bin" / "zwoair_imager").read_text() == "patched imager binary"
    # A file the delta didn't touch is preserved from the base.
    assert (asiair_dir / "config").read_text() == "base config"
    # A file only the delta added is present.
    assert (asiair_dir / "bin" / "new_tool").read_text() == "new in the delta"


def test_provision_firmware_raises_when_declared_delta_has_no_overlay(tmp_path):
    # A version explicitly declared in delta_base is a promise that
    # iscope/deb-build/asiair_armhf/home exists in its XAPK. If it's
    # missing, silently falling back to "just the base version" would look
    # like a successful provision of firmware that's actually unpatched --
    # this must fail loudly instead.
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    if subprocess.run(["which", "dpkg-deb"], capture_output=True).returncode != 0:
        pytest.skip("dpkg-deb not available on this machine")

    base_deb = tmp_path / "base_asiair.deb"
    _build_asiair_deb(base_deb, imager_contents="base imager binary")
    base_xapk = tmp_path / "firmware-1.0.0.xapk"
    _build_iscope_xapk(base_xapk, lambda deb_dir: shutil.copy(base_deb, deb_dir))

    other_deb = tmp_path / "other.deb"
    _build_other_deb(other_deb)

    # No delta_overlay passed -- this XAPK has no deb-build/ at all.
    delta_xapk = tmp_path / "firmware-1.0.1.xapk"
    _build_iscope_xapk(delta_xapk, lambda deb_dir: shutil.copy(other_deb, deb_dir))

    xapks = {"1.0.0": base_xapk, "1.0.1": delta_xapk}

    with (
        patch(
            "emulator.firmware.provision.download_xapk",
            side_effect=lambda version, dest_dir: xapks[version],
        ),
        pytest.raises(RuntimeError, match="1.0.1"),
    ):
        provision_firmware(
            version="1.0.1",
            work_dir=work_dir,
            delta_base={"1.0.1": "1.0.0"},
        )


def test_provision_firmware_merges_deb_build_when_not_a_declared_delta(tmp_path):
    # Real-world 3.3.1: no asiair .deb, but a *complete* deb-build/asiair_armhf
    # tree and no delta_base entry. provision_firmware must merge deb-build/
    # straight onto the .deb-derived out/ tree -- no base version involved.
    if subprocess.run(["which", "dpkg-deb"], capture_output=True).returncode != 0:
        pytest.skip("dpkg-deb not available on this machine")

    other_deb = tmp_path / "other.deb"
    _build_other_deb(other_deb)

    xapk_path = tmp_path / "firmware-3.3.1.xapk"
    _build_iscope_xapk(
        xapk_path,
        lambda deb_dir: shutil.copy(other_deb, deb_dir),  # no asiair .deb
        delta_overlay={
            "bin/zwoair_imager": "complete imager binary",
            "config": "complete config",
        },
    )

    with patch("emulator.firmware.provision.download_xapk", return_value=xapk_path):
        deb_out = provision_firmware(
            version="3.3.1", work_dir=tmp_path / "work", delta_base={}
        )

    asiair_dir = deb_out / "home" / "pi" / "ASIAIR"
    assert (
        asiair_dir / "bin" / "zwoair_imager"
    ).read_text() == "complete imager binary"
    assert (asiair_dir / "config").read_text() == "complete config"


def test_unpack_debs_raises_when_a_package_fails_to_unpack(tmp_path):
    if shutil.which("dpkg") is None:
        pytest.skip("dpkg not available on this machine")

    deb_dir = tmp_path / "deb"
    deb_dir.mkdir()
    # Not a real .deb archive, so `dpkg -x` will fail against it.
    (deb_dir / "broken.deb").write_bytes(b"not a deb archive")

    with pytest.raises(RuntimeError, match="broken.deb"):
        _unpack_debs(deb_dir, tmp_path / "out")
