"""Lithuanian Streamlit interface for the Eco Route scenario calculator."""

import time

import streamlit as st

from eco_route.calculations import (
    DISTANCE_LABELS, MODES, compare, lower_emission_options, source_data,
)
from eco_route.geoapify import (
    GeoapifyClient, GeoapifyError, RequestLimiter, SessionCache, normalize_place,
)
from eco_route.journey import RAIL_DETOUR_FACTOR, RAIL_DISTANCE_SOURCE, route_distances, scenario_distances
from eco_route.presentation import chart_spec, duration_chart_spec, format_duration, map_deck


st.set_page_config(page_title="Eco Route", page_icon="🌿", layout="wide")
RESULT_VERSION = 4


@st.cache_resource
def server_limiter():
    return RequestLimiter(per_minute=30)


def api_key():
    try:
        value = st.secrets.get("GEOAPIFY_API_KEY", "")
    except (FileNotFoundError, KeyError, st.errors.StreamlitSecretNotFoundError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def client_for_action():
    key = api_key()
    if not key or key == "YOUR_GEOAPIFY_API_KEY":
        raise GeoapifyError("Nenustatytas GEOAPIFY_API_KEY. Pasirinkite „Žinomas atstumas“.")
    now = time.monotonic()
    if now - st.session_state.get("eco_last_action", -100) < 5:
        raise GeoapifyError("Prieš kitą paiešką ar skaičiavimą palaukite 5 sekundes.")
    st.session_state.eco_last_action = now
    if "eco_cache" not in st.session_state:
        st.session_state.eco_cache = SessionCache()
    return GeoapifyClient(key, st.session_state.eco_cache, server_limiter())


def save_result(distances, failures, signature, title, places=None):
    estimates = compare(distances, selected, passengers, failures=failures)
    st.session_state.eco_result = {
        "version": RESULT_VERSION,
        "estimates": estimates, "selected": selected, "signature": signature,
        "title": title, "passengers": passengers,
        "source": source_data()["source_page"],
        "places": places,
    }


st.title("🌿 ECO ROUTE")
st.write("Palyginkite kelionės emisijas ir raskite ekologiškesnią alternatyvą.")
st.caption("Viena kryptis · vienam žmogui · vidutiniai scenarijai, ne tikslus kelionės matavimas")
if st.button("Išvalyti šios sesijos duomenis", key="clear_session"):
    for name in list(st.session_state):
        if name.startswith("eco_"):
            del st.session_state[name]

with st.container(border=True):
    source_mode = st.radio("Kaip nurodysite atstumą?", ["Vietų paieška", "Žinomas atstumas"],
                           horizontal=True, key="eco_source_mode")
    left, right = st.columns(2)
    selected = left.selectbox("Transporto tipas", list(MODES), index=4,
                              format_func=MODES.get, key="eco_transport")
    passengers = 1
    if selected == "car":
        passengers = int(right.number_input("Žmonių automobilyje, įskaitant vairuotoją",
                                            min_value=1, max_value=9, value=1, step=1,
                                            key="eco_passengers"))

    common = (source_mode, selected, passengers)
    signature = common
    if source_mode == "Žinomas atstumas":
        distance = st.number_input("Palyginimo atstumas, km", min_value=0.0, max_value=50000.0,
                                   value=100.0, step=1.0, key="eco_manual_km")
        st.caption("Palyginimui visoms transporto rūšims taikomas tas pats atstumas.")
        signature = common + (distance,)
        if st.button("Apskaičiuoti", type="primary", key="eco_calculate_manual"):
            save_result(scenario_distances(distance), {}, signature, f"{distance:g} km scenarijus")
    else:
        st.caption("Vietų pavadinimai siunčiami Geoapify kelio atstumui apskaičiuoti.")
        if not api_key() or api_key() == "YOUR_GEOAPIFY_API_KEY":
            st.info("Vietų paieškai reikia serverio GEOAPIFY_API_KEY. Režimas „Žinomas atstumas“ veikia be rakto.")
        left, right = st.columns(2)
        start_text = left.text_input("Išvykimo vieta", placeholder="Vilnius, Lietuva", key="eco_start")
        end_text = right.text_input("Kelionės tikslas", placeholder="Kaunas, Lietuva", key="eco_end")
        query = (" ".join(start_text.split()), " ".join(end_text.split()))
        signature = common + query
        if st.button("Apskaičiuoti", type="primary", key="eco_calculate_route"):
            client = None
            try:
                start_query, end_query = normalize_place(start_text), normalize_place(end_text)
                with st.spinner("Randame vietas ir skaičiuojame kelionę…"):
                    client = client_for_action()
                    start = client.search(start_query)[0]
                    end = client.search(end_query)[0]
                    distances, failures = route_distances(client, start, end, selected)
                save_result(distances, failures, signature, start.label + " → " + end.label, (start, end))
            except (GeoapifyError, ValueError) as error:
                st.error(str(error))
            finally:
                if client is not None:
                    client.close()

result = st.session_state.get("eco_result")
if result and result.get("version") != RESULT_VERSION:
    del st.session_state.eco_result
    result = None
if result:
    st.subheader("Kelionės rezultatai")
    st.text(result["title"])
    if signature != result["signature"]:
        st.warning("Nustatymai pakeisti. Žemiau rodomas ankstesnis rezultatas — perskaičiuokite.")
    estimates = result["estimates"]
    current = next(e for e in estimates if e.mode == result["selected"])
    selection_caption = f"Pasirinkta: {MODES[current.mode]}"
    if current.mode == "car":
        selection_caption += f" · žmonių automobilyje: {result['passengers']}"
    st.caption(selection_caption)
    if current.co2e_kg is not None:
        columns = st.columns(3 if current.distance.duration_seconds is not None else 2)
        left, right = columns[:2]
        approximate = current.distance.kind in {"rail_estimate", "rail_gtfs", "air_scenario"}
        prefix = "≈ " if approximate else ""
        left.metric("Emisijos vienam žmogui", f"{prefix}{current.co2e_kg:.2f} kg CO₂e")
        right.metric("Kelionės atstumas", f"{prefix}{current.distance.km:.1f} km")
        if current.distance.duration_seconds is not None:
            columns[2].metric("Kelionės trukmė", format_duration(current.distance.duration_seconds))
        st.caption(DISTANCE_LABELS[current.distance.kind])
        if current.distance.kind == "rail_gtfs":
            st.caption(current.distance.route_label + " · tarp stočių, be laukimo ir atvykimo į stotį.")
        elif current.mode == "bus" and current.distance.duration_seconds is not None:
            st.caption("Autobuso trukmė pagal kelių modelį, be sustojimų ir laukimo.")
    else:
        st.warning("Pasirinktos kelionės emisijos neapskaičiuotos: " + current.note)
    if result["places"]:
        start, end = result["places"]
        st.subheader("Kelionės žemėlapis")
        st.pydeck_chart(map_deck(start, end, current.distance), height=380, width="stretch")
        st.caption("A — išvykimo vieta · B — kelionės tikslas.")
        if current.distance and current.distance.kind == "rail_gtfs":
            st.caption("Linija tarp stočių: VINTRA / LTSA, LTG Link · CC BY 4.0. Kelias iki stočių neįtrauktas.")
        elif current.distance and current.distance.kind == "air_scenario":
            st.caption("Apytikslė skrydžio trajektorija tarp rastų vietų.")
        elif current.distance is None or not current.distance.geometry:
            st.caption("Rodomos rastos vietos; šiam variantui tikslios kelio linijos neturime.")
    st.subheader("Transporto palyginimas")
    available = [e for e in estimates if e.co2e_kg is not None]
    if available:
        emissions_tab, time_tab = st.tabs(["CO₂e", "Kelionės laikas"])
        with emissions_tab:
            st.vega_lite_chart(chart_spec(estimates, result["selected"]), width="stretch")
        with time_tab:
            if any(e.distance.duration_seconds is not None for e in available):
                st.vega_lite_chart(duration_chart_spec(estimates, result["selected"]), width="stretch")
                st.caption("Kelio laikas — modelio įvertis; traukinio — pagal tvarkaraštį, be laukimo ir atvykimo į stotį. Vėlavimai neįvertinti.")
            else:
                st.caption("Laikui palyginti nurodykite kelionės vietas. Vien atstumo nepakanka patikimai trukmei įvertinti.")
            if any(e.mode == "flight" and e.distance.duration_seconds is None for e in available):
                st.caption("Skrydžio trukmei reikia konkretaus reiso ir oro uostų duomenų.")
        legend = "★ — jūsų pasirinkimas."
        if any(e.distance.kind in {"rail_estimate", "rail_gtfs", "air_scenario"} for e in available):
            legend += " ≈ — apytikslis atstumas."
        st.caption(legend + " Užveskite žymeklį, kad pamatytumėte atstumą ir emisijas.")
    missing = [e for e in estimates if e.co2e_kg is None and not e.excluded_by_distance]
    if missing:
        with st.expander(f"Neįtraukti variantai ({len(missing)})"):
            for estimate in missing:
                st.write(f"{MODES[estimate.mode]}: {estimate.note}")
    options = lower_emission_options(estimates, result["selected"])
    if options:
        best_value = options[0].co2e_kg
        best = [e for e in options if abs(e.co2e_kg - best_value) < 1e-9]
        saved = current.co2e_kg - best_value
        st.success(f"Mažesnių emisijų scenarijus: {', '.join(MODES[e.mode] for e in best)}. Galimas skirtumas: {saved:.2f} kg CO₂e ({saved / current.co2e_kg:.1%}).")
    elif current.co2e_kg is not None:
        st.write("Tarp apskaičiuotų scenarijų mažesnių emisijų nerasta.")
    with st.expander("Kaip apskaičiuota? Šaltiniai ir prielaidos"):
        st.write("CO₂e leidžia palyginti skirtingų šiltnamio dujų poveikį. Skaičiuojama eksploatacija ir paskelbta kuro / energijos gamybos bei tiekimo dalis (WTT). Transporto gamyba, infrastruktūra ir žmogaus mityba neįtrauktos.")
        st.code("Automobilis: km × koeficientas / žmonių skaičius\nKitas transportas: km × koeficientas", language=None)
        unit = "kg CO₂e / automobilio km" if current.factor.per_vehicle else "kg CO₂e / keleivio-km"
        st.write(f"Pasirinkto transporto koeficientas: {current.factor.total:.5f} {unit}. Profilis: {current.factor.profile}.")
        st.write("Pėsčiųjų alternatyvos lyginamos iki 10 km, dviračio — iki 35 km. Pasirinktą transportą skaičiuojame ir ilgesniam keliui.")
        st.write(f"Kai vietinių maršruto duomenų nėra, traukinio kelią įvertiname: trumpiausias atstumas tarp rastų taškų Žemės paviršiumi × {RAIL_DETOUR_FACTOR:g}. Vandens kliūtys, kalnai ir persėdimai gali smarkiai pakeisti tikrąjį ilgį.")
        st.write("Kur yra tiesioginis LTG Link maršrutas VINTRA duomenyse, naudojame jo liniją ir tvarkaraščio trukmę tarp artimiausių stočių (iki 8 km nuo rastos vietos). Tikrinamos duomenų kalendoriaus datos; pasirenkama trumpiausia važiavimo trukmė tą dieną, ne konkretus dar neišvykęs reisas. Stoties pasiekimas ir laukimas neįtraukti. ×1,35 taikoma tik kai tokių duomenų nėra.")
        st.markdown("[VINTRA duomenys ir CC BY 4.0 licencija](https://data.gov.lt/datasets/1929/?resource_version=914)")
        st.markdown(f"[Traukinio atstumo vertinimo metodas — Barret (2020)]({RAIL_DISTANCE_SOURCE})")
        st.write("Lėktuvui naudojamas trumpiausias atstumas tarp rastų taškų. Koeficientas jau apima papildomą aviacijos poveikį klimatui (RF) ir 8 % atstumo pataisą — pakartotinai jų nepridedame. Kelionė iki oro uosto neįtraukta.")
        st.write("Grafikas palygina prognozuojamas emisijas. VINTRA traukinio trukmė yra tvarkaraščio pavyzdys; bilietų prieinamumas, atšaukimai, autobusų ir skrydžių tvarkaraščiai netikrinami. Autobusui taikomas vietinio autobuso profilis.")
        st.markdown(f"[DESNZ 2026: oficialūs koeficientai]({result['source']})")
        st.caption("Contains public sector information licensed under the Open Government Licence v3.0.")

else:
    st.info("Įveskite kelionės vietas arba žinomą atstumą ir spauskite „Apskaičiuoti“. Rezultatas bus rodomas čia.")
