import zipfile

import pytest

from emulator.firmware.extract_pem import _find_pem_blocks, extract_interop_pem


def test_find_pem_blocks_extracts_single_key_from_binary_noise():
    binary = (
        b"\x00\x01garbage\x02\x03-----BEGIN PRIVATE KEY-----\n"
        b"MIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA\n"
        b"-----END PRIVATE KEY-----\n\x00\x00more-noise\xff\xfe"
    )

    keys = _find_pem_blocks(binary)

    assert keys == [
        "-----BEGIN PRIVATE KEY-----\nMIIBVQIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA\n-----END PRIVATE KEY-----"
    ]


def test_find_pem_blocks_dedupes_repeated_key():
    key = "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----"
    binary = (key + "\x00garbage\x00" + key).encode()

    keys = _find_pem_blocks(binary)

    assert keys == [key]


def test_find_pem_blocks_returns_empty_when_no_key_present():
    assert _find_pem_blocks(b"\x00\x01no key here\x02\x03") == []


def test_extract_interop_pem_writes_key_from_apk(tmp_path):
    key = "-----BEGIN PRIVATE KEY-----\nAAAABBBBCCCC\n-----END PRIVATE KEY-----"
    so_bytes = b"\x7fELF\x00\x00garbage" + key.encode() + b"\x00\x00trailing"

    apk_path = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk_path, "w") as z:
        z.writestr("lib/armeabi-v7a/libopenssllib.so", so_bytes)

    out_path = tmp_path / "interop.pem"
    result = extract_interop_pem(str(apk_path), str(out_path))

    assert result == out_path
    assert out_path.read_text().strip() == key


def test_extract_interop_pem_raises_when_no_key_found(tmp_path):
    apk_path = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk_path, "w") as z:
        z.writestr(
            "lib/armeabi-v7a/libopenssllib.so", b"\x7fELF\x00\x00no key in here\x00"
        )

    with pytest.raises(RuntimeError, match="No interop private key found"):
        extract_interop_pem(str(apk_path), str(tmp_path / "interop.pem"))
