#!/usr/bin/env python3
"""
One-time script: Delete ALL visitor data from Firebase Realtime Database.
Admin dashboard and Register_App will show no visitors after this.

Run from project root:
  python clear_firebase_visitors.py

Uses: Admin/firebase_credentials.json and FIREBASE_DATABASE_URL in Admin/.env
Leaves: employees, meeting_rooms, invitations (unchanged).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Admin"))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "Admin", ".env"))
except ImportError:
    pass

import firebase_admin
from firebase_admin import credentials, db


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    cred_path = os.path.join(base, "Admin", "firebase_credentials.json")
    if not os.path.exists(cred_path):
        print("ERROR: Admin/firebase_credentials.json not found.")
        sys.exit(1)

    database_url = os.environ.get("FIREBASE_DATABASE_URL", "").strip().rstrip("/")
    if not database_url:
        print("ERROR: FIREBASE_DATABASE_URL not set. Set it in Admin/.env")
        sys.exit(1)
    if not database_url.startswith("https://"):
        database_url = "https://visitor-management-8f5b4-default-rtdb.firebaseio.com"

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {"databaseURL": database_url + "/"})

    ref = db.reference()
    visitors_ref = ref.child("visitors")
    snapshot = visitors_ref.get()
    count = len(snapshot) if snapshot else 0

    if count == 0:
        print("No visitors in Firebase. Nothing to delete.")
        return

    visitors_ref.delete()
    print(f"Deleted all visitor data ({count} visitor(s)) from Firebase.")
    print("Admin dashboard and Register_App will show no visitors. Register a new visitor to test QR email on approve.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if "404" in str(e) or "NotFound" in type(e).__name__:
            print("Firebase returned 404. Check FIREBASE_DATABASE_URL and that the Realtime Database exists.")
        else:
            print(f"Error: {e}")
        sys.exit(1)
