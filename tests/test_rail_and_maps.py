from datetime import date
import json
import unittest

from eco_route.calculations import Distance, compare
from eco_route.geoapify import Place
from eco_route.presentation import duration_chart_spec, format_duration, map_deck
from eco_route.rail import lookup_rail, service_active


class RailTests(unittest.TestCase):
    def test_vilnius_kaunas_uses_route_shape_and_schedule(self):
        route = lookup_rail(Place("Vilnius",54.6872,25.2797), Place("Kaunas",54.8985,23.9036), date(2026,11,15))
        self.assertEqual(route.kind, "rail_gtfs")
        self.assertTrue(101 < route.km < 106)
        self.assertTrue(50*60 < route.duration_seconds < 100*60)
        self.assertGreater(len(route.geometry), 100)
        self.assertEqual(route.route_label, "Vilnius → Kaunas")

    def test_long_route_follows_railway_not_direct_line(self):
        route = lookup_rail(Place("Vilnius",54.6872,25.2797), Place("Klaipėda",55.7033,21.1443), date(2026,11,15))
        self.assertTrue(370 < route.km < 380)
        self.assertTrue(3*3600 < route.duration_seconds < 5*3600)

    def test_expired_schedule_and_distant_places_fall_back(self):
        a, b = Place("Vilnius",54.6872,25.2797), Place("Kaunas",54.8985,23.9036)
        self.assertIsNone(lookup_rail(a,b,date(2040,1,1)))
        self.assertIsNone(lookup_rail(a,b,date(2026,12,31)))
        self.assertIsNone(lookup_rail(Place("Paris",48.86,2.35),b,date(2026,11,15)))
        self.assertIsNone(lookup_rail(a,a,date(2026,11,15)))

    def test_calendar_exceptions_override_weekdays(self):
        data={"exceptions":{"x":{"20261115":2,"20261116":1}},
              "calendars":{"x":{"start":"20261101","end":"20261130","days":[0,0,0,0,0,0,1]}}}
        self.assertFalse(service_active(data,"x",date(2026,11,15)))
        self.assertTrue(service_active(data,"x",date(2026,11,16)))
        self.assertFalse(service_active(data,"x",date(2026,11,17)))


class MapAndTimeTests(unittest.TestCase):
    def test_map_frames_both_places_and_draws_only_available_geometry(self):
        a, b=Place("A",54.68,25.28),Place("B",54.9,23.9)
        route=Distance(110,"road",3600,"routing",((25.28,54.68),(24.5,54.8),(23.9,54.9)))
        deck=map_deck(a,b,route)
        self.assertLess(deck.initial_view_state.zoom,10)
        self.assertEqual(deck.layers[0].type,"PathLayer")
        no_path=map_deck(a,b,Distance(100,"rail_estimate"))
        self.assertNotIn("PathLayer",[layer.type for layer in no_path.layers])
        serialized = json.loads(deck.to_json())
        self.assertEqual(serialized["layers"][0]["widthUnits"], "pixels")
        self.assertEqual(serialized["layers"][1]["radiusUnits"], "pixels")
        self.assertEqual(serialized["layers"][2]["sizeUnits"], "pixels")

    def test_zero_distance_map_remains_valid(self):
        point=Place("A",54.68,25.28)
        deck=map_deck(point,point,Distance(0,"same_point",0))
        self.assertLessEqual(deck.initial_view_state.zoom,14)

    def test_flight_without_route_geometry_draws_a_great_circle(self):
        start, end = Place("Vilnius",54.68,25.28), Place("London",51.51,-0.13)
        deck = map_deck(start,end,Distance(1700,"air_scenario"))
        layer = json.loads(deck.to_json())["layers"][0]
        self.assertEqual(layer["@@type"],"ArcLayer")
        self.assertTrue(layer["greatCircle"])
        self.assertEqual(layer["getHeight"],0)
        self.assertEqual(layer["widthUnits"],"pixels")
        self.assertEqual(layer["data"][0]["source"],[25.28,54.68])
        self.assertEqual(layer["data"][0]["target"],[-0.13,51.51])

    def test_duration_format_and_chart_use_time_not_emissions(self):
        self.assertEqual(format_duration(3600+30*60),"≈ 1 val. 30 min.")
        self.assertEqual(format_duration(0),"0 min.")
        self.assertEqual(format_duration(None),"Nėra duomenų")
        results=compare({"car":Distance(100,"road",7200,"routing"),
                         "rail":Distance(100,"rail_gtfs",3600,"timetable"),
                         "flight":Distance(100,"air_scenario")},"car")
        spec=duration_chart_spec(results,"car")
        self.assertEqual([r["minutes"] for r in spec["data"]["values"]],[60,120])
        self.assertEqual(spec["encoding"]["x"]["field"],"minutes")
