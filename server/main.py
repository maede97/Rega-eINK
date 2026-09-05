from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

DB_PATH = Path(__file__).resolve().with_name("flights.db")
app = FastAPI(title="REGA Flights API", version="1.0.0")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flights (
            timestamp TEXT,
            callsign TEXT,
            latitude REAL,
            longitude REAL
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


@app.get("/flights")
def get_flights(limit: int = 100) -> JSONResponse:
    if limit < 1:
        limit = 1

    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT timestamp, callsign, latitude, longitude
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
        }
        for timestamp, callsign, latitude, longitude in rows
    ]
    return JSONResponse(content={"flights": payload, "count": len(payload)})


@app.get("/flights/history")
def get_flights_history(limit: int = 1000) -> JSONResponse:
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
