from typing import Any

from sqlalchemy import text


def _fetch_rows(engine, query: str, params: dict[str, Any] | None = None):
    with engine.connect() as conn:
        return conn.execute(text(query), params or {}).mappings().all()


def ensure_catalog_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cs2_serverlist.community_servers (
                  id INT NOT NULL AUTO_INCREMENT,
                  community VARCHAR(64) NOT NULL,
                  name VARCHAR(191) NOT NULL,
                  host VARCHAR(191) NOT NULL,
                  port INT NOT NULL,
                  is_active TINYINT(1) NOT NULL DEFAULT 1,
                  sort_order INT NOT NULL DEFAULT 0,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (id),
                  UNIQUE KEY uniq_host_port (host, port),
                  KEY idx_active_sort (is_active, sort_order, id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )


def list_kepcs_servers(engine) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        engine,
        """
        SELECT id, shotid, mode, name, host, port, is_active
        FROM cs2_serverlist.servers
        ORDER BY id ASC
        """,
    )
    return [dict(row) for row in rows]


def create_kepcs_server(engine, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO cs2_serverlist.servers
                (shotid, mode, name, host, port, is_active)
                VALUES
                (:shotid, :mode, :name, :host, :port, :is_active)
                """
            ),
            {
                "shotid": payload["shotid"],
                "mode": payload["mode"],
                "name": payload["name"],
                "host": payload["host"],
                "port": payload["port"],
                "is_active": 1 if payload["is_active"] else 0,
            },
        )
        server_id = int(result.lastrowid)

    return get_kepcs_server(engine, server_id)


def update_kepcs_server(engine, server_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    assignments: list[str] = []
    params: dict[str, Any] = {"id": server_id}

    for source_key, column_name in (
        ("shotid", "shotid"),
        ("mode", "mode"),
        ("name", "name"),
        ("host", "host"),
        ("port", "port"),
        ("is_active", "is_active"),
    ):
        if source_key not in payload:
            continue
        assignments.append(f"{column_name} = :{source_key}")
        value = payload[source_key]
        params[source_key] = 1 if source_key == "is_active" and value else 0 if source_key == "is_active" else value

    if not assignments:
        return get_kepcs_server(engine, server_id)

    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                UPDATE cs2_serverlist.servers
                SET {", ".join(assignments)}
                WHERE id = :id
                """
            ),
            params,
        )
        if result.rowcount == 0:
            return None

    return get_kepcs_server(engine, server_id)


def delete_kepcs_server(engine, server_id: int) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM cs2_serverlist.servers WHERE id = :id"),
            {"id": server_id},
        )
        return result.rowcount > 0


def get_kepcs_server(engine, server_id: int) -> dict[str, Any] | None:
    rows = _fetch_rows(
        engine,
        """
        SELECT id, shotid, mode, name, host, port, is_active
        FROM cs2_serverlist.servers
        WHERE id = :id
        LIMIT 1
        """,
        {"id": server_id},
    )
    return dict(rows[0]) if rows else None


def fetch_community_server_rows(engine):
    rows = _fetch_rows(
        engine,
        """
        SELECT id, community, name, host, port
        FROM cs2_serverlist.community_servers
        WHERE is_active = 1
        ORDER BY sort_order ASC, id ASC
        """,
    )
    return [dict(row) for row in rows]


def list_community_servers(engine) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        engine,
        """
        SELECT id, community, name, host, port, is_active, sort_order
        FROM cs2_serverlist.community_servers
        ORDER BY sort_order ASC, id ASC
        """,
    )
    return [dict(row) for row in rows]


def create_community_server(engine, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO cs2_serverlist.community_servers
                (community, name, host, port, is_active, sort_order)
                VALUES
                (:community, :name, :host, :port, :is_active, :sort_order)
                """
            ),
            {
                "community": payload["community"],
                "name": payload["name"],
                "host": payload["host"],
                "port": payload["port"],
                "is_active": 1 if payload["is_active"] else 0,
                "sort_order": payload["sort_order"],
            },
        )
        server_id = int(result.lastrowid)

    return get_community_server(engine, server_id)


def update_community_server(engine, server_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    assignments: list[str] = []
    params: dict[str, Any] = {"id": server_id}

    for source_key, column_name in (
        ("community", "community"),
        ("name", "name"),
        ("host", "host"),
        ("port", "port"),
        ("is_active", "is_active"),
        ("sort_order", "sort_order"),
    ):
        if source_key not in payload:
            continue
        assignments.append(f"{column_name} = :{source_key}")
        value = payload[source_key]
        params[source_key] = 1 if source_key == "is_active" and value else 0 if source_key == "is_active" else value

    if not assignments:
        return get_community_server(engine, server_id)

    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                UPDATE cs2_serverlist.community_servers
                SET {", ".join(assignments)}
                WHERE id = :id
                """
            ),
            params,
        )
        if result.rowcount == 0:
            return None

    return get_community_server(engine, server_id)


def delete_community_server(engine, server_id: int) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM cs2_serverlist.community_servers WHERE id = :id"),
            {"id": server_id},
        )
        return result.rowcount > 0


def get_community_server(engine, server_id: int) -> dict[str, Any] | None:
    rows = _fetch_rows(
        engine,
        """
        SELECT id, community, name, host, port, is_active, sort_order
        FROM cs2_serverlist.community_servers
        WHERE id = :id
        LIMIT 1
        """,
        {"id": server_id},
    )
    return dict(rows[0]) if rows else None
