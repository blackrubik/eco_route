from pathlib import Path
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from eco_route.geoapify import GeoapifyError, Place
from eco_route.calculations import Distance

APP = Path(__file__).resolve().parents[1] / "app.py"


class FakeClient:
    def __init__(self, *args):
        pass

    def search(self, text):
        if "Vilnius" in text:
            return (Place("Vilnius, Lietuva", 54.68, 25.28), Place("Vilnius, kita vieta", 55, 25))
        return (Place("Kaunas, Lietuva", 54.9, 23.9),)

    def route(self, start, end, mode):
        if mode == "bus":
            raise GeoapifyError("Autobuso kelias nerastas.")
        return Distance(110, "road", 5400, "routing", ((start.lon, start.lat), (end.lon, end.lat)))

    def close(self):
        pass


class AppTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("requests.Session.get", side_effect=AssertionError("Real network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.secrets = patch("streamlit.secrets", {})
        self.secrets.start()
        self.addCleanup(self.secrets.stop)

    def app(self):
        app = AppTest.from_file(APP, default_timeout=15).run()
        self.assertFalse(app.exception)
        return app

    def manual(self):
        app = self.app()
        app.radio(key="eco_source_mode").set_value("Žinomas atstumas").run()
        app.button(key="eco_calculate_manual").click().run()
        return app

    def test_missing_secret_does_not_break_page_or_manual_calculation(self):
        app = self.manual()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "20.99 kg CO₂e")
        self.assertEqual(len(app.dataframe), 0)
        self.assertEqual(len(app.get("arrow_vega_lite_chart")) + len(app.get("vega_lite_chart")), 1)

    def test_unavailable_secrets_file_does_not_crash(self):
        from unittest.mock import Mock
        missing = Mock()
        missing.get.side_effect = st.errors.StreamlitSecretNotFoundError("No secrets")
        with patch("streamlit.secrets", missing):
            app = self.app()
            app.button(key="eco_calculate_route").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)

    def test_result_persists_and_is_marked_stale(self):
        app = self.manual()
        app.number_input(key="eco_passengers").set_value(3).run()
        self.assertEqual(app.metric[0].value, "20.99 kg CO₂e")
        self.assertTrue(any("ankstesnis" in warning.value for warning in app.warning))
        app.button(key="eco_calculate_manual").click().run()
        self.assertEqual(app.metric[0].value, "7.00 kg CO₂e")
        self.assertFalse(any("ankstesnis" in warning.value for warning in app.warning))

    def test_zero_distance_no_division_by_zero(self):
        app = self.manual()
        app.number_input(key="eco_manual_km").set_value(0).run()
        app.button(key="eco_calculate_manual").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "0.00 kg CO₂e")
        self.assertFalse(app.success)

    def test_clear_removes_result(self):
        app = self.manual()
        app.button(key="clear_session").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.metric)
        self.assertNotIn("eco_result", app.session_state)

    def test_previous_version_result_is_not_shown_with_changed_method(self):
        app = self.manual()
        old_result = dict(app.session_state["eco_result"])
        old_result.pop("version")
        app.session_state["eco_result"] = old_result
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.metric)

    def test_first_found_places_calculated_in_one_click_with_partial_failure(self):
        with patch("streamlit.secrets", {"GEOAPIFY_API_KEY": "test-key"}), \
                patch("eco_route.geoapify.GeoapifyClient", FakeClient):
            app = self.app()
            app.text_input(key="eco_start").set_value("Vilnius")
            app.text_input(key="eco_end").set_value("Kaunas")
            app.button(key="eco_calculate_route").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "23.09 kg CO₂e")
            self.assertEqual(app.session_state["eco_result"]["title"], "Vilnius, Lietuva → Kaunas, Lietuva")
            self.assertEqual(len(app.selectbox), 1)
            self.assertIn("Neįtraukti variantai (1)", [block.label for block in app.expander])
            self.assertFalse(any("šis atstumas ilgesnis" in node.value for node in app.markdown))
            app.text_input(key="eco_start").set_value("Klaipėda").run()
            self.assertTrue(any("ankstesnis" in warning.value for warning in app.warning))

    def test_train_calculated_without_manual_length(self):
        with patch("streamlit.secrets", {"GEOAPIFY_API_KEY": "test-key"}), \
                patch("eco_route.geoapify.GeoapifyClient", FakeClient), \
                patch("eco_route.journey.lookup_rail", return_value=Distance(103, "rail_gtfs", 3540, "timetable")):
            app = self.app()
            app.selectbox(key="eco_transport").set_value("rail").run()
            app.text_input(key="eco_start").set_value("Vilnius")
            app.text_input(key="eco_end").set_value("Kaunas")
            app.button(key="eco_calculate_route").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.metric[0].value.startswith("≈ "))
            self.assertIn("Traukinio kelias pagal VINTRA", " ".join(c.value for c in app.caption))
            self.assertEqual(len(app.metric), 3)
            self.assertFalse(app.number_input)
            self.assertFalse(app.dataframe)

    def test_passengers_only_for_car_and_hidden_count_does_not_affect_alternative(self):
        app = self.manual()
        app.number_input(key="eco_passengers").set_value(3).run()
        app.selectbox(key="eco_transport").set_value("bicycle").run()
        self.assertNotIn("eco_passengers", [widget.key for widget in app.number_input])
        app.button(key="eco_calculate_manual").click().run()
        captions = " ".join(c.value for c in app.caption)
        self.assertNotIn("žmonių automobilyje", captions)
        self.assertNotIn("RF:", captions)
        car = next(e for e in app.session_state["eco_result"]["estimates"] if e.mode == "car")
        self.assertAlmostEqual(car.co2e_kg, 20.99)

    def test_defaults_replace_settings_and_unnecessary_comments_are_removed(self):
        app = self.manual()
        self.assertFalse(app.checkbox)
        self.assertNotIn("Palyginimo nustatymai", [block.label for block in app.expander])
        text = " ".join(node.value for kind in (app.caption, app.info, app.warning, app.markdown) for node in kind)
        for removed in ("jūsų ribas", "Koeficientai daugiausia atspindi", "Nulis taikomas", "RF pasirinkimas"):
            self.assertNotIn(removed, text)
        result = app.session_state["eco_result"]
        flight = next(e for e in result["estimates"] if e.mode == "flight")
        self.assertAlmostEqual(flight.factor.total, 0.16415)
        excluded = [e for e in result["estimates"] if e.co2e_kg is None]
        self.assertEqual({e.mode for e in excluded}, {"walk", "bicycle"})
        self.assertTrue(all(e.excluded_by_distance for e in excluded))
        self.assertFalse(any("Neįtraukti variantai" in block.label for block in app.expander))
