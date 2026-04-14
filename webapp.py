import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from app_config import (
    API_BURST_LIMIT,
    API_BURST_WINDOW_SECONDS,
    API_KEY,
    API_KEY_HEADER_NAMES,
    ADMIN_API_KEY,
    A2S_MAX_RETRIES,
    A2S_TIMEOUT,
    AUTH_BAN_SECONDS,
    AUTH_BAN_STATE_CLEANUP_INTERVAL,
    AUTH_FAIL_LIMIT_PER_MINUTE,
    COMMUNITY_SERVERLIST_REFRESH_INTERVAL,
    ENABLE_DOCS,
    RATE_LIMIT_STATE_CLEANUP_INTERVAL,
    SERVERLIST_A2S_CONCURRENCY,
    SERVERLIST_A2S_TOTAL_TIMEOUT,
    SERVERLIST_BURST_LIMIT,
    SERVERLIST_BURST_WINDOW_SECONDS,
    SERVERLIST_LIMIT_PER_MINUTE,
    SERVERLIST_REFRESH_INTERVAL,
    TRUSTED_PROXY_CIDRS,
    TRUST_PROXY_HEADERS,
    WHITELIST_BURST_LIMIT,
    WHITELIST_BURST_WINDOW_SECONDS,
    WHITELIST_LIMIT_PER_MINUTE,
    WHITELIST_REFRESH_INTERVAL,
)
from cache_manager import SnapshotCacheStore, stop_background_task
from catalog_service import (
    create_community_server,
    create_kepcs_server,
    delete_community_server,
    delete_kepcs_server,
    ensure_catalog_tables,
    fetch_community_server_rows,
    list_community_servers,
    list_kepcs_servers,
    update_community_server,
    update_kepcs_server,
)
from db import engine
from security import (
    AuthManager,
    RateLimitRule,
    SlidingWindowLimiter,
    parse_trusted_proxy_networks,
)
from serverlist_service import (
    build_server_item,
    fetch_database_server_rows,
    fetch_whitelist_rows,
    now_str,
)


logger = logging.getLogger("kepapi")

RefreshFunc = Callable[[], Awaitable[int]]


@dataclass(frozen=True)
class RefreshJob:
    name: str
    interval_seconds: float
    refresh_once: RefreshFunc


_background_tasks: dict[str, asyncio.Task] = {}
_background_stop_event: asyncio.Event | None = None

_serverlist_a2s_semaphore = asyncio.Semaphore(SERVERLIST_A2S_CONCURRENCY)
_serverlist_cache_store = SnapshotCacheStore()
_community_serverlist_cache_store = SnapshotCacheStore()
_whitelist_cache_store = SnapshotCacheStore()

_trusted_proxy_networks = parse_trusted_proxy_networks(TRUSTED_PROXY_CIDRS)
_rate_limiter = SlidingWindowLimiter(RATE_LIMIT_STATE_CLEANUP_INTERVAL)
_public_auth_manager = AuthManager(
    api_key=API_KEY,
    api_key_header_names=API_KEY_HEADER_NAMES,
    trust_proxy_headers=TRUST_PROXY_HEADERS,
    trusted_proxy_networks=_trusted_proxy_networks,
    auth_fail_limit_per_minute=AUTH_FAIL_LIMIT_PER_MINUTE,
    auth_ban_seconds=AUTH_BAN_SECONDS,
    auth_ban_cleanup_interval=AUTH_BAN_STATE_CLEANUP_INTERVAL,
    rate_limiter=_rate_limiter,
)
_admin_auth_manager = AuthManager(
    api_key=ADMIN_API_KEY,
    api_key_header_names=API_KEY_HEADER_NAMES,
    trust_proxy_headers=TRUST_PROXY_HEADERS,
    trusted_proxy_networks=_trusted_proxy_networks,
    auth_fail_limit_per_minute=AUTH_FAIL_LIMIT_PER_MINUTE,
    auth_ban_seconds=AUTH_BAN_SECONDS,
    auth_ban_cleanup_interval=AUTH_BAN_STATE_CLEANUP_INTERVAL,
    rate_limiter=_rate_limiter,
)

_authenticated_api_rules = (
    RateLimitRule(
        bucket="api_burst",
        limit=API_BURST_LIMIT,
        window_seconds=API_BURST_WINDOW_SECONDS,
    ),
)
_serverlist_rules = (
    RateLimitRule(bucket="serverlist_1m", limit=SERVERLIST_LIMIT_PER_MINUTE, window_seconds=60),
    RateLimitRule(
        bucket="serverlist_burst",
        limit=SERVERLIST_BURST_LIMIT,
        window_seconds=SERVERLIST_BURST_WINDOW_SECONDS,
    ),
)
_whitelist_rules = (
    RateLimitRule(bucket="whitelist_1m", limit=WHITELIST_LIMIT_PER_MINUTE, window_seconds=60),
    RateLimitRule(
        bucket="whitelist_burst",
        limit=WHITELIST_BURST_LIMIT,
        window_seconds=WHITELIST_BURST_WINDOW_SECONDS,
    ),
)
_admin_query_rules = (
    RateLimitRule(bucket="admin_query_1m", limit=120, window_seconds=60),
)
_admin_write_rules = (
    RateLimitRule(bucket="admin_write_1m", limit=60, window_seconds=60),
)


async def _build_items(
    rows,
    *,
    include_shotid: bool,
    include_mode: bool = False,
    include_community: bool = False,
) -> list[dict]:
    return await asyncio.gather(
        *[
            build_server_item(
                row,
                semaphore=_serverlist_a2s_semaphore,
                a2s_timeout=A2S_TIMEOUT,
                total_timeout=SERVERLIST_A2S_TOTAL_TIMEOUT,
                max_retries=A2S_MAX_RETRIES,
                include_shotid=include_shotid,
                include_mode=include_mode,
                include_community=include_community,
            )
            for row in rows
        ]
    )


async def refresh_serverlist_cache_once() -> int:
    try:
        rows = await asyncio.to_thread(fetch_database_server_rows, engine)
        items = (
            await _build_items(rows, include_shotid=True, include_mode=True)
            if rows
            else []
        )
        await _serverlist_cache_store.replace(
            items, updated_at=now_str(), last_error=None
        )
        return len(rows)
    except Exception as exc:
        logger.exception("刷新数据库 serverlist 缓存失败")
        await _serverlist_cache_store.set_error(str(exc))
        return 0


async def refresh_whitelist_cache_once() -> int:
    try:
        rows = await asyncio.to_thread(fetch_whitelist_rows, engine)
        await _whitelist_cache_store.replace(
            rows, updated_at=now_str(), last_error=None
        )
        return len(rows)
    except Exception as exc:
        logger.exception("刷新 whitelist 缓存失败")
        await _whitelist_cache_store.set_error(str(exc))
        return 0


async def refresh_community_serverlist_cache_once() -> int:
    try:
        rows = await asyncio.to_thread(fetch_community_server_rows, engine)
        items = (
            await _build_items(rows, include_shotid=False, include_community=True)
            if rows
            else []
        )
        await _community_serverlist_cache_store.replace(
            items, updated_at=now_str(), last_error=None
        )
        return len(rows)
    except Exception as exc:
        logger.exception("刷新 community serverlist 缓存失败")
        await _community_serverlist_cache_store.set_error(str(exc))
        return 0


def get_refresh_jobs() -> tuple[RefreshJob, ...]:
    return (
        RefreshJob(
            name="serverlist_cache",
            interval_seconds=SERVERLIST_REFRESH_INTERVAL,
            refresh_once=refresh_serverlist_cache_once,
        ),
        RefreshJob(
            name="community_serverlist_cache",
            interval_seconds=COMMUNITY_SERVERLIST_REFRESH_INTERVAL,
            refresh_once=refresh_community_serverlist_cache_once,
        ),
        RefreshJob(
            name="whitelist_cache",
            interval_seconds=WHITELIST_REFRESH_INTERVAL,
            refresh_once=refresh_whitelist_cache_once,
        ),
    )


async def _run_periodic_refresh(job: RefreshJob):
    global _background_stop_event
    if _background_stop_event is None:
        _background_stop_event = asyncio.Event()

    while not _background_stop_event.is_set():
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        await job.refresh_once()
        elapsed = loop.time() - started_at
        wait_seconds = max(0.0, job.interval_seconds - elapsed)
        try:
            await asyncio.wait_for(_background_stop_event.wait(), timeout=wait_seconds)
        except asyncio.TimeoutError:
            pass


async def refresh_all_caches_once():
    jobs = get_refresh_jobs()
    results = await asyncio.gather(
        *(job.refresh_once() for job in jobs),
        return_exceptions=True,
    )

    for job, result in zip(jobs, results, strict=False):
        if isinstance(result, Exception):
            logger.warning("启动预热缓存失败: %s error=%s", job.name, result)
        else:
            logger.info("启动预热缓存完成: %s rows=%s", job.name, result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _background_stop_event, _background_tasks
    await asyncio.to_thread(ensure_catalog_tables, engine)
    await refresh_all_caches_once()
    _background_stop_event = asyncio.Event()
    _background_tasks = {
        job.name: asyncio.create_task(_run_periodic_refresh(job), name=job.name)
        for job in get_refresh_jobs()
    }
    try:
        yield
    except asyncio.CancelledError:
        logger.info("收到取消信号，开始关闭服务")
    finally:
        logger.info("FastAPI 关闭中...")
        if _background_stop_event is not None:
            _background_stop_event.set()
        for task in _background_tasks.values():
            await stop_background_task(task)
        _background_tasks = {}


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
)


@app.middleware("http")
async def apply_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")

    if str(getattr(getattr(request, "url", None), "path", "")).startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")

    return response


@app.get("/health")
def check():
    return {"status": "success"}


def verify_api_key(request: Request):
    _public_auth_manager.verify_api_key(request)


def verify_admin_api_key(request: Request):
    _admin_auth_manager.verify_api_key(request)


def _apply_rate_limits(request: Request, *rules: RateLimitRule):
    _public_auth_manager.enforce_rate_limits(request, *_authenticated_api_rules, *rules)


def _apply_admin_rate_limits(request: Request, *rules: RateLimitRule):
    _admin_auth_manager.enforce_rate_limits(request, *_authenticated_api_rules, *rules)


def require_serverlist_access(request: Request):
    verify_api_key(request)
    _apply_rate_limits(request, *_serverlist_rules)


def require_whitelist_access(request: Request):
    verify_api_key(request)
    _apply_rate_limits(request, *_whitelist_rules)


def require_admin_query_access(request: Request):
    verify_admin_api_key(request)
    _apply_admin_rate_limits(request, *_admin_query_rules)


def require_admin_write_access(request: Request):
    verify_admin_api_key(request)
    _apply_admin_rate_limits(request, *_admin_write_rules)


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise HTTPException(status_code=422, detail="布尔值格式不正确")


def _to_int(value, field_name: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} 必须是整数") from exc

    if minimum is not None and parsed < minimum:
        raise HTTPException(status_code=422, detail=f"{field_name} 不能小于 {minimum}")
    if maximum is not None and parsed > maximum:
        raise HTTPException(status_code=422, detail=f"{field_name} 不能大于 {maximum}")
    return parsed


def _to_clean_string(value, field_name: str, *, minimum: int = 1, maximum: int = 191) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        raise HTTPException(status_code=422, detail=f"{field_name} 不能为空")
    if len(text) > maximum:
        raise HTTPException(status_code=422, detail=f"{field_name} 不能超过 {maximum} 个字符")
    return text


def _normalize_kepcs_server_payload(payload: dict, *, partial: bool) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    normalized: dict = {}
    fields = {
        "shotid": ("ShotID", 1, 64),
        "mode": ("模式", 1, 32),
        "name": ("名称", 1, 191),
        "host": ("主机地址", 1, 191),
    }

    for key, (label, minimum, maximum) in fields.items():
        if key in payload:
            normalized[key] = _to_clean_string(payload[key], label, minimum=minimum, maximum=maximum)
        elif not partial:
            raise HTTPException(status_code=422, detail=f"{label} 不能为空")

    if "port" in payload:
        normalized["port"] = _to_int(payload["port"], "端口", minimum=1, maximum=65535)
    elif not partial:
        raise HTTPException(status_code=422, detail="端口不能为空")

    if "is_active" in payload or not partial:
        normalized["is_active"] = _to_bool(payload.get("is_active", True))

    return normalized


def _normalize_community_server_payload(payload: dict, *, partial: bool) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    normalized: dict = {}
    fields = {
        "community": ("社区标识", 1, 64),
        "name": ("名称", 1, 191),
        "host": ("主机地址", 1, 191),
    }

    for key, (label, minimum, maximum) in fields.items():
        if key in payload:
            normalized[key] = _to_clean_string(payload[key], label, minimum=minimum, maximum=maximum)
        elif not partial:
            raise HTTPException(status_code=422, detail=f"{label} 不能为空")

    if "port" in payload:
        normalized["port"] = _to_int(payload["port"], "端口", minimum=1, maximum=65535)
    elif not partial:
        raise HTTPException(status_code=422, detail="端口不能为空")

    if "sort_order" in payload:
        normalized["sort_order"] = _to_int(payload["sort_order"], "排序", minimum=0, maximum=9999)
    elif not partial:
        normalized["sort_order"] = 0

    if "is_active" in payload or not partial:
        normalized["is_active"] = _to_bool(payload.get("is_active", True))

    return normalized


@app.get("/api/kepcs/whitelist")
async def get_players(_: None = Depends(require_whitelist_access)):
    return await _whitelist_cache_store.get_items()


@app.get("/api/kepcs/serverlist")
async def get_server_list(_: None = Depends(require_serverlist_access)):
    return await _serverlist_cache_store.snapshot()


@app.get("/api/community/serverlist")
async def get_community_server_list(_: None = Depends(require_serverlist_access)):
    return await _community_serverlist_cache_store.snapshot()


@app.get("/api/admin/kepcs/servers")
async def get_admin_kepcs_servers(_: None = Depends(require_admin_query_access)):
    servers = await asyncio.to_thread(list_kepcs_servers, engine)
    return {"servers": servers}


@app.post("/api/admin/kepcs/servers")
async def create_admin_kepcs_server(
    payload: dict,
    _: None = Depends(require_admin_write_access),
):
    server = await asyncio.to_thread(
        create_kepcs_server,
        engine,
        _normalize_kepcs_server_payload(payload, partial=False),
    )
    await refresh_serverlist_cache_once()
    return {"server": server}


@app.patch("/api/admin/kepcs/servers/{server_id}")
async def update_admin_kepcs_server(
    server_id: int,
    payload: dict,
    _: None = Depends(require_admin_write_access),
):
    server = await asyncio.to_thread(
        update_kepcs_server,
        engine,
        server_id,
        _normalize_kepcs_server_payload(payload, partial=True),
    )
    if server is None:
        raise HTTPException(status_code=404, detail="服务器不存在")
    await refresh_serverlist_cache_once()
    return {"server": server}


@app.delete("/api/admin/kepcs/servers/{server_id}")
async def delete_admin_kepcs_server(
    server_id: int,
    _: None = Depends(require_admin_write_access),
):
    deleted = await asyncio.to_thread(delete_kepcs_server, engine, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="服务器不存在")
    await refresh_serverlist_cache_once()
    return {"success": True}


@app.get("/api/admin/community/servers")
async def get_admin_community_servers(_: None = Depends(require_admin_query_access)):
    servers = await asyncio.to_thread(list_community_servers, engine)
    return {"servers": servers}


@app.post("/api/admin/community/servers")
async def create_admin_community_server(
    payload: dict,
    _: None = Depends(require_admin_write_access),
):
    server = await asyncio.to_thread(
        create_community_server,
        engine,
        _normalize_community_server_payload(payload, partial=False),
    )
    await refresh_community_serverlist_cache_once()
    return {"server": server}


@app.patch("/api/admin/community/servers/{server_id}")
async def update_admin_community_server(
    server_id: int,
    payload: dict,
    _: None = Depends(require_admin_write_access),
):
    server = await asyncio.to_thread(
        update_community_server,
        engine,
        server_id,
        _normalize_community_server_payload(payload, partial=True),
    )
    if server is None:
        raise HTTPException(status_code=404, detail="社区服不存在")
    await refresh_community_serverlist_cache_once()
    return {"server": server}


@app.delete("/api/admin/community/servers/{server_id}")
async def delete_admin_community_server(
    server_id: int,
    _: None = Depends(require_admin_write_access),
):
    deleted = await asyncio.to_thread(delete_community_server, engine, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="社区服不存在")
    await refresh_community_serverlist_cache_once()
    return {"success": True}
