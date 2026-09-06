from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

DB_PATH = Path(__file__).resolve().with_name("flights.db")
API_KEYS_PATH = Path(__file__).resolve().with_name("api_keys.txt")
app = FastAPI(title="REGA Flights API", version="1.0.0")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flights (
            timestamp TEXT,
            callsign TEXT,
            latitude REAL,
            longitude REAL,
            active BOOLEAN
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flights_history (
            observed_at TEXT,
            callsign TEXT,
            latitude REAL,
            longitude REAL,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def load_api_keys() -> set[str]:
    if not API_KEYS_PATH.exists():
        return set()

    keys: set[str] = set()
    for line in API_KEYS_PATH.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            keys.add(value)
    return keys


def require_valid_api_key(authorization: str | None) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )

    valid_keys = load_api_keys()
    if token.strip() not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@app.get("/flights")
def get_flights(limit: int = 1000, authorization: str | None = Header(default=None)) -> JSONResponse:
    require_valid_api_key(authorization)

    if limit < 1:
        limit = 1

    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT timestamp, callsign, latitude, longitude, active
            FROM flights
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    payload = [
        {
            "timestamp": timestamp,
            "callsign": callsign,
            "latitude": latitude,
            "longitude": longitude,
            "active": active,
        }
        for timestamp, callsign, latitude, longitude, active in rows
    ]
    return JSONResponse(content={"flights": payload, "count": len(payload)})


@app.get("/flights/history")
def get_flights_history(limit: int = 1000, authorization: str | None = Header(default=None)) -> JSONResponse:
    require_valid_api_key(authorization)

    if limit < 1:
        limit = 1

    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT observed_at, callsign, latitude, longitude, recorded_at
            FROM flights_history
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    payload = [
        {
            "observed_at": observed_at,
            "callsign": callsign,
            "latitude": latitude,
            "longitude": longitude,
            "recorded_at": recorded_at,
        }
        for observed_at, callsign, latitude, longitude, recorded_at in rows
    ]
    return JSONResponse(content={"history": payload, "count": len(payload)})
