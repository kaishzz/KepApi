from typing import Any

from sqlalchemy import text


def _fetch_rows(engine, query: str, params: dict[str, Any] | None = None):
    with engine.connect() as conn:
        return conn.execute(text(query), params or {}).mappings().all()


def list_kepcs_servers(engine) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        engine,
        """
        SELECT id, mode, name, host, port, is_active
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
                (mode, name, host, port, is_active)
                VALUES
                (:mode, :name, :host, :port, :is_active)
                """
            ),
            {
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
        SELECT id, mode, name, host, port, is_active
        FROM cs2_serverlist.servers
        WHERE id = :id
        LIMIT 1
        """,
        {"id": server_id},
    )
    return dict(rows[0]) if rows else None
