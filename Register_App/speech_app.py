from flask import Flask, request, jsonify, send_from_directory
import firebase_admin
from firebase_admin import credentials, db
import google.generativeai as genai
import os
import datetime

app = Flask(__name__, static_folder='static')

# --- Firebase Initialization (Realtime DB) ---
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate("firebase_credentials.json")
        database_url = os.environ.get("FIREBASE_DATABASE_URL", "https://visitor-management-8f5b4-default-rtdb.firebaseio.com").rstrip("/") + "/"
        firebase_admin.initialize_app(cred, {"databaseURL": database_url})
    print("✅ Firebase Realtime Database initialized successfully.")
except Exception as e:
    print(f"❌ Firebase initialization error: {e}")

# --- Gemini API Setup ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBECruX0CccYjhoy9xFh3V0VCpLkJxmtew")
model = None
try:
    if GEMINI_API_KEY != "YOUR_GEMINI_API_KEY":
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        print("✅ Gemini model configured.")
except Exception as e:
    print(f"❌ Gemini initialization error: {e}")
    model = None

# --- Translate feedback to English ---
async def translate_to_english(text):
    if not model or not text.strip():
        return text
    try:
        prompt = f"Translate this text to English: {text}"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"❌ Translation error: {e}")
        return text

# --- Serve Main HTML ---
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

# --- Feedback Submission ---
@app.route('/submit_feedback', methods=['POST'])
async def submit_feedback():
    try:
        data = request.json
        visitor_id = data.get('visitor_id', 'anonymous')
        feedback_text = data.get('feedback_text', '')

        if not feedback_text.strip():
            return jsonify({"success": False, "message": "Feedback cannot be empty."}), 400

        translated_text = await translate_to_english(feedback_text)

        feedback_entry = {
            "visitor_id": visitor_id,
            "original_feedback": feedback_text,
            "translated_feedback": translated_text,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }

        db.reference("feedback").push(feedback_entry)

        return jsonify({"success": True, "message": "Feedback submitted and translated successfully."})

    except Exception as e:
        print(f"❌ Feedback submission error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# --- Run App ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
