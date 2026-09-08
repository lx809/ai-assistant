import logging
from logging.handlers import RotatingFileHandler

from app.config import Settings
from app.logging_setup import setup_logging


def _owned_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger("app").handlers if getattr(h, "_app_owned", False)]


def test_setup_logging_builds_console_and_file_handlers(tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", log_level="INFO")
    setup_logging(settings)
    handlers = _owned_handlers()
    assert len(handlers) == 2
    assert any(isinstance(h, RotatingFileHandler) for h in handlers)
    assert (tmp_path / "logs" / "backend.log").exists()


def test_setup_logging_is_idempotent(tmp_path):
    settings = Settings(log_dir=tmp_path / "logs")
    setup_logging(settings)
    setup_logging(settings)
    assert len(_owned_handlers()) == 2


def test_setup_logging_respects_level(tmp_path):
    settings = Settings(log_dir=tmp_path / "logs", log_level="WARNING")
    setup_logging(settings)
    assert logging.getLogger("app").level == logging.WARNING
