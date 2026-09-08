"""统一日志初始化：控制台 + 滚动文件，幂等可重复调用。"""
import logging
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

from app.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


@contextmanager
def timed_step(logger: logging.Logger, label: str, *args, level: int = logging.INFO):
    """记录一个执行步骤的耗时。args 为 label 的 % 参数，退出时自动追加 '用时=%.2fs'。"""
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.log(level, label + " 用时=%.2fs", *args, time.perf_counter() - start)


def setup_logging(settings: Settings) -> None:
    """初始化应用日志。每次调用重建自有 handler，因此幂等且测试安全（uvicorn --reload 场景不会叠加）。"""
    root = logging.getLogger("app")
    for handler in list(root.handlers):
        if getattr(handler, "_app_owned", False):
            root.removeHandler(handler)
            handler.close()

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    root.setLevel(settings.log_level.upper())
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._app_owned = True  # type: ignore[attr-defined]
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.log_dir / "backend.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._app_owned = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    # 第三方库降噪
    for noisy in ("httpx", "httpcore", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root.propagate = False
