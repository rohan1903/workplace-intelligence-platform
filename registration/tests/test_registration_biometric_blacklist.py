"""Unit tests for registration biometric blacklist cross-check.

Run from repo root:
  python -m unittest registration.tests.test_registration_biometric_blacklist -v
Or from registration/:
  python -m unittest tests.test_registration_biometric_blacklist -v
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

_reg_dir = Path(__file__).resolve().parent.parent
if str(_reg_dir) not in sys.path:
    sys.path.insert(0, str(_reg_dir))

import app as reg_app  # noqa: E402


def _emb_str(vec):
    v = np.asarray(vec, dtype=np.float64).flatten()
    return " ".join(str(x) for x in v.tolist())


class TestRegistrationBiometricBlacklist(unittest.TestCase):
    def setUp(self):
        self.base = np.zeros(128, dtype=np.float64)
        self.base[0] = 1.0
        os.environ.setdefault("VERIFICATION_THRESHOLD", "0.65")

    def test_no_visitors_allows(self):
        db = MagicMock()
        db.child.return_value.get.return_value = {}
        deny, msg, reason = reg_app._registration_biometric_blacklist_block(self.base, db)
        self.assertFalse(deny)
        self.assertIsNone(msg)
        self.assertIsNone(reason)

    def test_blacklisted_identical_face_denied(self):
        db = MagicMock()
        db.child.return_value.get.return_value = {
            "bl1": {
                "basic_info": {
                    "embedding": _emb_str(self.base),
                    "blacklisted": "yes",
                    "blacklist_reason": "Test reason",
                    "name": "Blocked",
                }
            }
        }
        deny, msg, reason = reg_app._registration_biometric_blacklist_block(self.base, db)
        self.assertTrue(deny)
        self.assertEqual(msg, reg_app.MSG_BLACKLISTED)
        self.assertEqual(reason, "Test reason")

    def test_blacklisted_far_face_allowed(self):
        far = self.base.copy()
        far[0] = 10.0
        db = MagicMock()
        db.child.return_value.get.return_value = {
            "bl1": {
                "basic_info": {
                    "embedding": _emb_str(far),
                    "blacklisted": "yes",
                    "name": "Blocked",
                }
            }
        }
        deny, msg, _ = reg_app._registration_biometric_blacklist_block(self.base, db)
        self.assertFalse(deny)

    def test_non_blacklisted_closest_allows(self):
        db = MagicMock()
        db.child.return_value.get.return_value = {
            "ok1": {
                "basic_info": {
                    "embedding": _emb_str(self.base),
                    "blacklisted": "no",
                    "name": "Legit",
                }
            }
        }
        deny, msg, _ = reg_app._registration_biometric_blacklist_block(self.base, db)
        self.assertFalse(deny)

    def test_twin_ambiguity_blacklisted_vs_not_denied_neutral(self):
        """Best and second within TWIN_GAP with different blacklist flags -> ambiguous message."""
        live = np.zeros(128, dtype=np.float64)
        live[0] = 1.0
        # Perturb one dimension only so L2 gaps stay small (like verify_face twin tests).
        bl = live.copy()
        bl[0] += 0.03
        ok = live.copy()
        ok[0] += 0.06
        db = MagicMock()
        db.child.return_value.get.return_value = {
            "ok1": {
                "basic_info": {
                    "embedding": _emb_str(ok),
                    "blacklisted": "no",
                    "name": "OK",
                }
            },
            "bl1": {
                "basic_info": {
                    "embedding": _emb_str(bl),
                    "blacklisted": "yes",
                    "name": "Bad",
                }
            },
        }
        deny, msg, reason = reg_app._registration_biometric_blacklist_block(live, db)
        self.assertTrue(deny)
        self.assertEqual(msg, reg_app.MSG_REGISTRATION_FACE_AMBIGUOUS)
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
