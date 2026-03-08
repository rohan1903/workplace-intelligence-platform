#!/usr/bin/env python3
"""
Seed Firebase Realtime Database with one employee and one meeting room
so Register_App can show "Meeting with an employee" and meeting rooms.

Run from project root AFTER creating the Realtime Database in Firebase Console:
  python seed_firebase_data.py

Requires: Admin/firebase_credentials.json and FIREBASE_DATABASE_URL in Admin/.env
"""
import os
import sys

# Load Admin .env for FIREBASE_DATABASE_URL
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
        print("WARNING: FIREBASE_DATABASE_URL missing or invalid; using default US URL.")
        database_url = "https://visitor-management-8f5b4-default-rtdb.firebaseio.com"

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {"databaseURL": database_url + "/"})
    ref = db.reference()

    # One sample employee (so "Meeting with an employee" has an option)
    emp_id = "emp1"
    ref.child("employees").child(emp_id).set({
        "name": "Admin User",
        "email": "rohankolachala@gmail.com",
        "department": "Admin",
        "role": "Administrator",
    })
    print(f"Added employee: emp1 (Admin User, rohankolachala@gmail.com)")

    # One sample meeting room (so room dropdown is not empty)
    room_id = "room1"
    ref.child("meeting_rooms").child(room_id).set({
        "name": "Conference Room A",
        "capacity": 6,
        "floor": "1",
        "amenities": "Projector, Whiteboard",
    })
    print(f"Added meeting room: room1 (Conference Room A)")

    print("Done. Restart Register_App if it is running, then refresh the registration page.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if "404" in str(e) or "NotFound" in type(e).__name__:
            print("Firebase returned 404. Create the Realtime Database first (see FIX_DATABASE_AND_SEED.md Step 1).")
        else:
            print(f"Error: {e}")
        sys.exit(1)
