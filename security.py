import ipaddress
import logging
import math
import secrets
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Iterable

from fastapi import HTTPException, Request


logger = logging.getLogger("kepapi.security")


@dataclass(frozen=True)
class RateLimitRule:
    bucket: str
    limit: int
    window_seconds: float


@dataclass(frozen=True)
class RequestIdentity:
    ip: str
    ip_source: str
    path: str


def normalize_ip(value: str) -> str | None:
    value = (value or "").strip().strip('"')
    if not value:
        return None

    if value.startswith("[") and "]" in value:
        value = value[1 : value.index("]")]
    elif value.count(":") == 1 and value.rsplit(":", 1)[1].isdigit():
        value = value.rsplit(":", 1)[0]

    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        return None


def parse_trusted_proxy_networks(cidr_values: Iterable[str]) -> tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network, ...
]:
    networks = []
    for raw in cidr_values:
        normalized = (raw or "").strip()
        if not normalized:
            continue
        networks.append(ipaddress.ip_network(normalized, strict=False))
    return tuple(networks)


def is_trusted_proxy_ip(
    remote_ip: str | None,
    trusted_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    if not remote_ip or not trusted_networks:
        return False

    try:
        ip = ipaddress.ip_address(remote_ip)
    except ValueError:
        return False
    return any(ip in network for network in trusted_networks)


def get_client_ip_with_source(
    request: Request,
    *,
    trust_proxy_headers: bool,
    trusted_proxy_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> tuple[str, str]:
    remote_ip = normalize_ip(request.client.host) if request.client else None
    should_trust_headers = trust_proxy_headers and is_trusted_proxy_ip(
        remote_ip, trusted_proxy_networks
    )

    if should_trust_headers:
        for header_name in (
            "cf-connecting-ip",
            "true-client-ip",
            "x-forwarded-for",
            "x-original-forwarded-for",
        ):
            value = request.headers.get(header_name)
            if value:
                if header_name in ("x-forwarded-for", "x-original-forwarded-for"):
                    for token in value.split(","):
                        ip = normalize_ip(token)
                        if ip:
                            return ip, header_name
                else:
                    ip = normalize_ip(value)
                    if ip:
                        return ip, header_name

        for header_name in ("x-real-ip", "x-client-ip", "x-remote-addr", "remoteaddr"):
            value = request.headers.get(header_name)
            if value:
                ip = normalize_ip(value)
                if ip:
                    return ip, header_name

        forwarded = request.headers.get("forwarded")
        if forwarded:
            for item in forwarded.split(","):
                for part in item.split(";"):
                    part = part.strip()
                    if part.lower().startswith("for="):
                        ip = normalize_ip(part[4:])
                        if ip:
                            return ip, "forwarded"

    if request.client and request.client.host:
        if remote_ip:
            return remote_ip, "asgi_client"
        return request.client.host, "asgi_client"
    return "unknown", "unknown"


def get_client_ip(
    request: Request,
    *,
    trust_proxy_headers: bool,
    trusted_proxy_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> str:
    ip, _ = get_client_ip_with_source(
        request,
        trust_proxy_headers=trust_proxy_headers,
        trusted_proxy_networks=trusted_proxy_networks,
    )
    return ip


class SlidingWindowLimiter:
    """基于滑动时间窗口的内存限流器。"""

    def __init__(self, cleanup_interval: float):
        self._events = defaultdict(deque)
        self._bucket_windows = {}
        self._next_cleanup_at = 0.0
        self._cleanup_interval = cleanup_interval
        self._lock = Lock()

    def allow(self, bucket: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        now = monotonic()
        with self._lock:
            self._bucket_windows[bucket] = window_seconds
            event_times = self._events[bucket]
            cutoff = now - window_seconds
            while event_times and event_times[0] <= cutoff:
                event_times.popleft()

            if len(event_times) >= limit:
                retry_after = max(1, math.ceil(window_seconds - (now - event_times[0])))
                if now >= self._next_cleanup_at:
                    self._cleanup_locked(now)
                return False, retry_after

            event_times.append(now)
            if now >= self._next_cleanup_at:
                self._cleanup_locked(now)
            return True, 0

    def _cleanup_locked(self, now: float):
        for bucket, event_times in list(self._events.items()):
            window_seconds = self._bucket_windows.get(bucket, 60.0)
            cutoff = now - window_seconds
            while event_times and event_times[0] <= cutoff:
                event_times.popleft()
            if not event_times:
                self._events.pop(bucket, None)
                self._bucket_windows.pop(bucket, None)
        self._next_cleanup_at = now + self._cleanup_interval


class AuthManager:
    def __init__(
        self,
        *,
        api_key: str,
        api_key_header_names: list[str],
        trust_proxy_headers: bool,
        trusted_proxy_networks: tuple[
            ipaddress.IPv4Network | ipaddress.IPv6Network, ...
        ],
        auth_fail_limit_per_minute: int,
        auth_ban_seconds: int,
        auth_ban_cleanup_interval: float,
        rate_limiter: SlidingWindowLimiter,
    ):
        self._api_key = api_key
        self._api_key_header_names = [header.lower() for header in api_key_header_names]
        self._trust_proxy_headers = trust_proxy_headers
        self._trusted_proxy_networks = trusted_proxy_networks
        self._auth_fail_limit_per_minute = auth_fail_limit_per_minute
        self._auth_ban_seconds = auth_ban_seconds
        self._auth_ban_cleanup_interval = auth_ban_cleanup_interval
        self._rate_limiter = rate_limiter

        self._auth_ban_until: dict[str, float] = {}
        self._auth_state_lock = Lock()
        self._next_auth_ban_cleanup_at = 0.0

    @property
    def trust_proxy_headers(self) -> bool:
        return self._trust_proxy_headers

    @property
    def trusted_proxy_networks(
        self,
    ) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
        return self._trusted_proxy_networks

    def get_client_ip(self, request: Request) -> str:
        return get_client_ip(
            request,
            trust_proxy_headers=self._trust_proxy_headers,
            trusted_proxy_networks=self._trusted_proxy_networks,
        )

    def get_client_ip_with_source(self, request: Request) -> tuple[str, str]:
        return get_client_ip_with_source(
            request,
            trust_proxy_headers=self._trust_proxy_headers,
            trusted_proxy_networks=self._trusted_proxy_networks,
        )

    def get_request_identity(self, request: Request) -> RequestIdentity:
        ip, ip_source = self.get_client_ip_with_source(request)
        path = getattr(getattr(request, "url", None), "path", "unknown")
        return RequestIdentity(ip=ip, ip_source=ip_source, path=path)

    def _enforce_rate_limit_for_ip(
        self,
        *,
        ip: str,
        path: str,
        bucket: str,
        limit: int,
        window_seconds: float,
    ):
        allowed, retry_after = self._rate_limiter.allow(
            bucket=f"{bucket}:{ip}", limit=limit, window_seconds=window_seconds
        )
        if not allowed:
            logger.warning(
                "[Denied][RateLimit] ip=%s path=%s bucket=%s retry_after=%ss",
                ip,
                path,
                bucket,
                retry_after,
            )
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests",
                headers={"Retry-After": str(retry_after)},
            )

    def enforce_rate_limit(
        self,
        request: Request,
        *,
        bucket: str,
        limit: int,
        window_seconds: float,
    ):
        identity = self.get_request_identity(request)
        self._enforce_rate_limit_for_ip(
            ip=identity.ip,
            path=identity.path,
            bucket=bucket,
            limit=limit,
            window_seconds=window_seconds,
        )

    def enforce_rate_limits(self, request: Request, *rules: RateLimitRule):
        identity = self.get_request_identity(request)
        for rule in rules:
            self._enforce_rate_limit_for_ip(
                ip=identity.ip,
                path=identity.path,
                bucket=rule.bucket,
                limit=rule.limit,
                window_seconds=rule.window_seconds,
            )

    def _cleanup_auth_bans(self, now: float):
        if now < self._next_auth_ban_cleanup_at:
            return
        with self._auth_state_lock:
            if now < self._next_auth_ban_cleanup_at:
                return
            for ip, ban_until in list(self._auth_ban_until.items()):
                if ban_until <= now:
                    self._auth_ban_until.pop(ip, None)
            self._next_auth_ban_cleanup_at = now + self._auth_ban_cleanup_interval

    def _extract_api_key(self, request: Request) -> tuple[str | None, str]:
        for header_name in self._api_key_header_names:
            value = request.headers.get(header_name)
            if value:
                return value.strip(), f"header:{header_name}"

        authorization = request.headers.get("authorization", "").strip()
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip(), "header:authorization"

        return None, "missing"

    def verify_api_key(self, request: Request):
        identity = self.get_request_identity(request)
        now = monotonic()
        self._cleanup_auth_bans(now)

        with self._auth_state_lock:
            ban_until = self._auth_ban_until.get(identity.ip, 0.0)
        if now < ban_until:
            retry_after = max(1, math.ceil(ban_until - now))
            logger.warning(
                "[Denied][Auth][Banned] ip=%s src=%s path=%s retry_after=%ss",
                identity.ip,
                identity.ip_source,
                identity.path,
                retry_after,
            )
            raise HTTPException(
                status_code=429,
                detail="Request denied",
                headers={"Retry-After": str(retry_after)},
            )

        provided_key, key_source = self._extract_api_key(request)
        if not provided_key or not secrets.compare_digest(provided_key, self._api_key):
            allowed, _ = self._rate_limiter.allow(
                bucket=f"auth_fail:{identity.ip}",
                limit=self._auth_fail_limit_per_minute,
                window_seconds=60,
            )
            if not allowed:
                with self._auth_state_lock:
                    self._auth_ban_until[identity.ip] = now + self._auth_ban_seconds
                logger.warning(
                    "[Denied][Auth][TooManyFailures] ip=%s src=%s path=%s key_src=%s ban=%ss",
                    identity.ip,
                    identity.ip_source,
                    identity.path,
                    key_source,
                    self._auth_ban_seconds,
                )
                raise HTTPException(
                    status_code=429,
                    detail="Request denied",
                    headers={"Retry-After": str(self._auth_ban_seconds)},
                )

            logger.warning(
                "[Denied][Auth][Unauthorized] ip=%s src=%s path=%s key_src=%s",
                identity.ip,
                identity.ip_source,
                identity.path,
                key_source,
            )
            raise HTTPException(status_code=401, detail="Unauthorized")

        logger.debug(
            "[Success][Auth] ip=%s src=%s path=%s key_src=%s",
            identity.ip,
            identity.ip_source,
            identity.path,
            key_source,
        )
