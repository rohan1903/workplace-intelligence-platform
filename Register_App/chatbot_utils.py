# chatbot_utils.py

import os, requests
import google.generativeai as genai
from deep_translator import GoogleTranslator
from intents import detect_intent
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEYS"))
model = genai.GenerativeModel("models/gemini-1.5-flash")
chat = model.start_chat(history=[])

# Flask API base URL
API_URL = "http://localhost:5000"

# Host info (static or can be made dynamic later)
HOSTS = {
    "raj": {"name": "Mr. Raj Sharma", "floor": "5th Floor, Wing B"},
    "anita": {"name": "Ms. Anita Verma", "floor": "3rd Floor, Wing A"}
}

# 🔁 Translate text if needed
def translate(text, target_lang):
    if target_lang.lower() in ["english", "en"]:
        return text
    try:
        return GoogleTranslator(source='auto', target=target_lang).translate(text)
    except Exception as e:
        return text + f" ⚠️ (Translation Failed: {str(e)})"

# 💬 Get Gemini response (fallback or open intent)
def get_gemini_response(message):
    try:
        stream = chat.send_message(message, stream=True)
        return "".join(chunk.text for chunk in stream if chunk.candidates)
    except Exception:
        return "⚠️ I couldn't generate a response at the moment."

# 📅 Appointment intent handler
def handle_appointment(message):
    host = "Anita" if "anita" in message.lower() else "Raj"
    payload = {"host": host, "visitor": "guest"}
    try:
        res = requests.post(f"{API_URL}/appointment", json=payload)
        if res.ok and res.json().get("status") == "confirmed":
            return f"✅ Appointment with {host} confirmed!"
        else:
            return f"❌ No appointment found for {host}."
    except requests.RequestException:
        return "🔌 Unable to connect to the appointment service."

# 🛠️ Complaint intent handler
def handle_issue_logging(message):
    try:
        requests.post(f"{API_URL}/log_issue", json={"issue": message})
        return "🛠️ Issue reported. Our team will address it soon."
    except requests.RequestException:
        return "⚠️ Couldn't log the issue right now."

# 💬 Feedback intent handler
def handle_feedback(message):
    try:
        requests.post(f"{API_URL}/feedback", json={"feedback": message})
    except:
        pass

    if any(word in message.lower() for word in ["bad", "poor", "issue", "problem"]):
        return "Thanks for the feedback. We'll work on improving."
    return "Thanks for your positive feedback! 😊"

# 🧠 Route by intent
def respond_by_intent(intent, message):
    intent = intent.lower()
    if intent == "navigation":
        return "Please mention the person or department you're heading to."
    elif intent == "appointments":
        return handle_appointment(message)
    elif intent == "host_lookup":
        for key in HOSTS:
            if key in message.lower():
                return f"{HOSTS[key]['name']} is on {HOSTS[key]['floor']}."
        return "Please provide a valid host name."
    elif intent == "wifi_info":
        return "📶 Guest Wi-Fi password is available at the front desk."
    elif intent == "facilities":
        return "🛜 Restrooms are near the elevators. Lounge is on the 2nd floor."
    elif intent == "complaints":
        return handle_issue_logging(message)
    elif intent == "company_info":
        return "📢 Welcome to our Office Workplace Intelligence Platform. Contact the admin desk for more information."
    elif intent == "feedback":
        return handle_feedback(message)
    elif intent == "headquarters":
        return "📍 Please contact the reception desk for directions to specific departments or offices."
    else:
        return get_gemini_response(message)

# 🎯 Public method for Streamlit/frontend
def get_bot_response(message, language="english"):
    try:
        intent = detect_intent(message)
        raw_reply = respond_by_intent(intent, message)
        return translate(raw_reply, language)
    except Exception as e:
        return f"❌ An error occurred: {str(e)}"
