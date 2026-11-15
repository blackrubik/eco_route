import math
import unittest

from eco_route.calculations import (
    Distance, Factor, compare, emissions_kg, factor_for, lower_emission_options,
)
from eco_route.journey import scenario_distances
from eco_route.presentation import chart_spec


class CalculationTests(unittest.TestCase):
    def test_source_backed_examples(self):
        self.assertAlmostEqual(emissions_kg(factor_for("car"), 100), 20.990)
        self.assertAlmostEqual(emissions_kg(factor_for("car"), 100, 3), 20.990 / 3)
        self.assertAlmostEqual(emissions_kg(factor_for("rail"), 100), 3.989)
        self.assertAlmostEqual(emissions_kg(factor_for("bus"), 100), 12.8)

    def test_public_transport_not_divided_by_car_occupancy(self):
        for mode in ("bus", "rail", "flight", "walk", "bicycle"):
            with self.subTest(mode=mode):
                self.assertEqual(emissions_kg(factor_for(mode), 100, 1),
                                 emissions_kg(factor_for(mode), 100, 5))

    def test_flight_no_double_uplift(self):
        self.assertAlmostEqual(emissions_kg(factor_for("flight", True), 1000), 164.15)
        self.assertAlmostEqual(emissions_kg(factor_for("flight", False), 1000), 105.82)

    def test_invalid_distance_and_factor(self):
        for distance in (-1, math.nan, math.inf, "100", True, 10**1000):
            with self.subTest(distance=distance), self.assertRaises(ValueError):
                emissions_kg(factor_for("car"), distance)
        with self.assertRaises(ValueError):
            emissions_kg(Factor(-1, 0, True, "invalid", ()), 1)
        with self.assertRaises(ValueError):
            emissions_kg(Factor(10, 10, True, "overflow", ()), 1e308)

    def test_occupancy_validation(self):
        for passengers in (0, -1, 10, 2.5, True):
            with self.subTest(passengers=passengers), self.assertRaises(ValueError):
                emissions_kg(factor_for("car"), 100, passengers)

    def test_actual_route_limit_and_selected_exception(self):
        result = compare({"walk": Distance(10.1, "road"), "car": Distance(11, "road")}, "car")
        self.assertIsNone(result[0].co2e_kg)
        result = compare({"walk": Distance(10.1, "road")}, "walk")
        self.assertEqual(result[0].co2e_kg, 0)
        self.assertEqual(compare({"walk": Distance(10, "road")}, "car")[0].co2e_kg, 0)

    def test_comparison_uses_distance_not_only_factor(self):
        result = compare({"car": Distance(1, "road"), "rail": Distance(100, "manual")}, "car")
        self.assertEqual(lower_emission_options(result, "car"), ())

    def test_car_alternative_uses_same_occupancy(self):
        result = compare({"car": Distance(100, "road"), "bus": Distance(100, "bus_road")}, "bus", 5)
        self.assertEqual(lower_emission_options(result, "bus")[0].mode, "car")

    def test_zero_and_missing_do_not_create_savings(self):
        zero = compare(scenario_distances(0), "car")
        self.assertEqual(lower_emission_options(zero, "car"), ())
        missing = compare({}, "car")
        self.assertEqual(lower_emission_options(missing, "car"), ())
        self.assertEqual(chart_spec(missing, "car")["data"]["values"], [])

    def test_chart_keeps_zero_but_excludes_unknown_and_marks_selection(self):
        result = compare({"car": Distance(5, "road"), "walk": Distance(5, "road")}, "car")
        rows = chart_spec(result, "car")["data"]["values"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["co2e"], 0)
        self.assertTrue(rows[1]["selected"])
        self.assertIn("★", rows[1]["transport"])

    def test_chart_identifies_estimated_train_distance_without_table(self):
        result = compare({"rail": Distance(135, "rail_estimate"), "car": Distance(110, "road")}, "rail")
        spec = chart_spec(result, "rail")
        rail = next(row for row in spec["data"]["values"] if row["selected"])
        self.assertTrue(rail["transport"].startswith("≈ "))
        self.assertEqual(rail["distance_km"], 135)
        self.assertIn("distance_km", [item["field"] for item in spec["encoding"]["tooltip"]])
