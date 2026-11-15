"""Offline lookup of direct LTG Link trips from the attributed VINTRA snapshot."""

from datetime import date, datetime
from functools import lru_cache
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from geopy.distance import great_circle

from eco_route.calculations import Distance


@lru_cache(maxsize=1)
def rail_data():
    path = Path(__file__).resolve().parents[1] / "data/lithuanian_rail.json"
    return json.loads(path.read_text(encoding="utf-8"))


def service_active(data, service, day):
    key = day.strftime("%Y%m%d")
    exception = data["exceptions"].get(service, {}).get(key)
    if exception is not None:
        return exception == 1
    calendar = data["calendars"].get(service)
    return bool(calendar and calendar["start"] <= key <= calendar["end"]
                and calendar["days"][day.weekday()])


def lookup_rail(start, end, travel_date: date | None = None, data=None):
    data = rail_data() if data is None else data
    day = travel_date or datetime.now(ZoneInfo("Europe/Vilnius")).date()
    obtained = date.fromisoformat(data["obtained_on"])
    if not 0 <= (day - obtained).days <= 30:
        return None  # Do not present an old snapshot as a current timetable.

    def nearest(place):
        candidates = [(great_circle(place.coords, (stop["coords"][1], stop["coords"][0])).km, identifier)
                      for identifier, stop in data["stops"].items()]
        distance, identifier = min(candidates)
        return identifier if distance <= 8 else None

    origin, destination = nearest(start), nearest(end)
    if origin is None or destination is None or origin == destination:
        return None
    best = None
    for pattern in data["patterns"]:
        if not service_active(data, pattern["service"], day):
            continue
        sequence = pattern["stops"]
        starts = [i for i, s in enumerate(sequence) if s[0] == origin]
        ends = [i for i, s in enumerate(sequence) if s[0] == destination]
        for i in starts:
            for j in ends:
                if j <= i:
                    continue
                first, last = sequence[i], sequence[j]
                seconds = last[1] - first[2]
                points = data["shapes"][pattern["shape"]]
                distance = points[last[3]][2] - points[first[3]][2]
                if seconds <= 0 or distance <= 0:
                    continue
                candidate = (seconds, distance, pattern, first[3], last[3])
                if best is None or candidate[:2] < best[:2]:
                    best = candidate
    if best is None:
        return None
    seconds, distance, pattern, first, last = best
    path = data["shapes"][pattern["shape"]][first:last+1]
    step = max(1, (len(path)-1)//1000+1)
    sample = path[::step]
    if sample[-1] != path[-1]:
        sample.append(path[-1])
    label = data["stops"][origin]["name"] + " → " + data["stops"][destination]["name"]
    return Distance(distance, "rail_gtfs", seconds, "timetable",
                    tuple((p[0], p[1]) for p in sample), label, data["source_catalog"])
