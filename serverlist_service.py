import asyncio
import logging
import socket
from datetime import datetime

import a2s
from sqlalchemy import text


logger = logging.getLogger("kepapi.serverlist")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_query_rows(engine, query: str):
    with engine.connect() as conn:
        rows = (
            conn.execute(text(query))
            .mappings()
            .all()
        )
    return rows


def fetch_database_server_rows(engine):
    return fetch_query_rows(
        engine,
        """
        SELECT
            s.id,
            s.mode,
            COALESCE(m.display_name, s.mode) AS mode_name,
            s.name,
            s.host,
            s.port
        FROM cs2_serverlist.servers AS s
        LEFT JOIN cs2_serverlist.server_modes AS m
            ON m.mode = s.mode
            AND m.is_active = 1
        WHERE s.is_active = 1
        ORDER BY COALESCE(m.sort_order, 0) ASC, s.id ASC
        """,
    )


def fetch_whitelist_rows(engine):
    return fetch_query_rows(
        engine,
        """
        SELECT UserID, SteamID
        FROM cs2_playtime.kep_player_info
        ORDER BY UserID ASC
        """,
    )


async def build_server_item(
    row,
    *,
    semaphore: asyncio.Semaphore,
    a2s_timeout: float,
    total_timeout: float,
    max_retries: int,
    include_mode: bool = False,
):
    row = dict(row)
    server_id = row.get("id")
    mode = row.get("mode")
    mode_name = row.get("mode_name")
    name = row.get("name")
    host = str(row.get("host") or row.get("ip") or "").strip()
    port = int(row["port"])

    item = {"id": server_id}
    if include_mode:
        item["mode"] = mode
        item["mode_name"] = mode_name or mode
    item.update(
        {
            "name": name or f"{host}:{port}",
            "server_name": None,
            "host": host,
            "port": port,
            "map": None,
            "current_players": None,
            "max_players": None,
            "status": "ok",
        }
    )

    for attempt in range(1, max_retries + 1):
        try:
            async with semaphore:
                info = await asyncio.wait_for(
                    asyncio.to_thread(a2s.info, (host, port), timeout=a2s_timeout),
                    timeout=total_timeout,
                )
            item["server_name"] = getattr(info, "server_name", None)
            item["map"] = info.map_name
            item["current_players"] = info.player_count
            item["max_players"] = info.max_players
            item["status"] = "ok"
            return item
        except (TimeoutError, socket.timeout, asyncio.TimeoutError):
            if attempt == max_retries:
                item["status"] = "timeout"
                logger.warning(
                    "A2S timeout host=%s port=%s retries=%s",
                    host,
                    port,
                    max_retries,
                )
        except Exception:
            item["status"] = "error"
            logger.exception("A2S error host=%s port=%s", host, port)
            return item

    return item
