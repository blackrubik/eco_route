"""Extract the LTG Link subset of a local official VINTRA GTFS archive.

Usage: python tools/import_lithuanian_rail.py /path/to/gtfs_all.zip
No extraction, network requests, or executable content from the archive.
"""

import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import sys
from zipfile import ZipFile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    hav = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.009 * 2 * math.asin(min(1, math.sqrt(hav)))


def seconds(text):
    h, m, s = map(int, text.split(":"))
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError("Invalid GTFS time")
    return h*3600+m*60+s


def build(archive_path):
    with ZipFile(archive_path) as archive:
        def rows(name):
            return csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="utf-8-sig"))
        agency_ids = {a["agency_id"] for a in rows("agency.txt") if "LTG Link" in a["agency_name"]}
        routes = {r["route_id"] for r in rows("routes.txt")
                  if r["agency_id"] in agency_ids and r["route_type"] == "2"}
        trips = {t["trip_id"]: t for t in rows("trips.txt") if t["route_id"] in routes}
        times = {t: [] for t in trips}
        for row in rows("stop_times.txt"):
            if row["trip_id"] in trips:
                times[row["trip_id"]].append(row)
        stop_ids = {s["stop_id"] for records in times.values() for s in records}
        stops = {s["stop_id"]: {"name": s["stop_name"],
                                "coords": [float(s["stop_lon"]), float(s["stop_lat"])]}
                 for s in rows("stops.txt") if s["stop_id"] in stop_ids}
        shape_ids = {t["shape_id"] for t in trips.values()}
        raw_shapes = {s: [] for s in shape_ids}
        for row in rows("shapes.txt"):
            if row["shape_id"] in shape_ids:
                raw_shapes[row["shape_id"]].append((int(row["shape_pt_sequence"]),
                                                   float(row["shape_pt_lon"]), float(row["shape_pt_lat"])))
        shapes = {}
        for shape_id, records in raw_shapes.items():
            points = []
            total = 0
            for _, lon, lat in sorted(records):
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValueError("Invalid shape coordinates")
                if points:
                    total += km(points[-1][:2], (lon, lat))
                points.append([lon, lat, round(total, 6)])
            shapes[shape_id] = points
        patterns = []
        for trip_id, trip in trips.items():
            points = shapes[trip["shape_id"]]
            sequence = []
            previous_index = 0
            for stop in sorted(times[trip_id], key=lambda r: int(r["stop_sequence"])):
                coords = stops[stop["stop_id"]]["coords"]
                index = min(range(previous_index, len(points)), key=lambda i: km(coords, points[i][:2]))
                if km(coords, points[index][:2]) > 1:
                    raise ValueError(f"Station too far from shape: {stop['stop_id']}")
                previous_index = index
                sequence.append([stop["stop_id"], seconds(stop["arrival_time"]),
                                 seconds(stop["departure_time"]), index])
            if len(sequence) >= 2:
                patterns.append({"service": trip["service_id"], "shape": trip["shape_id"], "stops": sequence})
        services = {t["service_id"] for t in trips.values()}
        calendars = {c["service_id"]: {"start": c["start_date"], "end": c["end_date"],
                     "days": [int(c[d]) for d in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]]}
                     for c in rows("calendar.txt") if c["service_id"] in services}
        exceptions = {}
        for c in rows("calendar_dates.txt"):
            if c["service_id"] in services:
                exceptions.setdefault(c["service_id"], {})[c["date"]] = int(c["exception_type"])
    if not stops or not patterns:
        raise ValueError("No LTG Link rail data found")
    return {
        "source_url": "https://visimarsrutai.lt/gtfs/gtfs_all.zip",
        "source_catalog": "https://data.gov.lt/datasets/1929/?resource_version=914",
        "attribution": "VINTRA / Lietuvos transporto saugos administracija; LTG Link",
        "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "obtained_on": datetime.now(ZoneInfo("Europe/Vilnius")).date().isoformat(),
        "source_sha256": hashlib.sha256(Path(archive_path).read_bytes()).hexdigest(),
        "distance_method": "sum of spherical distances along published GTFS shapes",
        "calendars": calendars, "exceptions": exceptions,
        "stops": stops, "shapes": shapes, "patterns": patterns,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python tools/import_lithuanian_rail.py /path/to/gtfs_all.zip")
    result = build(sys.argv[1])
    target = ROOT / "data/lithuanian_rail.json"
    target.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Imported {len(result['stops'])} stations, {len(result['patterns'])} trips; {target.stat().st_size} bytes")
