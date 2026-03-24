"""Unit tests for registration anti-bot rate limiter helpers."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

_reg_dir = Path(__file__).resolve().parent.parent
if str(_reg_dir) not in sys.path:
    sys.path.insert(0, str(_reg_dir))

import app as reg_app  # noqa: E402


class TestRegistrationRateLimit(unittest.TestCase):
    def setUp(self):
        reg_app._reset_registration_rate_limit_state_for_tests()

    def test_ip_minute_limit_blocks_after_threshold(self):
        now = 1000.0
        key = "reg:ip:min:127.0.0.1"
        for _ in range(5):
            ok, retry = reg_app._rl_hit_limit(key, limit=5, window_s=60, now_ts=now)
            self.assertTrue(ok)
            self.assertEqual(retry, 0)
        ok, retry = reg_app._rl_hit_limit(key, limit=5, window_s=60, now_ts=now + 0.1)
        self.assertFalse(ok)
        self.assertGreaterEqual(retry, 1)

    def test_window_expires_and_allows_again(self):
        now = 2000.0
        key = "reg:email:day:test@example.com"
        ok, _ = reg_app._rl_hit_limit(key, limit=1, window_s=10, now_ts=now)
        self.assertTrue(ok)
        ok, _ = reg_app._rl_hit_limit(key, limit=1, window_s=10, now_ts=now + 1)
        self.assertFalse(ok)
        ok, _ = reg_app._rl_hit_limit(key, limit=1, window_s=10, now_ts=now + 11)
        self.assertTrue(ok)

    def test_face_fingerprint_stable_for_close_float_noise(self):
        v = np.zeros(128, dtype=np.float64)
        v[0] = 1.23456
        v2 = v.copy()
        v2[0] = 1.23461  # rounds to same 3dp bucket
        f1 = reg_app._face_fingerprint(v)
        f2 = reg_app._face_fingerprint(v2)
        self.assertEqual(f1, f2)

    def test_email_normalization(self):
        self.assertEqual(reg_app._norm_email("  User@Example.COM "), "user@example.com")


if __name__ == "__main__":
    unittest.main()
