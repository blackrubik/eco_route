import streamlit as st
import time
from geopy.geocoders import Nominatim
from geopy.distance import geodesic


st.title('ECO ROUTE')

emissions_per_km = {
    'Pėsčiomis': 0,
    'Dviračiu': 0,
    'Traukiniu': 25,
    'Autobusu': 80,
    'Automobiliu': 150,
    'Lėktuvu': 250
}

alternative_transport_rules = {
    'Pėsčiomis': {"min_km": 0, "max_km": 10, "soft_max_km": 3},
    'Dviračiu': {"min_km": 0, "max_km": 35, "soft_max_km": 15},
    'Traukiniu': {"min_km": 15, "max_km": 2000},
    'Autobusu': {"min_km": 3, "max_km": 1500},
    'Automobiliu': {"min_km": 3, "max_km": 1200},
    'Lėktuvu': {"min_km": 600, "max_km": 20000},
}

kg_per_tree_per_year = 21

def trees_counter(co2_kg: float, kg_per_tree_per_year: float = 21.0) -> float:
    return co2_kg / kg_per_tree_per_year

def tree_days_counter(co2_kg: float, kg_per_tree_per_year: float = 21.0) -> float:
    if co2_kg == 0:
        return 0
    else:
        return co2_kg * 365 / kg_per_tree_per_year

def harm_level(co2_kg: float) -> str:
    if co2_kg < 5:
        return "Žemas"
    if co2_kg < 30:
        return "Vidutinis"
    return "Aukštas"


def eligible_transports(distance: float, rules: dict) -> tuple[list[str], dict]:
    allowed = []
    notes = {}
    
    for t, r in rules.items():
        min_km = r.get('min_km', 0)
        max_km = r.get('max_km', float('inf'))
        
        if not (min_km <= distance <= max_km):
            continue
        
        allowed.append(t)
        
        soft_max = r.get('soft_max_km', None)
        if soft_max != None and soft_max < distance:
            notes[t] = ('Įmanoma, bet sunkokai.')
            
    return allowed, notes


geolocator = Nominatim(user_agent='eco_route_school_project')

@st.cache_data(show_spinner=False)
def get_distance_km(start_text: str, end_text: str) -> float:
    start = geolocator.geocode(start_text)
    time.sleep(1)
    end = geolocator.geocode(end_text)
    
    if not start or not end:
        raise ValueError("Nepavyko rasti vienos iš vietų. Patikslinkite (miestas, šalis).")
    
    return geodesic((start.latitude, start.longitude), (end.latitude, end.longitude)).km

box = st.container(border=True)
with box:
    st.header('Apskaičiuok savo kelionės ekologiškumą!')

    start_text = st.text_input('Išvykimo vieta (pvz., Vilnius, Lithuania):')
    end_text = st.text_input('Kelionės tikslas (pvz., Kaunas, Lithuania):')


    with st.form('cal_form'):
        # travel['end'] = st.text_input('Jūsų kelionės pabaiga:')
        transport = st.selectbox('Transporto tipas:', emissions_per_km.keys())

        passengers = 1
        if transport == 'Automobiliu':
            passengers = st.number_input('Kiek žmonių važiuoja automobiliu?', min_value=1, value=1, step=1)
            
        submitted = st.form_submit_button('Apskaičiuoti')
        
    
if submitted:
    if not start_text.strip() or not end_text.strip():
        st.error('Prašome įvesti išvykimo vietą ir kelionės tikslą.')
    else:
        try:
            distance = get_distance_km(start_text, end_text)
            st.caption(f"Apskaičiuotas atstumas: ~{distance:.1f} km")
            allowed, notes = eligible_transports(distance, alternative_transport_rules)
            

            grams_per_km = emissions_per_km[transport]
            co2_kg = (grams_per_km * distance / 1000.0) / passengers

            st.subheader('Tavo rezultatai:')
            st.write(f'CO₂: **{co2_kg:.2f} kg**')
            st.write(f'Žalos lygis: **{harm_level(co2_kg)}**')

            if co2_kg != 0:
                st.write(f'Medžių kiekis kompensacijai: **{trees_counter(co2_kg):.2f}**')
                st.info(f'Vienam medžiui reikia maždaug **{tree_days_counter(co2_kg):.0f} dienų**, kad kompensuotų šią kelionę.')
            else:
                st.success('Išmetamųjų teršalų kiekis beveik nulinis. Sveikinimai!')
                
            st.divider()
            
            current = transport
            current_em = emissions_per_km[transport]
            
            candidates = [t for t in allowed if emissions_per_km[t] < current_em]
            
            if candidates:
                best = min(candidates, key=lambda t: emissions_per_km[t])
                st.write(f'Rekomenduojame ekologiškesnę alternatyvą: **{best.lower()}**')
                if best in notes:
                    st.caption(notes[best])
            else:
                st.write("Jūsų pasirinkimas jau yra vienas ekologiškiausių!")
                
                
        except ValueError as e:
            st.error(str(e))