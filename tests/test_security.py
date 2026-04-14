import sys
import unittest
from types import ModuleType, SimpleNamespace

if "fastapi" not in sys.modules:
    fake_fastapi = ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail=None, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            self.headers = headers or {}

    class Request:  # pragma: no cover - only for import compatibility
        pass

    fake_fastapi.HTTPException = HTTPException
    fake_fastapi.Request = Request
    sys.modules["fastapi"] = fake_fastapi

from fastapi import HTTPException

from security import (
    AuthManager,
    RateLimitRule,
    SlidingWindowLimiter,
    get_client_ip_with_source,
    parse_trusted_proxy_networks,
)


class DummyRequest:
    def __init__(self, *, headers=None, client_host="127.0.0.1", path="/api/test"):
        self.headers = headers or {}
        self.client = SimpleNamespace(host=client_host)
        self.url = SimpleNamespace(path=path)


class SecurityTests(unittest.TestCase):
    def _make_auth_manager(
        self,
        *,
        trust_proxy_headers=False,
        trusted_proxy_cidrs=None,
    ):
        return AuthManager(
            api_key="secret",
            api_key_header_names=["x-api-key"],
            trust_proxy_headers=trust_proxy_headers,
            trusted_proxy_networks=parse_trusted_proxy_networks(
                trusted_proxy_cidrs or []
            ),
            auth_fail_limit_per_minute=10,
            auth_ban_seconds=60,
            auth_ban_cleanup_interval=60,
            rate_limiter=SlidingWindowLimiter(60),
        )

    def test_untrusted_proxy_ignores_forwarded_headers(self):
        request = DummyRequest(
            headers={"x-forwarded-for": "8.8.8.8"},
            client_host="203.0.113.10",
        )

        ip, source = get_client_ip_with_source(
            request,
            trust_proxy_headers=True,
            trusted_proxy_networks=parse_trusted_proxy_networks(["127.0.0.1/32"]),
        )

        self.assertEqual(ip, "203.0.113.10")
        self.assertEqual(source, "asgi_client")

    def test_trusted_proxy_uses_forwarded_headers(self):
        request = DummyRequest(
            headers={"x-forwarded-for": "8.8.8.8, 1.1.1.1"},
            client_host="127.0.0.1",
        )

        ip, source = get_client_ip_with_source(
            request,
            trust_proxy_headers=True,
            trusted_proxy_networks=parse_trusted_proxy_networks(["127.0.0.1/32"]),
        )

        self.assertEqual(ip, "8.8.8.8")
        self.assertEqual(source, "x-forwarded-for")

    def test_verify_api_key_accepts_header(self):
        auth = self._make_auth_manager()
        request = DummyRequest(headers={"x-api-key": "secret"})

        auth.verify_api_key(request)

    def test_verify_api_key_accepts_bearer_token(self):
        auth = self._make_auth_manager()
        request = DummyRequest(headers={"authorization": "Bearer secret"})

        auth.verify_api_key(request)

    def test_verify_api_key_rejects_missing_header(self):
        request = DummyRequest()
        auth = self._make_auth_manager()

        with self.assertRaises(HTTPException) as ctx:
            auth.verify_api_key(request)

        self.assertEqual(ctx.exception.status_code, 401)

    def test_enforce_rate_limits_reuses_request_identity(self):
        auth = self._make_auth_manager()
        request = DummyRequest()

        auth.enforce_rate_limits(
            request,
            RateLimitRule(bucket="a", limit=2, window_seconds=60),
            RateLimitRule(bucket="b", limit=2, window_seconds=60),
        )


if __name__ == "__main__":
    unittest.main()
