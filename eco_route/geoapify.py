"""Validated, bounded Geoapify requests and session-local caches."""

from collections import OrderedDict, deque
from dataclasses import dataclass
import hashlib
import json
from threading import Lock
import time

import requests

from eco_route.calculations import Distance, nonnegative


class GeoapifyError(Exception):
    """Safe Lithuanian message, never a requests exception containing an API key."""


def normalize_place(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("Įveskite vietos pavadinimą.")
    text = " ".join(text.split())
    if not text or len(text) > 300 or any(ord(c) < 32 for c in text):
        raise ValueError("Vietos pavadinimas turi būti nuo 1 iki 300 simbolių.")
    return text


def coordinates(lat, lon) -> tuple[float, float]:
    if isinstance(lat, bool) or isinstance(lon, bool):
        raise ValueError("Netinkamos koordinatės.")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ValueError("Netinkamos koordinatės.")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Netinkamos koordinatės.")
    return float(lat), float(lon)


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float

    def __post_init__(self):
        coordinates(self.lat, self.lon)

    @property
    def coords(self) -> tuple[float, float]:
        return self.lat, self.lon


class SessionCache:
    """Bounded in-memory cache owned by one browser session; no shared addresses."""

    def __init__(self, max_entries: int = 128, clock=time.monotonic):
        self._entries = OrderedDict()
        self.max_entries = max_entries
        self.clock = clock

    def get(self, key):
        item = self._entries.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= self.clock():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key, value, ttl: float):
        now = self.clock()
        for expired in [k for k, (end, _) in self._entries.items() if end <= now]:
            del self._entries[expired]
        self._entries[key] = (now + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)


class RequestLimiter:
    """Shared across sessions of one server process; never sleeps or retries."""

    def __init__(self, per_minute: int = 30, clock=time.monotonic):
        self.limit = per_minute
        self.clock = clock
        self._times = deque()
        self._lock = Lock()

    def take(self):
        with self._lock:
            now = self.clock()
            while self._times and self._times[0] <= now - 60:
                self._times.popleft()
            if len(self._times) >= self.limit:
                raise GeoapifyError("Pasiektas programos užklausų limitas. Palaukite minutę.")
            self._times.append(now)


class GeoapifyClient:
    BASE_URL = "https://api.geoapify.com/v1/"

    def __init__(self, api_key: str, cache: SessionCache, limiter: RequestLimiter,
                 session=None, clock=time.monotonic, budget_seconds: float = 25):
        if not isinstance(api_key, str) or not api_key.strip() or api_key.strip() == "YOUR_GEOAPIFY_API_KEY":
            raise GeoapifyError("Nenustatytas GEOAPIFY_API_KEY. Galite skaičiuoti pagal žinomą atstumą.")
        self._key = api_key.strip()
        self._credential = hashlib.sha256(self._key.encode()).hexdigest()
        self.cache = cache
        self.limiter = limiter
        self.clock = clock
        self.deadline = clock() + budget_seconds
        self.session = session if session is not None else requests.Session()
        # Avoid .netrc credentials and ambient proxies being attached to API requests.
        self.session.trust_env = False
        self._blocked = None

    def close(self):
        self.session.close()

    def _json(self, endpoint: str, params: dict) -> dict:
        if self._blocked:
            raise GeoapifyError(self._blocked)
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise GeoapifyError("Baigėsi skaičiavimo laikas. Palyginimas gali būti nepilnas.")
        self.limiter.take()
        try:
            with self.session.get(
                self.BASE_URL + endpoint, params={**params, "apiKey": self._key},
                timeout=(min(3, remaining), min(6, remaining)),
                allow_redirects=False, stream=True,
            ) as response:
                if response.status_code in (401, 403, 429):
                    self._blocked = ("Geoapify užklausų limitas pasiektas. Bandykite vėliau."
                                     if response.status_code == 429 else
                                     "Geoapify atmetė prieigą. Patikrinkite serverio API rakto nustatymus.")
                    raise GeoapifyError(self._blocked)
                if not 200 <= response.status_code < 300:
                    raise GeoapifyError("Geoapify nepavyko įvykdyti užklausos. Bandykite vėliau.")
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    if self.clock() > self.deadline:
                        raise GeoapifyError("Baigėsi skaičiavimo laikas. Palyginimas gali būti nepilnas.")
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise GeoapifyError("Geoapify atsakymas per didelis.")
                data = json.loads(body)
        except requests.exceptions.Timeout:
            raise GeoapifyError("Geoapify neatsako laiku. Bandykite vėliau.") from None
        except requests.exceptions.RequestException:
            raise GeoapifyError("Nepavyko susisiekti su Geoapify.") from None
        except (ValueError, UnicodeError):
            raise GeoapifyError("Geoapify grąžino netinkamą atsakymą.") from None
        if not isinstance(data, dict):
            raise GeoapifyError("Geoapify grąžino netinkamą atsakymą.")
        return data

    def search(self, text: str) -> tuple[Place, ...]:
        text = normalize_place(text)
        key = (self._credential, "place", text.casefold())
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        data = self._json("geocode/search", {"text": text, "limit": 1, "format": "geojson"})
        try:
            features = data["features"]
            if not isinstance(features, list):
                raise ValueError
            places = []
            for feature in features[:1]:
                lon, lat = feature["geometry"]["coordinates"]
                if feature["geometry"].get("type") != "Point":
                    raise ValueError
                lat, lon = coordinates(lat, lon)
                label = feature["properties"]["formatted"]
                if not isinstance(label, str) or not label.strip():
                    raise ValueError
                place = Place(label[:500], lat, lon)
                if place not in places:
                    places.append(place)
        except (KeyError, TypeError, ValueError):
            raise GeoapifyError("Nepavyko perskaityti Geoapify vietos duomenų.") from None
        if not places:
            raise GeoapifyError("Vieta nerasta. Patikslinkite miestą, šalį arba adresą.")
        result = tuple(places)
        self.cache.put(key, result, ttl=24 * 3600)
        return result

    def route_km(self, start: Place, end: Place, mode: str) -> float:
        return self.route(start, end, mode).km

    def route(self, start: Place, end: Place, mode: str) -> Distance:
        if mode not in {"walk", "bicycle", "drive", "bus"}:
            raise ValueError("Nepalaikomas maršruto profilis.")
        if start.coords == end.coords:
            return Distance(0, "same_point", duration_seconds=0)
        key = (self._credential, "route-details-v1", start.coords, end.coords, mode)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        data = self._json("routing", {
            "waypoints": f"{start.lat},{start.lon}|{end.lat},{end.lon}",
            "mode": mode, "format": "geojson", "units": "metric",
        })
        try:
            feature = data["features"][0]
            result = feature["properties"]
            if not isinstance(result, dict) or str(result.get("distance_units")).lower() != "meters":
                raise ValueError
            km = nonnegative(result["distance"], "Atstumas") / 1000
            if km == 0:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise GeoapifyError("Maršrutas nerastas arba jo atstumo duomenys netinkami.") from None
        duration = None
        try:
            duration = nonnegative(result["time"], "Trukmė")
            if duration == 0:
                duration = None
        except (KeyError, ValueError):
            pass  # Missing time must not discard a valid distance.
        geometry = parse_geometry(feature.get("geometry"))
        route = Distance(km, "bus_road" if mode == "bus" else "road", duration,
                         "routing" if duration is not None else "", geometry,
                         source_url="https://apidocs.geoapify.com/docs/routing/")
        self.cache.put(key, route, ttl=6 * 3600)
        return route


def parse_geometry(geometry) -> tuple[tuple[float, float], ...]:
    """Discard malformed geometry without losing a valid CO₂ distance result."""
    try:
        kind = geometry["type"]
        lines = geometry["coordinates"]
        if kind == "LineString":
            lines = [lines]
        elif kind != "MultiLineString":
            return ()
        points = []
        for line in lines:
            if len(line) < 2:
                return ()
            for point in line:
                lon, lat = point[:2]
                lat, lon = coordinates(lat, lon)
                pair = (lon, lat)
                if not points or pair != points[-1]:
                    points.append(pair)
        if len(points) < 2:
            return ()
        step = max(1, (len(points)-1)//1000+1)
        return tuple(points[::step] + ([points[-1]] if points[::step][-1] != points[-1] else []))
    except (KeyError, TypeError, ValueError, IndexError):
        return ()
