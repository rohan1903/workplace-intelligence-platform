import base64
import json
import os
import sys
import importlib.util
import unittest
import unittest.mock
from pathlib import Path
from datetime import datetime, timedelta

import cv2
import numpy as np


def load_gate_app_module():
    """
    Load gate/app.py as a uniquely-named module to avoid name collisions with other Flask apps.
    """
    gate_dir = Path(__file__).resolve().parents[1]
    app_path = gate_dir / "app.py"

    # Ensure mock mode before module execution.
    os.environ["USE_MOCK_DATA"] = "True"
    os.environ["AUTH_MODE"] = os.environ.get("AUTH_MODE", "hybrid")
    # Avoid needing to sleep between check-in and check-out in edge-case tests.
    os.environ["CHECKIN_COOLDOWN_SECONDS"] = os.environ.get("CHECKIN_COOLDOWN_SECONDS", "0")

    # gate/app.py uses `from qr_module import ...` (non-package import),
    # so gate/ must be on sys.path for module execution to succeed.
    sys.path.insert(0, str(gate_dir))

    spec = importlib.util.spec_from_file_location("gate_app_mock_tests", str(app_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load spec for {app_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GateEdgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = load_gate_app_module()
        cls.client = cls.gate.app.test_client()

    def setUp(self):
        # Reset in-memory DB state for each test.
        self.gate.db_ref = self.gate.InMemoryDBRef(self.gate.build_mock_gate_data())

    def _get_visit(self, visitor_id: str, visit_id: str):
        visit = self.gate.db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}").get()
        self.assertIsNotNone(visit, f"Missing visit {visitor_id}/{visit_id}")
        return visit

    def _post_mock_auth(self, mock_face_id: str, qr_data: str | None):
        payload = {"mock_face_id": mock_face_id}
        if qr_data is not None:
            payload["qr_data"] = qr_data
        resp = self.client.post("/mock_auth", json=payload)
        self.assertEqual(resp.status_code, 200)
        return resp.get_json() or {}

    def test_wrong_face_for_qr_denied_but_qr_still_valid(self):
        v1 = "visitor_demo_1"
        v2 = "visitor_demo_2"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        res = self._post_mock_auth(mock_face_id=v2, qr_data=qr_payload)
        self.assertEqual(res.get("status"), "denied")
        self.assertIn("do not match", res.get("message", "").lower())

        qr_state = self._get_visit(v1, visit_id).get("qr_state", {})
        self.assertEqual(qr_state.get("status"), self.gate.QR_UNUSED)

    def test_stolen_qr_invalidated_on_face_only_checkout(self):
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        # Check-in with QR.
        res1 = self._post_mock_auth(mock_face_id=v1, qr_data=qr_payload)
        self.assertEqual(res1.get("status"), "granted")
        self.assertIn("check-in", res1.get("message", "").lower())

        # Checkout without QR (face-only).
        res2 = self._post_mock_auth(mock_face_id=v1, qr_data=None)
        self.assertEqual(res2.get("status"), "checked_out")
        self.assertIn("QR invalidated", res2.get("message", ""))

        qr_state = self._get_visit(v1, visit_id).get("qr_state", {})
        self.assertEqual(qr_state.get("status"), self.gate.QR_INVALIDATED)
        self.assertIn("possible lost", qr_state.get("invalidated_reason", ""))

    def test_qr_replay_denied_after_checkout_used(self):
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        # Check-in (QR).
        res1 = self._post_mock_auth(mock_face_id=v1, qr_data=qr_payload)
        self.assertEqual(res1.get("status"), "granted")

        # Advance QR scan time so the next scan isn't blocked by QR_SCAN_COOLDOWN_SECONDS.
        past_str = (datetime.now() - timedelta(seconds=61)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}/qr_state").update(
            {"checkin_scan_time": past_str}
        )

        # Check-out (QR again).
        res2 = self._post_mock_auth(mock_face_id=v1, qr_data=qr_payload)
        self.assertEqual(res2.get("status"), "checked_out")

        # Replay attempt (QR a third time) must fail QR validation.
        res3 = self._post_mock_auth(mock_face_id=v1, qr_data=qr_payload)
        self.assertEqual(res3.get("status"), "denied")
        self.assertIn("QR invalid:", res3.get("message", ""))

    def test_expired_qr_denied(self):
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        visit = self._get_visit(v1, visit_id)
        token = visit.get("qr_token")
        self.assertTrue(token, "Missing stored qr_token in mock data")

        expired_payload = json.dumps(
            {"v": v1, "i": visit_id, "k": token, "e": "2000-01-01 00:00:00"},
            separators=(",", ":"),
        )

        res = self._post_mock_auth(mock_face_id=v1, qr_data=expired_payload)
        self.assertEqual(res.get("status"), "denied")
        self.assertIn("QR invalid:", res.get("message", ""))

    def _minimal_jpeg_data_url(self):
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        self.assertTrue(ok)
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

    def test_checkout_wrong_face_correct_qr_denied_when_twin_set_excludes_qr_owner(self):
        """
        QR disambiguation only applies when the QR owner is in the ambiguous top pair from
        detect_twin. If the face matches two other visitors but not the QR owner, deny.
        """
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        past_ci = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "checked_in", "check_in_time": past_ci}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_2", "distance": 0.50, "name": "Other", "blacklisted": False},
            {
                "visitor_id": "visitor_not_qr_owner",
                "distance": 0.51,
                "name": "Other2",
                "blacklisted": False,
            },
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), unittest.mock.patch.object(
            self.gate, "get_face_embedding", return_value=fake_emb
        ):
            resp = self.client.post(
                "/checkin_verify_and_log",
                json={
                    "image": self._minimal_jpeg_data_url(),
                    "qr_data": qr_payload,
                    "action": "checkout",
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("status"), "denied")
        self.assertIn("do not match", data.get("message", "").lower())

    def test_checkin_twin_ambiguity_qr_disambiguates_when_owner_not_geometric_best(self):
        """
        Under twin-style ambiguity (weak top match, #1 and #2 within 0.08), the QR holder
        may not be the geometric #1 (e.g. identical twin or duplicate face enrollment).
        We accept the QR when its owner is in the ambiguous pair so checkout/check-in works.
        Tradeoff: a lookalike with someone else's QR in the same ambiguity band cannot be
        distinguished from the legitimate twin case using face distance alone.
        """
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "approved", "visit_approved": True}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_2", "distance": 0.50, "name": "Diya", "blacklisted": False},
            {"visitor_id": "visitor_demo_1", "distance": 0.51, "name": "Aarav", "blacklisted": False},
        ]
        fake_emb = [0.02] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), unittest.mock.patch.object(
            self.gate, "get_face_embedding", return_value=fake_emb
        ):
            resp = self.client.post(
                "/checkin_verify_and_log",
                json={
                    "image": self._minimal_jpeg_data_url(),
                    "qr_data": qr_payload,
                    "action": "checkin",
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("status"), "granted")

    def test_checkout_twin_ambiguity_denied_when_owner_not_geometric_best(self):
        """At checkout, ambiguous twin cases are denied even if QR owner is in top pair."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]
        past_ci = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "checked_in", "check_in_time": past_ci}
        )
        past_scan = (datetime.now() - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}/qr_state").update(
            {"status": "CHECKIN_USED", "scan_count": 1, "checkin_scan_time": past_scan}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_2", "distance": 0.50, "name": "Diya", "blacklisted": False},
            {"visitor_id": "visitor_demo_1", "distance": 0.51, "name": "Aarav", "blacklisted": False},
        ]
        fake_emb = [0.02] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), unittest.mock.patch.object(
            self.gate, "get_face_embedding", return_value=fake_emb
        ):
            resp = self.client.post(
                "/checkin_verify_and_log",
                json={
                    "image": self._minimal_jpeg_data_url(),
                    "qr_data": qr_payload,
                    "action": "checkout",
                },
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json() or {}
        self.assertEqual(data.get("status"), "denied")

    # ── Wrong face + correct QR: single-match (no twin) ──────────────────
    def test_wrong_face_correct_qr_denied_single_match(self):
        """Wrong face best-matches a DIFFERENT visitor than the QR owner → mismatch."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        fake_matches = [
            {"visitor_id": "visitor_demo_2", "distance": 0.35, "name": "Diya", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkin",
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "denied")
        self.assertIn("do not match", data["message"])

    def test_wrong_face_correct_qr_denied_checkout_single_match(self):
        """Same as above but for checkout."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]
        past_ci = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "checked_in", "check_in_time": past_ci}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_2", "distance": 0.40, "name": "Diya", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkout",
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "denied")
        self.assertIn("do not match", data["message"].lower())

    # ── Unregistered face + correct QR ─────────────────────────────────
    def test_unregistered_face_correct_qr_denied(self):
        """Face matches NO visitor → denied even with a valid QR."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=[]), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkin",
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "denied")
        msg = (data.get("message") or "").lower()
        self.assertTrue(
            "no match found" in msg or "face not recognized" in msg or "incorrect face" in msg,
            msg=f"Unexpected denial message: {data.get('message')!r}",
        )

    # ── Hybrid mode requires QR (no action=auto bypass) ────────────────
    def test_hybrid_mode_denies_face_only_auto_action(self):
        """In hybrid mode, face-only (no QR) must be denied even with action=auto."""
        fake_matches = [
            {"visitor_id": "visitor_demo_1", "distance": 0.30, "name": "Aarav", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "action": "auto",
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "denied")
        self.assertIn("QR", data["message"])

    def test_hybrid_mode_denies_face_only_no_action(self):
        """In hybrid mode, face-only (no QR, no action) must be denied."""
        fake_matches = [
            {"visitor_id": "visitor_demo_1", "distance": 0.30, "name": "Aarav", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "denied")
        self.assertIn("QR", data["message"])

    # ── Correct face + correct QR succeeds ─────────────────────────────
    def test_correct_face_correct_qr_checkin_granted(self):
        """Positive case: matching face + matching QR → check-in granted."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "approved", "visit_approved": True}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_1", "distance": 0.30, "name": "Aarav", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkin",
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "granted")

    def test_correct_face_correct_qr_checkout_granted(self):
        """Positive case: matching face + matching QR → checkout granted."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]
        past_ci = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "checked_in", "check_in_time": past_ci}
        )
        past_scan = (datetime.now() - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}/qr_state").update(
            {"status": "CHECKIN_USED", "scan_count": 1, "checkin_scan_time": past_scan}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_1", "distance": 0.28, "name": "Aarav", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkout",
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "checked_out")

    # ── Twin: QR agrees with geometric best → allowed ──────────────────
    def test_twin_qr_agrees_with_best_match_allowed(self):
        """Twin ambiguity where QR confirms the geometric best match → granted."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "approved", "visit_approved": True}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_1", "distance": 0.50, "name": "Aarav", "blacklisted": False},
            {"visitor_id": "visitor_demo_2", "distance": 0.51, "name": "Diya", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkin",
            })
        data = resp.get_json() or {}
        self.assertEqual(data["status"], "granted")

    # ── QR mismatch behavior by phase ──────────────────────────────────
    def test_qr_not_invalidated_after_wrong_face_during_checkin(self):
        """At check-in phase, wrong face should deny but preserve QR for the rightful owner."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        fake_matches = [
            {"visitor_id": "visitor_demo_2", "distance": 0.35, "name": "Diya", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkin",
            })

        qr_state = self._get_visit(v1, visit_id).get("qr_state", {})
        self.assertEqual(qr_state["status"], self.gate.QR_UNUSED)

    def test_qr_not_invalidated_after_wrong_face_during_checkout(self):
        """Wrong face at checkout denies access but keeps QR valid for retry with correct face."""
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]
        past_ci = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.gate.db_ref.child(f"visitors/{v1}/visits/{visit_id}").update(
            {"status": "checked_in", "check_in_time": past_ci}
        )

        fake_matches = [
            {"visitor_id": "visitor_demo_2", "distance": 0.35, "name": "Diya", "blacklisted": False},
        ]
        fake_emb = [0.01] * 128

        with unittest.mock.patch.object(self.gate, "find_all_face_matches", return_value=fake_matches), \
             unittest.mock.patch.object(self.gate, "get_face_embedding", return_value=fake_emb):
            resp = self.client.post("/checkin_verify_and_log", json={
                "image": self._minimal_jpeg_data_url(),
                "qr_data": qr_payload,
                "action": "checkout",
            })

        self.assertEqual((resp.get_json() or {}).get("status"), "denied")
        qr_state = self._get_visit(v1, visit_id).get("qr_state", {})
        self.assertNotEqual(qr_state.get("status"), self.gate.QR_INVALIDATED)
        self.assertEqual(qr_state.get("status"), self.gate.QR_UNUSED)

    # ── Original tests ─────────────────────────────────────────────────
    def test_blacklisted_visitor_denied_and_qr_invalidated(self):
        v1 = "visitor_demo_1"
        visit_id = "visit_demo_1"
        qr_payload = self._get_visit(v1, visit_id)["qr_payload"]

        self.gate.db_ref.child(f"visitors/{v1}/basic_info").update({"blacklisted": "yes"})

        res = self._post_mock_auth(mock_face_id=v1, qr_data=qr_payload)
        self.assertEqual(res.get("status"), "denied")
        self.assertIn("blacklisted", res.get("message", "").lower())

        qr_state = self._get_visit(v1, visit_id).get("qr_state", {})
        self.assertEqual(qr_state.get("status"), self.gate.QR_INVALIDATED)

    def test_feedback_form_validation(self):
        resp1 = self.client.get("/feedback_form")
        self.assertEqual(resp1.status_code, 400)

        resp2 = self.client.get("/feedback_form?visitor_id=does_not_exist")
        self.assertEqual(resp2.status_code, 404)

        resp3 = self.client.post(
            "/submit_feedback",
            data={"visitor_id": "visitor_demo_1", "feedback_text": ""},
        )
        self.assertEqual(resp3.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)

