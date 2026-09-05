from __future__ import annotations

import sqlite3
from pathlib import Path

from FlightRadarAPI import FlightRadar24API

DB_PATH = Path(__file__).resolve().with_name("flights.db")
AIRLINE_ICAO = "RGA"


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


def fetch_current_flights() -> list[dict[str, object]]:
    api = FlightRadar24API()
    bounds = api.get_bounds({
        "tl_y": 47.808455,
        "tl_x": 5.956080,
        "br_y": 45.817995,
        "br_x": 10.492030,
    })
    flights = api.get_flights(airline=AIRLINE_ICAO, bounds=bounds)

    records: list[dict[str, object]] = []
    for flight in flights:
        records.append(
            {
                "timestamp": getattr(flight, "time", None),
                "callsign": getattr(flight, "callsign", None),
                "latitude": getattr(flight, "latitude", None),
                "longitude": getattr(flight, "longitude", None),
            }
        )
    return records


def persist_flights(records: list[dict[str, object]]) -> int:
    filtered_records = [record for record in records if record.get("callsign")]

    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)

        # delete only the rows where no longer a callsign is present. keep the ones with valid callsigns
        current_callsigns = [record.get("callsign") for record in filtered_records]
        conn.execute(
            "DELETE FROM flights WHERE callsign NOT IN ({})".format(
                ",".join("?" for _ in current_callsigns)
            ),
            current_callsigns,
        )

        conn.executemany(
            "INSERT INTO flights (timestamp, callsign, latitude, longitude) VALUES (?, ?, ?, ?)",
            [
                (
                    record.get("timestamp"),
                    record.get("callsign"),
                    record.get("latitude"),
                    record.get("longitude"),
                )
                for record in filtered_records
            ],
        )
        conn.executemany(
            """
            INSERT INTO flights_history (observed_at, callsign, latitude, longitude)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    record.get("timestamp"),
                    record.get("callsign"),
                    record.get("latitude"),
                    record.get("longitude"),
                )
                for record in filtered_records
            ],
        )
        conn.commit()
    return len(filtered_records)


def main() -> None:
    records = fetch_current_flights()
    stored = persist_flights(records)
    print(f"Stored {stored} REGA flight records in {DB_PATH}")


if __name__ == "__main__":
    main()
