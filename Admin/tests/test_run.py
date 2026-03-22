#!/usr/bin/env python3
"""Quick test script to check if the app can start. Run from admin/: python tests/test_run.py"""

import sys
from pathlib import Path

# Ensure admin is on path and cwd when running from admin/tests/
_admin_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_admin_dir))

print("Testing imports...")
try:
    from flask import Flask
    print("[OK] Flask imported successfully")
except ImportError as e:
    print(f"[FAIL] Flask import failed: {e}")
    print("   Install with: pip3 install Flask")
    sys.exit(1)

try:
    import pandas
    print("[OK] pandas imported successfully")
except ImportError as e:
    print(f"[WARN] pandas import failed: {e}")
    print("   Install with: pip3 install pandas")

try:
    from dotenv import load_dotenv
    print("[OK] python-dotenv imported successfully")
except ImportError as e:
    print(f"[WARN] python-dotenv import failed: {e}")
    print("   Install with: pip3 install python-dotenv")

print("\nTesting app.py import...")
try:
    import app
    print("[OK] app.py imported successfully")
    print("\n[OK] All checks passed! You can run: python app.py")
except Exception as e:
    print(f"[FAIL] Error importing app.py: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
