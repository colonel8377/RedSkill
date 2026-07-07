"""config.py — paths, constants, auto-detect project root.

ROOT is detected from __file__ (2 levels up from src/core/).
Override with REDSKILL_ROOT env var.
"""
from __future__ import annotations

import os
from pathlib import Path

# Auto-detect ROOT: src/core/config.py → src/core → src → ROOT
ROOT = Path(os.environ.get("REDSKILL_ROOT", Path(__file__).resolve().parent.parent.parent))

DATA_DIR = ROOT / "data"
DOWNLOADS_DIR = ROOT / "downloads"
DISCOVERED_PATH = ROOT / "discovered.json"
DB_PATH = DATA_DIR / "skills.db"
SCHEMA_PATH = ROOT / "src" / "schema.sql"
LOG_PATH = ROOT / "download_log.txt"
FAILED_PATH = ROOT / "download_failed.txt"
SEED_PATH = Path("/tmp/redskill_union.json")
CHECKPOINT_PATH = DATA_DIR / "checkpoint.jsonl"

# API endpoints
BASE_URL = "https://edith.xiaohongshu.com/api/sns/v1/creator/red_skill"
URL_LIST = f"{BASE_URL}/list_published_skills"
URL_SEARCH = f"{BASE_URL}/search_published_skills"
URL_BUNDLE = f"{BASE_URL}/get_skill_bundle"

# HTTP
UA = "redskill-crawl/1.0"
TIMEOUT_JSON = 30
TIMEOUT_ZIP = 120
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_ZIP_BYTES = 200 * 1024 * 1024
MAX_RETRY = 2
PAGE_LIMIT = 100

# Keywords for sweep fallback
SWEEP_KEYWORDS = [
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "写", "画", "做", "学", "看", "用", "找", "买", "玩", "聊",
    "ai", "gpt", "文案", "写作", "绘画", "设计", "工具", "助手",
    "小红书", "营销", "运营", "爆款", "笔记", "翻译", "总结",
    "代码", "编程", "效率", "模板", "攻略", "教程", "测评",
]
