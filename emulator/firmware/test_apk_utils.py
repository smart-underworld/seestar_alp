import zipfile

import pytest

from emulator.firmware.apk_utils import NoMatchingSplitError, open_apk


def test_open_apk_raises_no_matching_split_error_when_containing_not_found(tmp_path):
    xapk_path = tmp_path / "fake.xapk"
    with zipfile.ZipFile(xapk_path, "w") as z:
        z.writestr("manifest.json", "{}")
        with zipfile.ZipFile(xapk_path.with_suffix(".inner"), "w"):
            pass
        z.write(xapk_path.with_suffix(".inner"), "base.apk")

    with pytest.raises(NoMatchingSplitError, match="does/not/exist"):
        with open_apk(str(xapk_path), containing=["does/not/exist"]):
            pass
