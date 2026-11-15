# Eco Route

„Streamlit“ programa, skirta apytikslėms kelionės CO₂e emisijoms įvertinti ir
transporto scenarijams palyginti. Sąsaja pateikiama lietuvių kalba. Repozitorija:
https://github.com/blackrubik/eco_route

## Galimybės

- Vienam žmogui tenkančios vienos krypties kelionės emisijos skaičiuojamos
  pagal patikrintus DESNZ 2026 koeficientus.
- Žmonių skaičius taikomas automobiliui; viešojo transporto emisijos papildomai
  iš bendrakeleivių skaičiaus nedalijamos.
- „Žinomas atstumas“: to paties atstumo palyginimas be API rakto ir tinklo užklausų.
- Pirmoji „Geoapify“ rasta vieta naudojama iš karto, be patvirtinimo. Keliai
  skaičiuojami pėsčiųjų, dviračio, automobilio ir vietinio autobuso profiliais.
- Grafikas su atstumais užvedus žymeklį, galimas emisijų sumažėjimas ir pradinių
  duomenų paaiškinimas.
- Rastų vietų ir gauto kelio žemėlapis, kelionės trukmė šalia CO₂e rezultato
  ir atskira trukmės palyginimo kortelė.
- Tiesioginėms „LTG Link“ kelionėms naudojamos VINTRA maršrutų linijos ir laikas
  tarp stočių; neradus tinkamų duomenų paliekamas apytikslis įvertis.
- Dalinis rezultatas išlieka įvykus klaidai. Rezultatas išsaugomas, o pakeitus
  įvestį pažymima, kad jį reikia perskaičiuoti.

[Skaičiavimo metodika](docs/methodology.md) ·
[Likę darbai](docs/roadmap.md) · [Patikrų rezultatai](docs/validation.md).

## Paleidimas

Numatytos „Python“ versijos — 3.11 ir 3.13; „Codespaces“ naudoja 3.11.
Vietiniai testai atlikti su 3.13.2. Projekto šakniniame aplanke paleiskite:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pip==26.3
python -m pip install -r requirements.lock
python -m streamlit run app.py
```

Greita patikra: pasirinkite „Žinomas atstumas“, 100 km, automobilį ir vieną žmogų,
tada spauskite „Apskaičiuoti“. Tikėtinas rezultatas — **20,99 kg CO₂e**.

Vietų paieškai sukurkite `.streamlit/secrets.toml` pagal
`.streamlit/secrets.example.toml` pavyzdį ir įrašykite savo `GEOAPIFY_API_KEY`.
Esamo failo su raktu neperrašykite. Prieglobos aplinkoje naudokite „Secrets“
nustatymus. Be rakto puslapis ir režimas su žinomu atstumu toliau veikia.

## Projekto struktūra

| Failas | Paskirtis |
|---|---|
| `app.py` | Sąsaja ir sesijos būsena |
| `eco_route/calculations.py` | Koeficientai, vienetai ir skaičiavimai |
| `eco_route/geoapify.py` | Tinklo klientas, atsakymų tikrinimas, podėlis ir užklausų ribojimas |
| `eco_route/journey.py` | Atstumų surinkimas išsaugant dalinį rezultatą |
| `eco_route/presentation.py` | CO₂e ir trukmės grafikai bei žemėlapis |
| `eco_route/rail.py` | Tiesioginių traukinių paieška pagal VINTRA kalendorius |
| `data/lithuanian_rail.json` | Atvirųjų stočių, maršrutų linijų ir tvarkaraščių duomenų kopija |
| `tools/import_lithuanian_rail.py` | Geležinkelio duomenų kopijos atnaujinimas |
| `data/emission_factors_2026.json` | Koeficientai, vienetai ir šaltinių identifikatoriai |
| `tools/verify_factors.py` | Pakartotinis palyginimas su oficialiu XLSX failu |
| `tests/` | „unittest“ ir „Streamlit AppTest“ testai be tikro API |

`requirements.txt` nurodo fiksuotas tiesioginių priklausomybių versijas,
`requirements.lock` — visą jų medį „Python“ 3.11/3.13 aplinkoms su „macOS“ arba
„Linux“, įskaitant atskiras „NumPy“ versijas. Šie failai atnaujinami kartu,
atlikus testus ir auditą. „pip“ atnaujinamas atskira komanda.

## Privatumas ir apkrova

Vietų pavadinimai ir koordinatės perduodami „Geoapify“. Rakto, adresų ir viso URL
su `apiKey` negalima įrašyti į „Git“, pranešimus ar žurnalus. Podėlis laikomas tik
konkrečios sesijos atmintyje: iki 128 įrašų, paieškos duomenys — iki 24 valandų,
maršrutai — iki 6 valandų. Podėlio rakte naudojamas slaptojo rakto maišos atspaudas.
Išvalymo mygtukas pašalina sesijos duomenis.

Vienam skaičiavimui pagal vietas reikia iki šešių HTTP užklausų: dviejų paieškų
ir iki keturių kelių profilių. Traukinio kelias įvertinamas automatiškai be
papildomos užklausos. Podėlis sumažina užklausų skaičių. Automatiškai jos
nekartojamos; gavus 401/403/429 atsakymą naujos tos operacijos užklausos nebesiunčiamos.
Riba — 30 užklausų per minutę vienam procesui ir 5 sekundės tarp sesijos tinklo
veiksmų. Keliems procesams reikia išorinio bendro užklausų ribojimo mechanizmo.
API klientas nenaudoja `.netrc`, aplinkos tarpinių serverių ar peradresavimų.

Operacijai skiriamas 25 sekundžių laiko biudžetas, tikrinamas prieš užklausą ir
skaitant atsakymą. Prisijungimo ir skaitymo laukimo ribos — iki 3 ir 6 sekundžių,
atsakymo dydis — iki 2 MB. Tai nėra griežta bendro laukimo riba: DNS ir tinklo
veikimas gali ją pailginti.

## Patikros ir publikavimas

```sh
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -m pip check
python3 -B tools/verify_factors.py /path/to/official-factors.xlsx
```

„GitHub Actions“ paruoštas testams ir auditui su „Python“ 3.11/3.13; darbo eiga
bus paleista išsiuntus pakeitimus į „GitHub“ („push“). „Codespaces“ įdiegia
priklausomybes ir atveria peržiūrą per 8501 prievadą. CORS/XSRF apsaugos įjungtos.
Pats konteineris ir nuotolinė CI darbo eiga dar nebuvo paleisti. Vieša priegloba
nesukonfigūruota. Pakeitimų fiksavimas („commit“), siuntimas („push“) ir publikavimas
atliekami atskirais veiksmais.

## Rezultatų patikimumo ribos

Koeficientai daugiausia atspindi Jungtinės Karalystės vidurkius ir nėra pritaikyti
būtent Lietuvai. Sumuojama eksploatacija ir paskelbta WTT dalis — kuro ar energijos
gamyba bei tiekimas. Tai nėra visas gyvavimo ciklas.

Neradus tinkamo tiesioginio traukinio VINTRA duomenyse, kelio ilgis įvertinamas
automatiškai: didžiojo apskritimo lanko atstumas tarp rastų taškų × 1,35
(Barret, 2020 metodas). Radus traukinį, ilgis nustatomas pagal maršruto liniją,
o trukmė — pagal tvarkaraštį tarp stočių, neįskaitant laukimo ir atvykimo į stotį.
Duomenų kopiją reikia atnaujinti po 30 dienų.

Skrydis tarp rastų taškų yra scenarijus be konkrečių oro uostų, atvykimo į juos ir
persėdimų. Reisų buvimas netikrinamas. Autobuso profilis yra vietinis, ne tarpmiestinis.
Nulinės ėjimo ir įprasto dviračio emisijos taikomos tik apibrėžtose skaičiavimo
ribose. „Žalos“ ir kompensavimo medžiais rodikliai pašalinti.

[Lietuvos duomenys, jų atnaujinimas ir vietinių koeficientų patikra](docs/local-data.md).
