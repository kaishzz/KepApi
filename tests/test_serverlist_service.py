import asyncio
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

if "a2s" not in sys.modules:
    fake_a2s = ModuleType("a2s")
    fake_a2s.info = None
    sys.modules["a2s"] = fake_a2s

if "sqlalchemy" not in sys.modules:
    fake_sqlalchemy = ModuleType("sqlalchemy")
    fake_sqlalchemy.text = lambda value: value
    sys.modules["sqlalchemy"] = fake_sqlalchemy

from serverlist_service import (
    build_server_item,
    fetch_database_server_rows,
)


class ServerlistServiceTests(unittest.TestCase):
    def test_fetch_database_server_rows_includes_mode_display_name(self):
        class FakeResult:
            def mappings(self):
                return self

            def all(self):
                return []

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query):
                self.query = query
                return FakeResult()

        class FakeEngine:
            def __init__(self):
                self.connection = FakeConnection()

            def connect(self):
                return self.connection

        engine = FakeEngine()

        fetch_database_server_rows(engine)

        query = str(engine.connection.query)
        self.assertIn("server_modes", query)
        self.assertIn("mode_name", query)
        self.assertIn("sort_order", query)

    def test_build_server_item_keeps_mode_metadata_near_front(self):
        row = {
            "id": 1,
            "mode": "mode_a",
            "mode_name": "模式A",
            "name": "Server A",
            "host": "127.0.0.1",
            "port": 27015,
        }
        fake_info = SimpleNamespace(
            server_name="Visible Name",
            map_name="ze_test",
            player_count=5,
            max_players=64,
        )

        async def run_test():
            semaphore = asyncio.Semaphore(1)
            with patch("serverlist_service.a2s.info", return_value=fake_info):
                return await build_server_item(
                    row,
                    semaphore=semaphore,
                    a2s_timeout=0.1,
                    total_timeout=0.2,
                    max_retries=1,
                    include_mode=True,
                )

        item = asyncio.run(run_test())
        self.assertEqual(
            list(item.keys())[:4],
            ["id", "mode", "mode_name", "name"],
        )
        self.assertEqual(item["mode_name"], "模式A")
        self.assertEqual(item["status"], "ok")

    def test_build_server_item_marks_timeout_after_retries(self):
        row = {
            "id": 1,
            "name": "Server A",
            "host": "127.0.0.1",
            "port": 27015,
        }

        async def run_test():
            semaphore = asyncio.Semaphore(1)
            with patch("serverlist_service.a2s.info", side_effect=TimeoutError()):
                return await build_server_item(
                    row,
                    semaphore=semaphore,
                    a2s_timeout=0.1,
                    total_timeout=0.2,
                    max_retries=2,
                )

        item = asyncio.run(run_test())
        self.assertEqual(item["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
