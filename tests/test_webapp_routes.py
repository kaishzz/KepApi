import os
import sys
import unittest
from types import ModuleType, SimpleNamespace


for env_name, env_value in {
    "KEPAPI_API_KEY": "secret",
    "KEPAPI_ADMIN_API_KEY": "admin-secret",
    "KEPAPI_DB_HOST": "127.0.0.1",
    "KEPAPI_DB_USER": "tester",
    "KEPAPI_DB_PASS": "tester",
}.items():
    os.environ.setdefault(env_name, env_value)


if "fastapi" in sys.modules and (
    not hasattr(sys.modules["fastapi"], "Depends")
    or not hasattr(getattr(sys.modules["fastapi"], "FastAPI", object), "middleware")
):
    del sys.modules["fastapi"]


if "fastapi" not in sys.modules:
    fake_fastapi = ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail=None, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            self.headers = headers or {}

    class Request:  # pragma: no cover - compatibility shim for imports
        pass

    class _Route:
        def __init__(self, path: str):
            self.path = path

    class FastAPI:
        def __init__(self, *, lifespan=None, **kwargs):
            self.lifespan = lifespan
            self.routes = []
            self.settings = kwargs

        def _register(self, path: str):
            def decorator(func):
                self.routes.append(_Route(path))
                return func

            return decorator

        def get(self, path: str):
            return self._register(path)

        def post(self, path: str):
            return self._register(path)

        def patch(self, path: str):
            return self._register(path)

        def delete(self, path: str):
            return self._register(path)

        def middleware(self, _type: str):
            def decorator(func):
                return func

            return decorator

    def Depends(dependency):
        return dependency

    fake_fastapi.Depends = Depends
    fake_fastapi.FastAPI = FastAPI
    fake_fastapi.HTTPException = HTTPException
    fake_fastapi.Request = Request
    sys.modules["fastapi"] = fake_fastapi


if "sqlalchemy" not in sys.modules:
    fake_sqlalchemy = ModuleType("sqlalchemy")
    fake_sqlalchemy.text = lambda value: value
    sys.modules["sqlalchemy"] = fake_sqlalchemy


if "a2s" not in sys.modules:
    fake_a2s = ModuleType("a2s")
    fake_a2s.info = None
    sys.modules["a2s"] = fake_a2s


if "db" not in sys.modules:
    fake_db = ModuleType("db")
    fake_db.engine = SimpleNamespace()
    sys.modules["db"] = fake_db


from webapp import (
    app,
    get_refresh_jobs,
    require_admin_query_access,
    require_serverlist_access,
)


class WebappRouteTests(unittest.TestCase):
    def test_only_current_api_routes_are_registered(self):
        route_paths = {
            route.path
            for route in app.routes
            if getattr(route, "path", None)
        }

        self.assertIn("/api/kepcs/serverlist", route_paths)
        self.assertIn("/api/kepcs/whitelist", route_paths)
        self.assertIn("/api/admin/kepcs/servers", route_paths)
        self.assertIn("/api/admin/kepcs/servers/{server_id}", route_paths)
        self.assertNotIn("/api/serverlist", route_paths)
        self.assertNotIn("/api/whitelist", route_paths)

    def test_refresh_jobs_cover_all_background_caches(self):
        self.assertEqual(
            {job.name for job in get_refresh_jobs()},
            {
                "serverlist_cache",
                "whitelist_cache",
            },
        )

    def test_public_key_can_access_serverlist_but_not_admin_routes(self):
        public_request = SimpleNamespace(
            headers={"x-api-key": "secret"},
            client=SimpleNamespace(host="127.0.0.1"),
            url=SimpleNamespace(path="/api/kepcs/serverlist"),
        )

        admin_request = SimpleNamespace(
            headers={"x-api-key": "secret"},
            client=SimpleNamespace(host="127.0.0.1"),
            url=SimpleNamespace(path="/api/admin/kepcs/servers"),
        )

        require_serverlist_access(public_request)

        with self.assertRaises(Exception) as ctx:
            require_admin_query_access(admin_request)

        self.assertEqual(getattr(ctx.exception, "status_code", None), 401)

    def test_admin_key_can_access_admin_routes(self):
        request = SimpleNamespace(
            headers={"x-api-key": "admin-secret"},
            client=SimpleNamespace(host="127.0.0.1"),
            url=SimpleNamespace(path="/api/admin/kepcs/servers"),
        )

        require_admin_query_access(request)


if __name__ == "__main__":
    unittest.main()
