import json
import math
import unittest
from unittest.mock import Mock

import requests

from eco_route.geoapify import (
    GeoapifyClient, GeoapifyError, Place, RequestLimiter, SessionCache, normalize_place,
)
from eco_route.journey import route_distances
from eco_route.calculations import Distance
from geopy.distance import great_circle


def response(data=None, status=200, body=None):
    result = Mock()
    result.status_code = status
    result.iter_content.return_value = [body if body is not None else json.dumps(data).encode()]
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def location(label="Vilnius", lon=25.28, lat=54.68):
    return {"features": [{"geometry": {"type": "Point", "coordinates": [lon, lat]},
                          "properties": {"formatted": label}}]}


def road_payload(distance=105000, units="meters", time=3600, geometry=None):
    return {"features": [{"properties": {"distance": distance, "distance_units": units, "time": time},
                          "geometry": geometry}]}


START = Place("Vilnius", 54.68, 25.28)
END = Place("Kaunas", 54.90, 23.90)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.cache = SessionCache()
        self.client = GeoapifyClient("private-test-key", self.cache, RequestLimiter(), session=self.session)

    def test_coordinate_order_search_normalization_and_cache(self):
        self.session.get.return_value = response(location())
        places = self.client.search("  Vilnius   Lithuania ")
        self.assertEqual(places[0].coords, (54.68, 25.28))
        self.client.search("vilnius lithuania")
        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual(self.session.get.call_args.kwargs["params"]["text"], "Vilnius Lithuania")
        self.assertEqual(self.session.get.call_args.kwargs["params"]["limit"], 1)

    def test_cache_separated_by_credentials(self):
        self.session.get.return_value = response(location())
        self.client.search("Vilnius")
        other = GeoapifyClient("another-key", self.cache, RequestLimiter(), session=self.session)
        other.search("Vilnius")
        self.assertEqual(self.session.get.call_count, 2)

    def test_meters_to_km_waypoints_and_route_cache(self):
        self.session.get.return_value = response(road_payload())
        self.assertEqual(self.client.route_km(START, END, "drive"), 105)
        self.assertEqual(self.client.route_km(START, END, "drive"), 105)
        kwargs = self.session.get.call_args.kwargs
        self.assertEqual(kwargs["params"]["waypoints"], "54.68,25.28|54.9,23.9")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["params"]["units"], "metric")
        self.assertEqual(self.session.get.call_count, 1)

    def test_invalid_route_payloads(self):
        for data in ({}, {"features": []}, {"features": [None]},
                     road_payload(-1), road_payload("100"), road_payload(units="miles"), road_payload(0)):
            with self.subTest(data=data):
                self.session.get.return_value = response(data)
                with self.assertRaises(GeoapifyError):
                    self.client.route_km(START, END, "drive")

    def test_time_and_geometry_are_returned_without_an_extra_request(self):
        self.session.get.return_value = response(road_payload(geometry={
            "type": "MultiLineString", "coordinates": [[[25.28, 54.68], [24.5, 54.8], [23.9, 54.9]]] }))
        route = self.client.route(START, END, "drive")
        self.assertEqual(route.duration_seconds, 3600)
        self.assertEqual(route.geometry[0], (25.28, 54.68))
        self.assertEqual(route.geometry[-1], (23.9, 54.9))
        self.client.route_km(START, END, "drive")
        self.assertEqual(self.session.get.call_count, 1)

    def test_bad_geometry_or_time_does_not_hide_valid_distance(self):
        self.session.get.return_value = response(road_payload(time="invalid", geometry={
            "type": "LineString", "coordinates": [[25, 54], [900, 95]]}))
        route = self.client.route(START, END, "drive")
        self.assertEqual(route.km, 105)
        self.assertIsNone(route.duration_seconds)
        self.assertEqual(route.geometry, ())

    def test_invalid_locations(self):
        for data in ({}, {"features": []}, {"features": None}, location(lat=100), location(lon=math.nan)):
            with self.subTest(data=data):
                self.session.get.return_value = response(data)
                with self.assertRaises(GeoapifyError):
                    self.client.search("Vilnius")

    def test_timeout_and_network_errors_never_expose_key(self):
        for error in (requests.Timeout("https://secret?apiKey=private-test-key"),
                      requests.ConnectionError("private-test-key")):
            self.session.get.side_effect = error
            with self.assertRaises(GeoapifyError) as caught:
                self.client.search("Vilnius")
            self.assertNotIn("private-test-key", str(caught.exception))
            self.assertNotIn("https://", str(caught.exception))

    def test_http_errors_and_no_retry_after_rate_or_auth_error(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                session = Mock()
                session.get.return_value = response(status=status)
                client = GeoapifyClient("key", SessionCache(), RequestLimiter(), session=session)
                for _ in range(2):
                    with self.assertRaises(GeoapifyError):
                        client.search("Vilnius")
                self.assertEqual(session.get.call_count, 1)
        for status in (302, 400, 500, 503):
            self.session.get.return_value = response(status=status)
            with self.assertRaises(GeoapifyError):
                self.client.search("Vilnius")

    def test_invalid_json_and_large_response(self):
        for body in (b"invalid", b"[]", b"x" * 2_000_001):
            self.session.get.return_value = response(body=body)
            with self.assertRaises(GeoapifyError):
                self.client.search("Vilnius")

    def test_expired_budget_does_not_send_request(self):
        now = [0]
        client = GeoapifyClient("key", SessionCache(), RequestLimiter(), session=self.session,
                               clock=lambda: now[0], budget_seconds=5)
        now[0] = 6
        with self.assertRaises(GeoapifyError):
            client.search("Vilnius")
        self.session.get.assert_not_called()

    def test_cache_expiry_eviction_and_session_isolation(self):
        now = [0]
        cache = SessionCache(max_entries=2, clock=lambda: now[0])
        cache.put("a", 1, 2)
        cache.put("b", 2, 100)
        cache.put("c", 3, 100)
        self.assertIsNone(cache.get("a"))
        self.assertIsNone(SessionCache().get("b"))
        now[0] = 101
        self.assertIsNone(cache.get("b"))
        self.assertIsNone(cache.get("c"))

    def test_server_limit_shared_and_expires(self):
        now = [0]
        limiter = RequestLimiter(per_minute=1, clock=lambda: now[0])
        limiter.take()
        with self.assertRaises(GeoapifyError):
            limiter.take()
        now[0] = 60
        limiter.take()

    def test_input_rejection_before_requests(self):
        for text in (" ", "a" * 301, "a\x00b"):
            with self.assertRaises(ValueError):
                normalize_place(text)
        with self.assertRaises(GeoapifyError):
            GeoapifyClient("", self.cache, RequestLimiter())


class JourneyTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        no_rail = patch("eco_route.journey.lookup_rail", return_value=None)
        no_rail.start()
        self.addCleanup(no_rail.stop)

    def test_selected_route_survives_partial_failure_and_no_geocoding(self):
        client = Mock()
        client.route.side_effect = [Distance(110, "road"), GeoapifyError("Bus unavailable")]
        distances, failures = route_distances(client, START, END, "car")
        self.assertEqual(distances["car"].km, 110)
        self.assertIn("bus", failures)
        self.assertEqual(distances["rail"].kind, "rail_estimate")
        client.search.assert_not_called()
        self.assertEqual(client.route.call_args_list[0].args[2], "drive")
        self.assertEqual(distances["flight"].kind, "air_scenario")

    def test_same_coordinates_need_no_requests(self):
        client = Mock()
        distances, failures = route_distances(client, START, START, "car")
        self.assertEqual({d.km for d in distances.values()}, {0})
        self.assertFalse(failures)
        client.route.assert_not_called()

    def test_train_is_estimated_automatically_and_short_modes_are_excluded(self):
        client = Mock()
        client.route.return_value = Distance(110, "road")
        distances, failures = route_distances(client, START, END, "rail")
        self.assertAlmostEqual(distances["rail"].km, great_circle(START.coords, END.coords).km * 1.35)
        self.assertEqual(distances["rail"].kind, "rail_estimate")
        self.assertIn("walk", failures)
        self.assertIn("10 km", failures["walk"].message)
        self.assertIn("35 km", failures["bicycle"].message)
        self.assertTrue(failures["walk"].excluded_by_distance)
        self.assertNotIn("rail", failures)

    def test_automatic_train_survives_road_api_failure(self):
        client = Mock()
        client.route.side_effect = GeoapifyError("Service unavailable")
        distances, failures = route_distances(client, START, END, "rail")
        self.assertGreater(distances["rail"].km, distances["flight"].km)
        self.assertNotIn("rail", failures)
        self.assertIn("car", failures)

    def test_local_rail_distance_and_time_replace_fallback(self):
        client = Mock()
        client.route.return_value = Distance(110, "road")
        local = Distance(103, "rail_gtfs", 3540, "timetable")
        distances, _ = route_distances(client, START, END, "rail", rail_lookup=lambda a,b: local)
        self.assertIs(distances["rail"], local)

    def test_unavailable_snapshot_preserves_automatic_estimate(self):
        client = Mock()
        client.route.return_value = Distance(110, "road")
        broken = Mock(side_effect=OSError("missing file"))
        distances, _ = route_distances(client, START, END, "rail", rail_lookup=broken)
        self.assertEqual(distances["rail"].kind, "rail_estimate")
