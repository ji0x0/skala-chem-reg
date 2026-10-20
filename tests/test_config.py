"""Step 0 — 설정과 구조화 로그가 약속대로 동작하는가."""
import json
import logging

import pytest
from pydantic import ValidationError

from app.core.config import ROOT_DIR, Settings
from app.core.logging import JsonFormatter


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert Settings(_env_file=None).log_level == "DEBUG"


def test_invalid_value_fails_at_startup(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "INFOO")          # 오타
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_root_dir_points_to_project():
    assert (ROOT_DIR / "pyproject.toml").exists()


def test_log_line_is_json_with_context_fields():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "노드 완료", None, None)
    record.node, record.latency_ms = "plan", 412
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "노드 완료" and line["node"] == "plan" and line["latency_ms"] == 412
