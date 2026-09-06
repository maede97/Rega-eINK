from __future__ import annotations

import sqlite3
from pathlib import Path
import datetime

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
        if getattr(flight, "callsign", None) is None:
            continue
        callsign = getattr(flight, "callsign", "")
        if len(callsign) < 3:
            continue
        if callsign[:3] != AIRLINE_ICAO:
            # sometimes, the callsign is the aircraft and not RGAXX
            continue
        records.append(
            {
                "timestamp": getattr(flight, "time", None),
                "callsign": getattr(flight, "callsign", None),
                "latitude": getattr(flight, "latitude", None),
                "longitude": getattr(flight, "longitude", None),
                "active": 1
            }
        )
    return records


def persist_flights(records: list[dict[str, object]]) -> int:
    filtered_records = [record for record in records if record.get("callsign")]

    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)

        # delete only the rows where no longer a callsign is present. but keep the last location but mark as inactive
        current_callsigns = [record.get("callsign") for record in filtered_records]
        conn.execute(
            "UPDATE flights SET active = 0 WHERE callsign NOT IN ({})".format(
                ",".join("?" for _ in current_callsigns)
            ),
            current_callsigns,
        )
        # now delete the old flightpaths (inactive) but keep only the latest one for each callsign
        conn.execute(
            """
            DELETE FROM flights
            WHERE rowid NOT IN (
                SELECT MAX(rowid)
                FROM flights
                GROUP BY callsign
            )
            AND active = 0
            """
        )
        
        conn.executemany(
            "INSERT INTO flights (timestamp, callsign, latitude, longitude, active) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    record.get("timestamp"),
                    record.get("callsign"),
                    record.get("latitude"),
                    record.get("longitude"),
                    record.get("active"),
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

        # delete all history entries which are older than two weeks
        two_weeks_ago = datetime.datetime.utcnow() - datetime.timedelta(weeks=2)
        two_weeks_ago_unix_timestamp = int(two_weeks_ago.timestamp())
        conn.execute(
            "DELETE FROM flights_history WHERE observed_at < ?",
            (two_weeks_ago_unix_timestamp,),
        )

        conn.commit()
    return len(filtered_records)


def main() -> None:
    records = fetch_current_flights()
    stored = persist_flights(records)
    print(f"Stored {stored} REGA flight records in {DB_PATH}")


if __name__ == "__main__":
    main()
