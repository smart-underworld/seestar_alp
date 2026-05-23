"""Tests for the Bruno .bru environment file parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.bru_parser import _parse_vars_block, load_env


# ── _parse_vars_block (unit) ──────────────────────────────────────────────


class TestParseVarsBlock:
    def test_parses_base_url_and_dev_num(self):
        text = "vars {\n  base_url: http://localhost:5555\n  dev_num: 1\n}\n"
        result = _parse_vars_block(text)
        assert result["base_url"] == "http://localhost:5555"
        assert result["dev_num"] == "1"

    def test_ignores_content_outside_vars_block(self):
        text = "meta { name: test }\nvars {\n  key: val\n}\nother { x: y }\n"
        result = _parse_vars_block(text)
        assert result == {"key": "val"}

    def test_empty_vars_block(self):
        text = "vars {\n}\n"
        assert _parse_vars_block(text) == {}

    def test_empty_file(self):
        assert _parse_vars_block("") == {}

    def test_no_vars_block(self):
        assert _parse_vars_block("meta { name: foo }\n") == {}

    def test_extra_whitespace_handled(self):
        text = "vars {\n   base_url :   http://192.168.1.1:5555   \n}\n"
        result = _parse_vars_block(text)
        assert result["base_url"] == "http://192.168.1.1:5555"

    def test_trailing_slash_in_url_preserved(self):
        text = "vars {\n  base_url: http://localhost:5555/\n}\n"
        result = _parse_vars_block(text)
        assert result["base_url"] == "http://localhost:5555/"

    def test_only_first_vars_block_read(self):
        text = "vars {\n  a: 1\n}\nvars {\n  b: 2\n}\n"
        result = _parse_vars_block(text)
        assert "a" in result
        assert "b" not in result

    def test_unknown_keys_returned(self):
        text = "vars {\n  my_custom_key: hello\n}\n"
        result = _parse_vars_block(text)
        assert result["my_custom_key"] == "hello"


# ── load_env (integration) ────────────────────────────────────────────────


class TestLoadEnv:
    def _write_bru(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "env.bru"
        p.write_text(content)
        return p

    def test_loads_valid_file(self, tmp_path):
        p = self._write_bru(
            tmp_path,
            "vars {\n  base_url: http://192.168.1.51:5555\n  dev_num: 2\n}\n",
        )
        result = load_env(p)
        assert result["base_url"] == "http://192.168.1.51:5555"
        assert result["dev_num"] == "2"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_env(tmp_path / "nonexistent.bru")

    def test_accepts_string_path(self, tmp_path):
        p = self._write_bru(tmp_path, "vars {\n  key: value\n}\n")
        result = load_env(str(p))
        assert result["key"] == "value"

    def test_accepts_path_object(self, tmp_path):
        p = self._write_bru(tmp_path, "vars {\n  key: value\n}\n")
        result = load_env(Path(p))
        assert result["key"] == "value"

    def test_empty_file_returns_empty(self, tmp_path):
        p = self._write_bru(tmp_path, "")
        assert load_env(p) == {}

    def test_file_with_no_vars_block(self, tmp_path):
        p = self._write_bru(tmp_path, "meta { name: test }\n")
        assert load_env(p) == {}

    def test_real_seestar_env_format(self, tmp_path):
        """Matches the actual format used in the repo's Bruno environments."""
        content = "vars {\n  base_url: http://192.168.1.51:5555\n  dev_num: 1\n}\n"
        p = self._write_bru(tmp_path, content)
        result = load_env(p)
        assert result["base_url"] == "http://192.168.1.51:5555"
        assert result["dev_num"] == "1"
