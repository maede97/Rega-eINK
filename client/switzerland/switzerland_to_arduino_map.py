#!/usr/bin/env python3
"""Fetch Switzerland map geometry from OpenStreetMap and emit Arduino arrays.

This script downloads the national boundary from Overpass, samples it to a
compact point set, and prints C++ constants that can be pasted into swiss.ino.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
import math
from pathlib import Path
import urllib.parse
import urllib.request


OVERPASS_URL = "https://overpass.osm.ch/api/interpreter"
OVERPASS_SWITZERLAND_QUERY = """[out:json][timeout:120];
rel(51701);
out body;
>;
out geom;
"""

HEADER_PATH = Path("./switzerland_outline.h")

DOUGLAS_PEUCKER_EPSILON_METERS = 1300.0
MERGE_TOLERANCE_DEGREES = 5e-4

@dataclass
class Way:
    lat: list[float]
    lon: list[float]


@dataclass
class Point:
    lat: float
    lon: float
    x: float
    y: float


def fetch_geometry(query: str) -> list[Way]:
    request = urllib.request.Request(
        OVERPASS_URL,
        data=("data=" + urllib.parse.quote(query)).encode("utf-8"),
        method="POST",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; SwitzerlandMapGenerator/1.0)",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))

    elements = payload.get("elements", [])
    if not elements:
        raise RuntimeError("No Switzerland relation returned by Overpass")

    relation = next((element for element in elements if element.get("type") == "relation"), None)
    if relation is None:
        raise RuntimeError("No Switzerland relation element returned by Overpass")

    outer_way_ids: set[int] = set()
    ways: list[Way] = []
    for member in relation.get("members", []):
        if member.get("type") != "way" or member.get("role") != "outer":
            continue

        reference = member.get("ref")
        if reference is not None:
            outer_way_ids.add(int(reference))

        geometry = member.get("geometry")
        if geometry:
            lat = [float(point["lat"]) for point in geometry]
            lon = [float(point["lon"]) for point in geometry]
            if len(lat) >= 2:
                ways.append(Way(lat=lat, lon=lon))

    if not ways:
        for element in elements:
            if element.get("type") != "way":
                continue

            reference = element.get("id")
            if reference is None or int(reference) not in outer_way_ids:
                continue

            geometry = element.get("geometry")
            if not geometry:
                continue

            lat = [float(point["lat"]) for point in geometry]
            lon = [float(point["lon"]) for point in geometry]
            if len(lat) < 2:
                continue
            ways.append(Way(lat=lat, lon=lon))

    if not ways:
        raise RuntimeError("Switzerland relation contained no outer way geometry")

    return ways


def perpendicular_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    if start == end:
        return ((point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2) ** 0.5

    x0, y0 = point
    x1, y1 = start
    x2, y2 = end
    numerator = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
    denominator = ((y2 - y1) ** 2 + (x2 - x1) ** 2) ** 0.5
    return numerator / denominator


def points_match(lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
    return abs(lat1 - lat2) <= MERGE_TOLERANCE_DEGREES and abs(lon1 - lon2) <= MERGE_TOLERANCE_DEGREES


def stitch_ways(ways: list[Way]) -> list[Way]:
    remaining = [Way(lat=way.lat[:], lon=way.lon[:]) for way in ways]
    stitched: list[Way] = []

    while remaining:
        current = remaining.pop(0)

        changed = True
        while changed:
            changed = False
            for index, candidate in enumerate(remaining):
                if points_match(current.lat[-1], current.lon[-1], candidate.lat[0], candidate.lon[0]):
                    current.lat.extend(candidate.lat[1:])
                    current.lon.extend(candidate.lon[1:])
                    remaining.pop(index)
                    changed = True
                    break
                if points_match(current.lat[-1], current.lon[-1], candidate.lat[-1], candidate.lon[-1]):
                    current.lat.extend(reversed(candidate.lat[:-1]))
                    current.lon.extend(reversed(candidate.lon[:-1]))
                    remaining.pop(index)
                    changed = True
                    break
                if points_match(current.lat[0], current.lon[0], candidate.lat[-1], candidate.lon[-1]):
                    current.lat = candidate.lat[:-1] + current.lat
                    current.lon = candidate.lon[:-1] + current.lon
                    remaining.pop(index)
                    changed = True
                    break
                if points_match(current.lat[0], current.lon[0], candidate.lat[0], candidate.lon[0]):
                    current.lat = list(reversed(candidate.lat[1:])) + current.lat
                    current.lon = list(reversed(candidate.lon[1:])) + current.lon
                    remaining.pop(index)
                    changed = True
                    break

        stitched.append(current)

    return stitched


def project_point(lat: float, lon: float, center_lat_rad: float) -> tuple[float, float]:
    meters_per_lon = 111320.0 * math.cos(center_lat_rad)
    meters_per_lat = 110540.0
    x = (lon - 5.9560800) * meters_per_lon
    y = (lat - 45.8179950) * meters_per_lat
    return x, y


def douglas_peucker(points: list[Point], epsilon: float) -> list[Point]:
    if len(points) < 3:
        return points

    max_distance = 0.0
    index = 0
    start = points[0]
    end = points[-1]
    for i in range(1, len(points) - 1):
        distance = perpendicular_distance((points[i].x, points[i].y), (start.x, start.y), (end.x, end.y))
        if distance > max_distance:
            index = i
            max_distance = distance

    if max_distance > epsilon:
        left = douglas_peucker(points[: index + 1], epsilon)
        right = douglas_peucker(points[index:], epsilon)
        return left[:-1] + right

    return [start, end]


def emit_way_arrays(prefix: str, ways: list[Way], lines: list[str]) -> None:
    stitched_ways = stitch_ways(ways)
    center_lat_rad = math.radians((45.8179950 + 47.8084550) * 0.5)

    for index, way in enumerate(stitched_ways):
        points = [Point(lat=lat, lon=lon, x=project_point(lat, lon, center_lat_rad)[0], y=project_point(lat, lon, center_lat_rad)[1]) for lat, lon in zip(way.lat, way.lon)]
        simplified = douglas_peucker(points, DOUGLAS_PEUCKER_EPSILON_METERS)
        lat_values = ", ".join(f"{point.lat:.7f}f" for point in simplified)
        lon_values = ", ".join(f"{point.lon:.7f}f" for point in simplified)
        lines.append(f"static const float {prefix}_{index}_LAT[] = {{ {lat_values} }};")
        lines.append(f"static const float {prefix}_{index}_LON[] = {{ {lon_values} }};")
        lines.append("")


def emit_header(switzerland_ways: list[Way]) -> str:
    lines = ["#pragma once", "", "#include <stdint.h>", ""]
    lines.append("struct SwitzerlandWay {")
    lines.append("  uint8_t count;")
    lines.append("  const float *lat;")
    lines.append("  const float *lon;")
    lines.append("};")
    lines.append("")

    emit_way_arrays("SWITZERLAND_WAY", switzerland_ways, lines)
    stitched_ways = stitch_ways(switzerland_ways)
    lines.append(f"static const uint8_t SWITZERLAND_WAY_COUNT = {len(stitched_ways)};")
    lines.append("static const SwitzerlandWay SWITZERLAND_WAYS[] = {")
    center_lat_rad = __import__("math").radians((45.8179950 + 47.8084550) * 0.5)
    for index, way in enumerate(stitched_ways):
        points = [Point(lat=lat, lon=lon, x=project_point(lat, lon, center_lat_rad)[0], y=project_point(lat, lon, center_lat_rad)[1]) for lat, lon in zip(way.lat, way.lon)]
        simplified = douglas_peucker(points, DOUGLAS_PEUCKER_EPSILON_METERS)
        lines.append(
            f"  {{ {len(simplified)}, SWITZERLAND_WAY_{index}_LAT, SWITZERLAND_WAY_{index}_LON }},"
        )
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    switzerland_ways = fetch_geometry(OVERPASS_SWITZERLAND_QUERY)
    HEADER_PATH.write_text(emit_header(switzerland_ways), encoding="utf-8")
    print(f"wrote {HEADER_PATH} with {len(switzerland_ways)} Switzerland ways")


if __name__ == "__main__":
    main()
