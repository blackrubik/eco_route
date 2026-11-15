"""Units, source-backed factors, and comparison rules without UI or network calls."""

from dataclasses import dataclass
from functools import lru_cache
import json
from math import isfinite
from pathlib import Path

MODES = {
    "walk": "Pėsčiomis",
    "bicycle": "Dviračiu",
    "rail": "Traukiniu",
    "bus": "Autobusu (vietiniu)",
    "car": "Automobiliu",
    "flight": "Lėktuvu",
}
DISTANCE_LABELS = {
    "road": "Apskaičiuotas kelias",
    "bus_road": "Apskaičiuotas kelias autobusu",
    "manual": "Jūsų įvestas atstumas",
    "scenario": "Vienodo atstumo scenarijus",
    "air_scenario": "Apytikslis skrydžio atstumas",
    "rail_estimate": "Apytikslis traukinio kelio ilgis",
    "rail_gtfs": "Traukinio kelias pagal VINTRA duomenis",
    "same_point": "Tie patys taškai; kelionės nėra",
}
SOURCE_PATH = Path(__file__).resolve().parents[1] / "data/emission_factors_2026.json"
DEFAULT_MAX_WALK = 10
DEFAULT_MAX_BICYCLE = 35
DEFAULT_WITH_RF = True


def distance_limit_note(mode: str, limit: float) -> str:
    name = "Pėsčiųjų" if mode == "walk" else "Dviračio"
    return f"{name} alternatyvos lyginamos iki {limit:g} km; šis atstumas ilgesnis."


def nonnegative(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name}: reikia skaičiaus.")
    try:
        value = float(value)
    except OverflowError:
        raise ValueError(f"{name}: skaičius per didelis.") from None
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name}: skaičius turi būti baigtinis ir neneigiamas.")
    return value


def validate_passengers(passengers: int) -> None:
    # Product scope: passenger cars with 1–9 occupants, including the driver.
    if isinstance(passengers, bool) or not isinstance(passengers, int) or not 1 <= passengers <= 9:
        raise ValueError("Automobilyje turi būti nuo 1 iki 9 žmonių (įskaitant vairuotoją).")


@dataclass(frozen=True)
class Factor:
    operating: float
    upstream: float
    per_vehicle: bool
    profile: str
    source_ids: tuple[str, ...]

    @property
    def total(self) -> float:
        return self.operating + self.upstream


@lru_cache(maxsize=1)
def source_data() -> dict:
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def factor_for(mode: str, with_rf: bool = True) -> Factor:
    if mode not in MODES:
        raise ValueError("Nežinomas transportas.")
    if mode in ("walk", "bicycle"):
        return Factor(0, 0, False, "Be variklio; gamyba ir mityba neįtrauktos", ())
    profiles = {
        "car": ("4_301_3074_4_1", "26_904_3074_4_1", "Vidutinis automobilis, nežinomas kuras (JK)"),
        "bus": ("25_314_3145_11_1", "26_910_3145_11_1", "Vidutinis vietinis autobusas (JK)"),
        "rail": ("25_315_3147_11_1", "26_911_3147_11_1", "Vidutinis dyzelinis / elektrinis traukinys (JK)"),
        "flight": (
            "21_316_3178_11_1" if with_rf else "21_316_3179_11_1",
            "22_912_3178_11_1" if with_rf else "22_912_3179_11_1",
            "Tarptautinis skrydis ne į / iš JK; vidutinė klasė; " + ("su RF" if with_rf else "be RF"),
        ),
    }
    operating_id, upstream_id, profile = profiles[mode]
    rows = {r["id"]: r for r in source_data()["rows"]}
    unit = "km" if mode == "car" else "passenger.km"
    values = []
    for identifier in (operating_id, upstream_id):
        row = rows[identifier]
        if row["unit"] != unit or row["ghg"] != "kg CO2e":
            raise ValueError("Netinkami emisijų koeficiento vienetai.")
        values.append(nonnegative(float(row["value"]), "Koeficientas"))
    return Factor(*values, mode == "car", profile, (operating_id, upstream_id))


def emissions_kg(factor: Factor, distance_km: float, car_passengers: int = 1) -> float:
    distance = nonnegative(distance_km, "Atstumas")
    validate_passengers(car_passengers)
    nonnegative(factor.operating, "Koeficientas")
    nonnegative(factor.upstream, "Koeficientas")
    result = distance * factor.total / (car_passengers if factor.per_vehicle else 1)
    return nonnegative(result, "Emisijos")


@dataclass(frozen=True)
class Distance:
    km: float
    kind: str
    duration_seconds: float | None = None
    duration_kind: str = ""
    geometry: tuple[tuple[float, float], ...] = ()  # longitude, latitude
    route_label: str = ""
    source_url: str = ""

    def __post_init__(self):
        nonnegative(self.km, "Atstumas")
        if self.kind not in DISTANCE_LABELS:
            raise ValueError("Nežinomas atstumo šaltinis.")
        if self.duration_seconds is not None:
            nonnegative(self.duration_seconds, "Trukmė")


@dataclass(frozen=True)
class RouteIssue:
    message: str
    excluded_by_distance: bool = False


@dataclass(frozen=True)
class Estimate:
    mode: str
    distance: Distance | None
    co2e_kg: float | None
    note: str
    factor: Factor
    excluded_by_distance: bool = False


def compare(
    distances: dict[str, Distance], selected: str, car_passengers: int = 1,
    with_rf: bool = DEFAULT_WITH_RF, max_walk: float = DEFAULT_MAX_WALK,
    max_bicycle: float = DEFAULT_MAX_BICYCLE,
    failures: dict[str, str | RouteIssue] | None = None,
) -> tuple[Estimate, ...]:
    if selected not in MODES:
        raise ValueError("Nežinomas transportas.")
    validate_passengers(car_passengers)
    limits = {"walk": nonnegative(max_walk, "Ėjimo riba"),
              "bicycle": nonnegative(max_bicycle, "Dviračio riba")}
    results = []
    for mode in MODES:
        factor = factor_for(mode, with_rf)
        distance = distances.get(mode)
        if distance is None:
            issue = (failures or {}).get(mode, "Nėra patvirtinto atstumo.")
            note = issue.message if isinstance(issue, RouteIssue) else issue
            excluded = isinstance(issue, RouteIssue) and issue.excluded_by_distance
            results.append(Estimate(mode, None, None, note, factor, excluded))
        elif mode != selected and mode in limits and distance.km > limits[mode]:
            results.append(Estimate(mode, distance, None, distance_limit_note(mode, limits[mode]), factor, True))
        else:
            results.append(Estimate(mode, distance, emissions_kg(factor, distance.km, car_passengers), "", factor))
    return tuple(results)


def lower_emission_options(estimates: tuple[Estimate, ...], selected: str) -> tuple[Estimate, ...]:
    current = next(e for e in estimates if e.mode == selected)
    if current.co2e_kg is None:
        return ()
    return tuple(sorted(
        (e for e in estimates if e.mode != selected and e.co2e_kg is not None
         and e.co2e_kg < current.co2e_kg - 1e-9),
        key=lambda e: e.co2e_kg,
    ))
