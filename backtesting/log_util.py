"""
共享日志工具模块
所有回测脚本使用统一的日志配置
"""

import os
import logging
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logger(name: str, log_prefix: str = None) -> logging.Logger:
    """
    创建统一配置的 logger。
    - File handler: DEBUG 级别，写入 logs/{prefix}_{timestamp}.log
    - Console handler: INFO 级别，仅打印消息文本
    """
    if log_prefix is None:
        log_prefix = name

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"{log_prefix}_{timestamp}.log")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    logger.info(f"  日志文件: {log_file}")
    return logger
