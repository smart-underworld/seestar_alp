import device.version as version_mod
from device.version import Version


def test_git_version_cached(monkeypatch):
    class FakePopen:
        def __init__(self, cmd, stdout=None, stderr=None, env=None):
            self.cmd = cmd

        def communicate(self):
            if self.cmd[:2] == ["git", "describe"]:
                return [b"v1.2.3\n"]
            return [b""]

    version_mod._version = None
    monkeypatch.setattr(version_mod.subprocess, "Popen", FakePopen)

    first = Version.git_version()
    second = Version.git_version()
    assert first == "v1.2.3"
    assert second == "v1.2.3"


def test_app_version_reads_version_file(monkeypatch, tmp_path):
    vfile = tmp_path / "version.txt"
    vfile.write_text("v9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(version_mod, "search_path", str(tmp_path))

    assert Version.app_version() == "v9.9.9"


def test_app_version_falls_back_to_git_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(version_mod, "search_path", str(tmp_path))
    monkeypatch.setattr(Version, "git_version", staticmethod(lambda: "v0.0.1"))

    assert Version.app_version() == "v0.0.1"
