"""结构化日志 + 调试开关（SR-NF13「关键路径日志 + 健康检查/调试开关」）。

为什么单独一层：日志是**基础设施**，不属于任何业务域（core/ 是领域、api/ 是接口、
storage/ 是持久化）。放这里，三方都能用，又不会让领域层反向依赖接口层。

约定：
- 日志是**一行一条 JSON**（`logs/timeflow.jsonl`）：机器可读、能直接 grep/统计，不需要解析自由文本；
- **默认只记"发生了什么"**（事件名 + 关键字段），不记请求正文、不记备注内容 ——
  本项目是个人时间工具，日志里不该出现用户写的文字（隐私最小化）；需要细节时开 `--debug`；
- 调试开关只影响**日志级别**，不改任何业务行为（"调试"不能变成"另一种运行方式"）；
- 任何日志失败都**吞掉**（写不进日志不该让主流程挂掉 —— 但也绝不因此改变业务结果）。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

LOGGER_NAME = "timeflow"
DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "timeflow.jsonl"

# 环境变量开关（方便计划任务/脚本里开；命令行 `--debug` 走同一条路）
ENV_DEBUG = "TF_DEBUG"
ENV_LOG_PATH = "TF_LOG_PATH"
# `TF_LOG_PATH=off` / `none` → 只打控制台、不落文件（测试/临时运行用）
_DISABLE_VALUES = {"off", "none", "0", "false"}

_configured = False


class _JsonFormatter(logging.Formatter):
    """把日志记录成一行 JSON：`{ts, level, event, logger, ...}`。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)[-400:]
        return json.dumps(payload, ensure_ascii=False)


def debug_enabled() -> bool:
    """调试开关：`TF_DEBUG=1/true/yes/on` 视为开（大小写不敏感）。"""
    return os.environ.get(ENV_DEBUG, "").strip().lower() in {"1", "true", "yes", "on"}


def _project_root() -> Path:
    """项目根（日志默认落 `<根>/logs/`）——**不跟 CWD 走**，免得从别处启动时写到不知道的地方。"""
    from timeflow.config import ROOT

    return Path(ROOT)


class _CurrentStderrHandler(logging.StreamHandler[Any]):
    """每次 emit 都取**当前**的 `sys.stderr`，而不是配置那一刻的那个。

    ★ 为什么要有这个类（T-G65 实测踩到）：`logging.StreamHandler(stream=sys.stderr)`
    在**配置那一刻**就把流绑死了，而 pytest 的 `capsys` 每个用例都会换掉 `sys.stderr`（用完就关）。
    于是只要"第一次配置日志"发生在某个用了 `capsys` 的用例里，**后面**的用例一记日志就抛
    `ValueError: I/O operation on closed file`，logging 把它打成一段
    「--- Logging error --- + Traceback」写进**当前** stderr —— 而那条 stderr
    正是别的用例在断言的输出。症状很隐蔽：
    `test_broken_database_gives_a_stable_code_not_a_traceback` 会**随跑的先后顺序**时红时绿
    （单跑绿、按"先写命令再只读"的顺序跑就红）。绑死一个会被换掉的流本来就不对，这里改成每次现取。
    """

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


def setup_logging(
    debug: bool | None = None,
    log_path: str | Path | None = None,
    force: bool = False,
) -> Path | None:
    """配置日志：控制台 + 一行一条 JSON 的文件。返回日志文件路径（不可写时返回 None）。

    - `debug` 缺省看环境变量 `TF_DEBUG`；
    - `log_path` 缺省 `logs/timeflow.jsonl`（可用 `TF_LOG_PATH` 覆盖；相对路径按 CWD 解析）；
    - **幂等**：重复调用不会叠加 handler（除非 `force=True`，那是测试用的）；
    - 文件写不进去（只读目录/权限不足）→ 退回只打控制台，并在控制台说明原因，**不抛异常**。
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured and not force:
        return getattr(logger, "_tf_log_path", None)

    level = logging.DEBUG if (debug_enabled() if debug is None else debug) else logging.INFO
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = _JsonFormatter()
    stream = _CurrentStderrHandler()  # 不绑死 stderr：见上面那个类的注释（T-G65）
    stream.setFormatter(formatter)
    stream.setLevel(level)
    logger.addHandler(stream)

    raw_path = (
        log_path
        or os.environ.get(ENV_LOG_PATH)
        or Path(_project_root()) / DEFAULT_LOG_DIR / DEFAULT_LOG_FILE
    )
    path = Path(raw_path)
    written: Path | None = None
    if path.name.lower() in _DISABLE_VALUES or str(path).strip().lower() in _DISABLE_VALUES:
        logger._tf_log_path = None  # type: ignore[attr-defined]
        _configured = True
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)
        written = path
    except OSError as exc:  # 写不进日志不该挡住启动
        logger.warning(
            "file_log_unavailable", extra={"fields": {"path": str(path), "error": str(exc)}}
        )

    logger.propagate = False
    logger._tf_log_path = written  # type: ignore[attr-defined]
    _configured = True
    return written


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """记一条结构化事件（**一行一条 JSON**）。事件名用 `小写_下划线`，字段只放能机器读的值。

    刻意**不接受**自由文本字段（如备注内容）——个人数据不进日志。
    """
    logging.getLogger(LOGGER_NAME).log(level, event, extra={"fields": fields})


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
