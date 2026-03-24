"""
Admin dashboard integration tests with USE_MOCK_DATA=True (no Firebase).

Run from the Admin directory:
    python -m unittest tests.test_admin_dashboard_mock -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_admin_dir = Path(__file__).resolve().parent.parent

# Match a normal `python app.py` run from Admin/
os.chdir(_admin_dir)
if str(_admin_dir) not in sys.path:
    sys.path.insert(0, str(_admin_dir))

os.environ["USE_MOCK_DATA"] = "True"

import app as admin_app  # noqa: E402


class AdminDashboardMockTests(unittest.TestCase):
    """Flask test_client checks against mock-backed routes and APIs."""

    @classmethod
    def setUpClass(cls):
        admin_app.USE_MOCK_DATA = True
        cls.app = admin_app.app
        cls.app.testing = True

    def setUp(self):
        admin_app.USE_MOCK_DATA = True
        admin_app._MOCK_BLACKLIST_STATE.clear()
        admin_app._mock_rooms_cache = None
        admin_app._MOCK_VISITORS_BASE = None
        admin_app._MOCK_EMPLOYEES_CACHE = None

    def test_get_home(self):
        with self.app.test_client() as c:
            r = c.get("/")
            self.assertEqual(r.status_code, 200)
            html = r.get_data(as_text=True)
            self.assertIn("Visitors Management", html)
            self.assertIn("Dashboard", html)

    def test_get_visitors(self):
        with self.app.test_client() as c:
            r = c.get("/visitors")
            self.assertEqual(r.status_code, 200)

    def test_get_dashboard(self):
        with self.app.test_client() as c:
            r = c.get("/dashboard")
            self.assertEqual(r.status_code, 200)

    def test_get_blacklist_page(self):
        with self.app.test_client() as c:
            r = c.get("/blacklist")
            self.assertEqual(r.status_code, 200)

    def test_get_rooms_page(self):
        with self.app.test_client() as c:
            r = c.get("/rooms")
            self.assertEqual(r.status_code, 200)

    def test_get_employees(self):
        with self.app.test_client() as c:
            r = c.get("/employees")
            self.assertEqual(r.status_code, 200)

    def test_get_feedback_analysis(self):
        with self.app.test_client() as c:
            r = c.get("/feedback_analysis")
            self.assertEqual(r.status_code, 200)

    def test_api_occupancy(self):
        with self.app.test_client() as c:
            r = c.get("/api/occupancy")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIsInstance(data, dict)
            self.assertIn("current_occupancy", data)
            self.assertIn("timestamp", data)
            self.assertIsInstance(data["current_occupancy"], (int, float))

    def test_api_occupancy_over_time(self):
        with self.app.test_client() as c:
            r = c.get("/api/occupancy_over_time")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIsInstance(data, dict)
            self.assertIn("occupancy_over_time_last24", data)
            self.assertIn("timestamp", data)
            occ = data["occupancy_over_time_last24"]
            self.assertIn("labels", occ)
            self.assertIn("data", occ)

    def test_api_rooms_list_has_defaults(self):
        with self.app.test_client() as c:
            r = c.get("/api/rooms/list")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIsInstance(data, dict)
            for key in ("room_1", "room_2", "room_3"):
                self.assertIn(key, data, msg="Expected default mock room ids in list")

    def test_api_rooms_suggest(self):
        with self.app.test_client() as c:
            r = c.get("/api/rooms/suggest?count=5")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIn("suggestions", data)
            self.assertIsInstance(data["suggestions"], list)

    def test_api_rooms_crud(self):
        body = {
            "name": "Unit Test Room",
            "capacity": 99,
            "floor": "9",
            "amenities": "Test",
        }
        with self.app.test_client() as c:
            r = c.post(
                "/api/rooms",
                data=json.dumps(body),
                content_type="application/json",
            )
            self.assertEqual(r.status_code, 200)
            created = r.get_json()
            self.assertTrue(created.get("success"))
            room_id = created.get("room_id")
            self.assertTrue(room_id)

            listed = c.get("/api/rooms/list").get_json()
            self.assertIn(room_id, listed)
            self.assertEqual(listed[room_id].get("name"), "Unit Test Room")

            r2 = c.put(
                f"/api/rooms/{room_id}",
                data=json.dumps({**body, "name": "Unit Test Room Updated"}),
                content_type="application/json",
            )
            self.assertEqual(r2.status_code, 200)
            self.assertTrue(r2.get_json().get("success"))
            listed2 = c.get("/api/rooms/list").get_json()
            self.assertEqual(listed2[room_id].get("name"), "Unit Test Room Updated")

            r3 = c.delete(f"/api/rooms/{room_id}")
            self.assertEqual(r3.status_code, 200)
            self.assertTrue(r3.get_json().get("success"))
            listed3 = c.get("/api/rooms/list").get_json()
            self.assertNotIn(room_id, listed3)

    def test_presentation_demo_rooms_not_editable(self):
        demo_ids = list(admin_app.PRESENTATION_ROOM_IDS)
        if not demo_ids:
            self.skipTest("presentation_demo.PRESENTATION_ROOM_IDS empty (import path)")
        rid = demo_ids[0]
        payload = json.dumps(
            {"name": "Hacked", "capacity": 1, "floor": "0", "amenities": ""}
        )
        with self.app.test_client() as c:
            r_put = c.put(
                f"/api/rooms/{rid}",
                data=payload,
                content_type="application/json",
            )
            self.assertEqual(r_put.status_code, 403)
            self.assertIn("message", r_put.get_json() or {})

            r_del = c.delete(f"/api/rooms/{rid}")
            self.assertEqual(r_del.status_code, 403)

    def test_blacklist_toggle_api(self):
        with self.app.test_client() as c:
            r1 = c.post(
                "/blacklist/visitor_1",
                data=json.dumps({"blacklisted": True, "reason": "test"}),
                content_type="application/json",
            )
            self.assertEqual(r1.status_code, 200)
            self.assertTrue(r1.get_json().get("success"))

            r2 = c.post(
                "/blacklist/visitor_1",
                data=json.dumps({"blacklisted": False, "reason": "test"}),
                content_type="application/json",
            )
            self.assertEqual(r2.status_code, 200)
            self.assertTrue(r2.get_json().get("success"))

    def test_blacklist_edit_reason_keeps_single_record(self):
        with self.app.test_client() as c:
            r1 = c.post(
                "/blacklist/visitor_1",
                data=json.dumps({"blacklisted": True, "reason": "first"}),
                content_type="application/json",
            )
            self.assertEqual(r1.status_code, 200)
            state1 = dict(admin_app._MOCK_BLACKLIST_STATE.get("visitor_1") or {})
            self.assertTrue(state1.get("blacklisted"))
            self.assertEqual(state1.get("reason"), "first")
            ts1 = state1.get("blacklisted_at")
            self.assertTrue(ts1)

            # Edit reason while remaining blacklisted -> should update in-place, not duplicate/reset timestamp.
            r2 = c.post(
                "/blacklist/visitor_1",
                data=json.dumps({"blacklisted": True, "reason": "updated"}),
                content_type="application/json",
            )
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(len(admin_app._MOCK_BLACKLIST_STATE), 1)
            state2 = dict(admin_app._MOCK_BLACKLIST_STATE.get("visitor_1") or {})
            self.assertEqual(state2.get("reason"), "updated")
            self.assertEqual(state2.get("blacklisted_at"), ts1)

    def test_blacklist_unknown_visitor_rejected(self):
        with self.app.test_client() as c:
            r = c.post(
                "/blacklist/visitor_does_not_exist",
                data=json.dumps({"blacklisted": True, "reason": "x"}),
                content_type="application/json",
            )
            self.assertEqual(r.status_code, 404)
            body = r.get_json() or {}
            self.assertFalse(body.get("success", True))

    def test_mock_data_toggle_api(self):
        with self.app.test_client() as c:
            r = c.get("/api/mock_data")
            self.assertEqual(r.status_code, 200)
            body = r.get_json()
            self.assertIn("mock", body)

            r = c.post("/api/mock_data", data=json.dumps({"mock": True}), content_type="application/json")
            self.assertEqual(r.status_code, 200)
            body = r.get_json()
            self.assertTrue(body["success"])
            self.assertTrue(body["mock"])


if __name__ == "__main__":
    unittest.main()
