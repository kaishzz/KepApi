import json
import os
import sys
from pathlib import Path
from typing import Any


def get_runtime_dir() -> Path:
    """返回脚本目录或 PyInstaller 可执行文件所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


RUNTIME_DIR = get_runtime_dir()
APP_CONFIG_PATH = RUNTIME_DIR / "app_config.json"
DOTENV_PATH = RUNTIME_DIR / ".env"


def _strip_wrapping_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _load_dotenv() -> None:
    if not DOTENV_PATH.exists():
        return

    with DOTENV_PATH.open("r", encoding="utf-8") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("export "):
                line = line[7:].lstrip()

            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or not key:
                raise ValueError(f".env 第 {line_number} 行格式无效")

            os.environ.setdefault(key, _strip_wrapping_quotes(value))


def _load_file_config() -> dict[str, Any]:
    if not APP_CONFIG_PATH.exists():
        return {}

    with APP_CONFIG_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("app_config.json 顶层必须是对象")
    return data


_load_dotenv()
_FILE_CONFIG = _load_file_config()
_DB_CONFIG = _FILE_CONFIG.get("database", {})
if not isinstance(_DB_CONFIG, dict):
    _DB_CONFIG = {}


def _read_setting(
    env_name: str,
    file_key: str,
    default: Any = None,
    *,
    cast=lambda value: value,
    section: dict[str, Any] | None = None,
    required: bool = False,
):
    raw_value = os.getenv(env_name)
    if raw_value is None:
        source = section if section is not None else _FILE_CONFIG
        raw_value = source.get(file_key)

    if raw_value is None:
        if required:
            raise ValueError(f"缺少必填配置项 {env_name}/{file_key}")
        raw_value = default

    try:
        return cast(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"配置项 {env_name}/{file_key} 的值无效: {raw_value!r}"
        ) from exc


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"无法解析布尔值: {value!r}")


def _to_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError(f"无法解析字符串列表: {value!r}")


LOG_FILE = str(RUNTIME_DIR / _read_setting("KEPAPI_LOG_FILE", "log_file", "kepapi.log"))
API_KEY = _read_setting("KEPAPI_API_KEY", "api_key", cast=str, required=True)
ADMIN_API_KEY = _read_setting(
    "KEPAPI_ADMIN_API_KEY",
    "admin_api_key",
    API_KEY,
    cast=str,
)
API_KEY_HEADER_NAMES = _read_setting(
    "KEPAPI_API_KEY_HEADER_NAMES",
    "api_key_header_names",
    ["x-api-key"],
    cast=_to_str_list,
)
ENABLE_DOCS = _read_setting(
    "KEPAPI_ENABLE_DOCS",
    "enable_docs",
    False,
    cast=_to_bool,
)
TRUST_PROXY_HEADERS = _read_setting(
    "KEPAPI_TRUST_PROXY_HEADERS",
    "trust_proxy_headers",
    False,
    cast=_to_bool,
)
TRUSTED_PROXY_CIDRS = _read_setting(
    "KEPAPI_TRUSTED_PROXY_CIDRS",
    "trusted_proxy_cidrs",
    [],
    cast=_to_str_list,
)

A2S_TIMEOUT = _read_setting("KEPAPI_A2S_TIMEOUT", "a2s_timeout", 5.0, cast=float)
SERVERLIST_A2S_TOTAL_TIMEOUT = _read_setting(
    "KEPAPI_SERVERLIST_A2S_TOTAL_TIMEOUT",
    "serverlist_a2s_total_timeout",
    6.0,
    cast=float,
)
A2S_MAX_RETRIES = _read_setting(
    "KEPAPI_A2S_MAX_RETRIES", "a2s_max_retries", 3, cast=int
)
SERVERLIST_A2S_CONCURRENCY = _read_setting(
    "KEPAPI_SERVERLIST_A2S_CONCURRENCY",
    "serverlist_a2s_concurrency",
    20,
    cast=int,
)

SERVERLIST_REFRESH_INTERVAL = _read_setting(
    "KEPAPI_SERVERLIST_REFRESH_INTERVAL", "serverlist_refresh_interval", 5.0, cast=float
)

SERVERLIST_LIMIT_PER_MINUTE = _read_setting(
    "KEPAPI_SERVERLIST_LIMIT_PER_MINUTE",
    "serverlist_limit_per_minute",
    300,
    cast=int,
)
API_BURST_LIMIT = _read_setting(
    "KEPAPI_API_BURST_LIMIT", "api_burst_limit", 80, cast=int
)
API_BURST_WINDOW_SECONDS = _read_setting(
    "KEPAPI_API_BURST_WINDOW_SECONDS",
    "api_burst_window_seconds",
    10.0,
    cast=float,
)
SERVERLIST_BURST_LIMIT = _read_setting(
    "KEPAPI_SERVERLIST_BURST_LIMIT", "serverlist_burst_limit", 60, cast=int
)
SERVERLIST_BURST_WINDOW_SECONDS = _read_setting(
    "KEPAPI_SERVERLIST_BURST_WINDOW_SECONDS",
    "serverlist_burst_window_seconds",
    10,
    cast=float,
)
WHITELIST_LIMIT_PER_MINUTE = _read_setting(
    "KEPAPI_WHITELIST_LIMIT_PER_MINUTE",
    "whitelist_limit_per_minute",
    180,
    cast=int,
)
WHITELIST_BURST_LIMIT = _read_setting(
    "KEPAPI_WHITELIST_BURST_LIMIT", "whitelist_burst_limit", 30, cast=int
)
WHITELIST_BURST_WINDOW_SECONDS = _read_setting(
    "KEPAPI_WHITELIST_BURST_WINDOW_SECONDS",
    "whitelist_burst_window_seconds",
    10.0,
    cast=float,
)
WHITELIST_REFRESH_INTERVAL = _read_setting(
    "KEPAPI_WHITELIST_REFRESH_INTERVAL",
    "whitelist_refresh_interval",
    30.0,
    cast=float,
)
AUTH_FAIL_LIMIT_PER_MINUTE = _read_setting(
    "KEPAPI_AUTH_FAIL_LIMIT_PER_MINUTE",
    "auth_fail_limit_per_minute",
    20,
    cast=int,
)
AUTH_BAN_SECONDS = _read_setting(
    "KEPAPI_AUTH_BAN_SECONDS", "auth_ban_seconds", 600, cast=int
)
RATE_LIMIT_STATE_CLEANUP_INTERVAL = _read_setting(
    "KEPAPI_RATE_LIMIT_STATE_CLEANUP_INTERVAL",
    "rate_limit_state_cleanup_interval",
    300,
    cast=float,
)
AUTH_BAN_STATE_CLEANUP_INTERVAL = _read_setting(
    "KEPAPI_AUTH_BAN_STATE_CLEANUP_INTERVAL",
    "auth_ban_state_cleanup_interval",
    300,
    cast=float,
)

DB_HOST = _read_setting(
    "KEPAPI_DB_HOST", "host", cast=str, section=_DB_CONFIG, required=True
)
DB_PORT = _read_setting(
    "KEPAPI_DB_PORT", "port", 3306, cast=int, section=_DB_CONFIG
)
DB_USER = _read_setting(
    "KEPAPI_DB_USER", "user", cast=str, section=_DB_CONFIG, required=True
)
DB_PASS = _read_setting(
    "KEPAPI_DB_PASS", "password", cast=str, section=_DB_CONFIG, required=True
)
DB_CHARSET = _read_setting(
    "KEPAPI_DB_CHARSET", "charset", "utf8mb4", cast=str, section=_DB_CONFIG
)

if not API_KEY_HEADER_NAMES:
    raise ValueError("api_key_header_names 不能为空")

if not str(ADMIN_API_KEY).strip():
    raise ValueError("admin_api_key 不能为空")

if TRUST_PROXY_HEADERS and not TRUSTED_PROXY_CIDRS:
    raise ValueError(
        "启用 trust_proxy_headers 时，必须同时配置 trusted_proxy_cidrs"
    )

for value, label in (
    (A2S_TIMEOUT, "a2s_timeout"),
    (SERVERLIST_A2S_TOTAL_TIMEOUT, "serverlist_a2s_total_timeout"),
    (SERVERLIST_REFRESH_INTERVAL, "serverlist_refresh_interval"),
    (SERVERLIST_BURST_WINDOW_SECONDS, "serverlist_burst_window_seconds"),
    (API_BURST_WINDOW_SECONDS, "api_burst_window_seconds"),
    (WHITELIST_BURST_WINDOW_SECONDS, "whitelist_burst_window_seconds"),
    (WHITELIST_REFRESH_INTERVAL, "whitelist_refresh_interval"),
    (RATE_LIMIT_STATE_CLEANUP_INTERVAL, "rate_limit_state_cleanup_interval"),
    (AUTH_BAN_STATE_CLEANUP_INTERVAL, "auth_ban_state_cleanup_interval"),
):
    if value <= 0:
        raise ValueError(f"{label} 必须大于 0")

for value, label in (
    (A2S_MAX_RETRIES, "a2s_max_retries"),
    (SERVERLIST_A2S_CONCURRENCY, "serverlist_a2s_concurrency"),
    (SERVERLIST_LIMIT_PER_MINUTE, "serverlist_limit_per_minute"),
    (API_BURST_LIMIT, "api_burst_limit"),
    (SERVERLIST_BURST_LIMIT, "serverlist_burst_limit"),
    (WHITELIST_LIMIT_PER_MINUTE, "whitelist_limit_per_minute"),
    (WHITELIST_BURST_LIMIT, "whitelist_burst_limit"),
    (AUTH_FAIL_LIMIT_PER_MINUTE, "auth_fail_limit_per_minute"),
    (AUTH_BAN_SECONDS, "auth_ban_seconds"),
):
    if value <= 0:
        raise ValueError(f"{label} 必须大于 0")
