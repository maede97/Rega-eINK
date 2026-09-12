from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = Path(__file__).resolve().with_name("flights.db")
API_KEYS_PATH = Path(__file__).resolve().with_name("api_keys.txt")

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"


app = FastAPI(title="REGA Flights API", version="1.0.0")

# Allow browser-based clients to access the API (adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flights (
            timestamp numeric,
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
            observed_at numeric,
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

@app.get("/flights/range")
def get_flights_range(start: str, end: str, authorization: str | None = Header(default=None)) -> JSONResponse:
    require_valid_api_key(authorization)

    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT observed_at, callsign, latitude, longitude
            FROM flights_history
            WHERE observed_at > ? AND observed_at < ?
            ORDER BY observed_at DESC
            """,
            (start, end),
        ).fetchall()

    payload = [
        {
            "observed_at": observed_at,
            "callsign": callsign,
            "latitude": latitude,
            "longitude": longitude,
        }
        for observed_at, callsign, latitude, longitude in rows
    ]
    return JSONResponse(content={"flights": payload, "count": len(payload)})


@app.get("/")
def root() -> FileResponse:
    index = WEB_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index, media_type="text/html")

@app.get("/favicon.ico")
def favicon() -> FileResponse:
    favicon_path = WEB_DIR / "favicon.ico"
    if not favicon_path.exists():
        raise HTTPException(status_code=404, detail="favicon.ico not found")
    return FileResponse(favicon_path, media_type="image/x-icon")

@app.get("/apple-touch-icon.png")
def apple_touch_icon() -> FileResponse:
    apple_touch_icon_path = WEB_DIR / "apple-touch-icon.png"
    if not apple_touch_icon_path.exists():
        raise HTTPException(status_code=404, detail="apple-touch-icon.png not found")
    return FileResponse(apple_touch_icon_path, media_type="image/png")