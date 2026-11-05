import importlib.util
import pathlib

import pytest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "scripts"
    / "make_win_version_file.py"
)
_spec = importlib.util.spec_from_file_location("make_win_version_file", _SCRIPT)
mwvf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mwvf)


@pytest.mark.parametrize(
    "git_version, expected",
    [
        ("v3.3.1", (3, 3, 1, 0)),
        ("v3.3.1\n", (3, 3, 1, 0)),
        ("v3.3.1-17-g5b35e2c", (3, 3, 1, 17)),
        ("v3.3.1-17-g5b35e2c-dirty", (3, 3, 1, 17)),
        ("v2.5", (2, 5, 0, 0)),
        ("5b35e2c", (0, 0, 0, 0)),
        ("", (0, 0, 0, 0)),
    ],
)
def test_parse_version(git_version, expected):
    assert mwvf.parse_version(git_version) == expected


def test_render_embeds_full_version_string():
    text = mwvf.render("v3.3.1-17-g5b35e2c-dirty\n")
    assert "StringStruct('FileVersion', 'v3.3.1-17-g5b35e2c-dirty')" in text
    assert "StringStruct('ProductVersion', 'v3.3.1-17-g5b35e2c-dirty')" in text
    assert "filevers=(3, 3, 1, 17)" in text


def test_written_file_evaluates_like_pyinstaller_loader(tmp_path):
    # PyInstaller's load_version_info_from_text_file() eval()s the file with its
    # versioninfo classes in scope. That module only imports on Windows, so eval
    # against recording stand-ins to check syntax and structure portably.
    out = tmp_path / "file_version_info.txt"
    assert mwvf.main(["x", "v3.3.1-17-g5b35e2c", str(out)]) == 0

    def rec(name):
        return lambda *a, **kw: (name, a, kw)

    names = [
        "VSVersionInfo",
        "FixedFileInfo",
        "StringFileInfo",
        "StringTable",
        "StringStruct",
        "VarFileInfo",
        "VarStruct",
    ]
    info = eval(out.read_text(encoding="utf-8"), {n: rec(n) for n in names})
    assert info[0] == "VSVersionInfo"
    ffi = info[2]["ffi"]
    assert ffi[2]["filevers"] == (3, 3, 1, 17)
    assert ffi[2]["prodvers"] == (3, 3, 1, 17)
    string_file_info = info[2]["kids"][0]
    string_table = string_file_info[1][0][0]
    strings = dict(s[1] for s in string_table[1][1])
    assert strings["FileVersion"] == "v3.3.1-17-g5b35e2c"
    assert strings["ProductVersion"] == "v3.3.1-17-g5b35e2c"
    assert strings["OriginalFilename"] == "seestar_alp.exe"


def test_main_usage_error():
    assert mwvf.main(["x"]) == 2
