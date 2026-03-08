import os
import firebase_admin
from firebase_admin import credentials, db

# Initialize Firebase only if not already initialized
if not firebase_admin._apps:
    database_url = os.environ.get("FIREBASE_DATABASE_URL", "https://visitor-management-8f5b4-default-rtdb.firebaseio.com").rstrip("/") + "/"
    cred = credentials.Certificate("firebaseKey.json")
    firebase_admin.initialize_app(cred, {"databaseURL": database_url})

firebase_db = db
