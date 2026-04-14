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
)


class ServerlistServiceTests(unittest.TestCase):
    def test_build_server_item_keeps_shotid_immediately_after_id(self):
        row = {
            "id": 1,
            "shotid": "db-1",
            "mode": "ze",
            "community": "fys",
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
                    include_community=True,
                    include_mode=True,
                )

        item = asyncio.run(run_test())
        self.assertEqual(
            list(item.keys())[:5],
            ["id", "shotid", "mode", "community", "name"],
        )
        self.assertEqual(item["status"], "ok")

    def test_build_server_item_marks_timeout_after_retries(self):
        row = {
            "id": 1,
            "shotid": "db-1",
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
