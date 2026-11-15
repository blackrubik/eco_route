"""Collect distances, preserving successful results when another route fails."""

from geopy.distance import geodesic, great_circle

from eco_route.calculations import (
    DEFAULT_MAX_BICYCLE, DEFAULT_MAX_WALK, Distance, MODES, RouteIssue, distance_limit_note, nonnegative,
)
from eco_route.geoapify import GeoapifyError, Place
from eco_route.rail import lookup_rail

# Barret (2020), §2.5 and Appendix A3: an approximate city-pair rail distance.
# This proxy was fitted to road distances; it does not establish a rail connection.
RAIL_DETOUR_FACTOR = 1.35
RAIL_DISTANCE_SOURCE = (
    "https://travel-footprint-calculator.irap.omp.eu/static/pdf/"
    "dbarret-estimating-monitoring-footprint-athena-xifu.pdf"
)


def route_distances(client, start: Place, end: Place, selected: str,
                    max_walk: float = DEFAULT_MAX_WALK,
                    max_bicycle: float = DEFAULT_MAX_BICYCLE,
                    rail_lookup=None) -> tuple[dict[str, Distance], dict[str, RouteIssue]]:
    if selected not in MODES:
        raise ValueError("Nežinomas transportas.")
    limits = {"walk": nonnegative(max_walk, "Ėjimo riba"),
              "bicycle": nonnegative(max_bicycle, "Dviračio riba")}
    if start.coords == end.coords:
        return {mode: Distance(0, "same_point", duration_seconds=0) for mode in MODES}, {}
    lower_bound = geodesic(start.coords, end.coords).km
    direct_km = great_circle(start.coords, end.coords).km
    distances = {
        "flight": Distance(direct_km, "air_scenario"),
        "rail": Distance(direct_km * RAIL_DETOUR_FACTOR, "rail_estimate"),
    }
    try:
        rail_route = (rail_lookup or lookup_rail)(start, end)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        rail_route = None  # Retain the labelled estimate if the snapshot is unavailable.
    if rail_route is not None:
        distances["rail"] = rail_route
    failures = {}
    profiles = {"walk": "walk", "bicycle": "bicycle", "car": "drive", "bus": "bus"}
    # Fetch the user's choice first; later failures must not hide it.
    order = sorted(profiles, key=lambda mode: mode != selected)
    for mode in order:
        if mode != selected and mode in limits and lower_bound > limits[mode]:
            failures[mode] = RouteIssue(distance_limit_note(mode, limits[mode]), excluded_by_distance=True)
            continue
        try:
            distances[mode] = client.route(start, end, profiles[mode])
        except GeoapifyError as error:
            failures[mode] = RouteIssue(str(error))
    return distances, failures


def scenario_distances(distance_km: float) -> dict[str, Distance]:
    """Same-distance sensitivity comparison; no assertion of route availability."""
    distance = nonnegative(distance_km, "Atstumas")
    return {mode: Distance(distance, "scenario") for mode in MODES}
