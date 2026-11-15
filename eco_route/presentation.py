"""Serializable presentation data, shared by Streamlit and chart tests."""

from eco_route.calculations import DISTANCE_LABELS, MODES


def format_duration(seconds):
    if seconds is None:
        return "Nėra duomenų"
    if seconds == 0:
        return "0 min."
    minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return "≈ " + (f"{hours} val. {minutes} min." if hours else f"{minutes} min.")


def chart_spec(estimates, selected):
    rows = [{"transport": ("≈ " if e.distance.kind in {"rail_estimate", "rail_gtfs", "air_scenario"} else "")
                          + MODES[e.mode] + (" ★" if e.mode == selected else ""),
             "co2e": e.co2e_kg, "selected": e.mode == selected,
             "distance_km": e.distance.km,
             "duration": format_duration(e.distance.duration_seconds),
             "basis": DISTANCE_LABELS[e.distance.kind]}
            for e in estimates if e.co2e_kg is not None]
    rows.sort(key=lambda row: row["co2e"])
    maximum = max((r["co2e"] for r in rows), default=0)
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": rows},
        "height": {"step": 40},
        "encoding": {
            "y": {"field": "transport", "type": "nominal", "sort": [r["transport"] for r in rows], "title": None},
            "x": {"field": "co2e", "type": "quantitative", "title": "kg CO₂e vienam žmogui",
                  "scale": {"domain": [0, maximum * 1.2 if maximum > 0 else 1]}},
            "tooltip": [{"field": "transport", "title": "Transportas"},
                        {"field": "co2e", "title": "kg CO₂e / žmogui", "format": ".2f"},
                        {"field": "distance_km", "title": "Atstumas, km", "format": ".1f"},
                        {"field": "duration", "title": "Trukmė"},
                        {"field": "basis", "title": "Atstumo pagrindas"}],
        },
        "layer": [
            {"mark": {"type": "bar", "cornerRadiusEnd": 4},
             "encoding": {"color": {"condition": {"test": "datum.selected", "value": "#087f73"},
                                     "value": "#90adb6"}}},
            {"mark": {"type": "text", "align": "left", "dx": 6},
             "encoding": {"text": {"field": "co2e", "type": "quantitative", "format": ".2f"}}},
        ],
    }


def duration_chart_spec(estimates, selected):
    timed = [e for e in estimates if e.co2e_kg is not None and e.distance.duration_seconds is not None]
    spec = chart_spec(tuple(timed), selected)
    for row, estimate in zip(spec["data"]["values"], sorted(timed, key=lambda e: e.co2e_kg)):
        row["minutes"] = estimate.distance.duration_seconds / 60
    values = spec["data"]["values"]
    values.sort(key=lambda row: row["minutes"])
    maximum = max((r["minutes"] for r in values), default=0)
    spec["encoding"]["x"] = {"field": "minutes", "type": "quantitative", "title": "Kelionės laikas, min.",
                                 "scale": {"domain": [0, maximum * 1.3 if maximum else 1]}}
    spec["encoding"]["y"]["sort"] = [r["transport"] for r in values]
    spec["layer"][1]["encoding"]["text"] = {"field": "duration", "type": "nominal"}
    return spec


def map_deck(start, end, distance):
    import pydeck as pdk
    markers = [
        {"position": [start.lon, start.lat], "name": start.label, "label": "A", "color": [8, 127, 115]},
        {"position": [end.lon, end.lat], "name": end.label, "label": "B", "color": [224, 119, 48]},
    ]
    layers = []
    if distance and distance.kind == "air_scenario" and start.coords != end.coords:
        layers.append(pdk.Layer(
            "ArcLayer", [{"source": markers[0]["position"], "target": markers[1]["position"]}],
            get_source_position="source", get_target_position="target",
            great_circle=True, get_height=0, num_segments=100,
            get_source_color=[8, 127, 115], get_target_color=[8, 127, 115],
            get_width=4, width_units=pdk.types.String("pixels"),
        ))
    elif distance and distance.geometry:
        layers.append(pdk.Layer("PathLayer", [{"path": list(distance.geometry)}],
                                get_path="path", get_color=[8, 127, 115],
                                get_width=5, width_units=pdk.types.String("pixels"), wrap_longitude=True))
    layers.append(pdk.Layer("ScatterplotLayer", markers, get_position="position", get_fill_color="color",
                            get_radius=8, radius_units=pdk.types.String("pixels"), pickable=True))
    layers.append(pdk.Layer("TextLayer", markers, get_position="position", get_text="label",
                            get_color=[255, 255, 255], get_size=12, size_units=pdk.types.String("pixels")))
    points = [m["position"] for m in markers]
    if distance and distance.geometry:
        points += list(distance.geometry)
    # The basemap uses Web Mercator, whose display range is smaller than WGS84.
    points = [(lon, max(-85, min(85, lat))) for lon, lat in points]
    view = pdk.data_utils.compute_view(points, view_proportion=1)
    view.zoom = min(14, view.zoom)
    return pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto",
                    map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
                    tooltip={"text": "{name}"})
