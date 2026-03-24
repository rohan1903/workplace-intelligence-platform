import os
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from presentation_demo import PRESENTATION_ROOM_IDS, PRESENTATION_ROOM_OPTIONS
except ImportError:
    PRESENTATION_ROOM_OPTIONS = {}
    PRESENTATION_ROOM_IDS = frozenset()

import smtplib
import random
import copy
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, jsonify, make_response
import pandas as pd
from dotenv import load_dotenv, dotenv_values
try:
    import firebase_admin
    from firebase_admin import credentials, db
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("[!] firebase-admin not installed. Using mock data mode.")
import pickle
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import csv
import io
import json

import pickle
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
import os
from flask import send_from_directory

# Add this route to serve images from the uploads_reg folder

# Load your sentiment analysis model (add this at the top of your app.py)
try:
    with open('sentiment_analysis.pkl', 'rb') as f:
        sentiment_model = pickle.load(f)
    print("Sentiment model loaded successfully")
except FileNotFoundError:
    print("Sentiment model file not found")
    sentiment_model = None
except Exception as e:
    print(f"Error loading sentiment model: {e}")
    sentiment_model = None


# --------------------------
# Environment & Flask Setup
# --------------------------
_admin_dir = os.path.dirname(os.path.abspath(__file__))
_admin_env_path = os.path.join(_admin_dir, ".env")
_admin_firebase_cred_path = os.path.join(_admin_dir, "firebase_credentials.json")
load_dotenv(_admin_env_path)


def _parse_env_bool(value, default=True):
    """Parse typical truthy/falsey strings; empty or unknown falls back to *default*."""
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return default


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "default_secret_for_testing")
app.config['UPLOAD_FOLDER'] = 'UPLOADS'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --------------------------
# Firebase Initialization (Optional - uses mock data if unavailable)
# --------------------------
# To switch to real Firebase: set USE_MOCK_DATA=false in admin/.env and add firebase_credentials.json
# If USE_MOCK_DATA is set in admin/.env, that wins over a conflicting OS/user environment variable
# (load_dotenv alone does not override existing env vars).
_dotenv_file = dotenv_values(_admin_env_path)
_raw_mock = _dotenv_file.get("USE_MOCK_DATA")
if _raw_mock is not None and str(_raw_mock).strip() != "":
    USE_MOCK_DATA = _parse_env_bool(_raw_mock, default=True)
else:
    USE_MOCK_DATA = _parse_env_bool(os.getenv("USE_MOCK_DATA"), default=True)

FIREBASE_INITIALIZED = False

if FIREBASE_AVAILABLE:
    try:
        if os.path.exists(_admin_firebase_cred_path):
            # Always initialize Firebase so it's ready when mock mode is toggled off at runtime.
            if not firebase_admin._apps:
                cred = credentials.Certificate(_admin_firebase_cred_path)
                database_url = os.environ.get("FIREBASE_DATABASE_URL", "https://visitor-management-8f5b4-default-rtdb.firebaseio.com").rstrip("/") + "/"
                firebase_admin.initialize_app(cred, {"databaseURL": database_url})
            FIREBASE_INITIALIZED = True
            if USE_MOCK_DATA:
                print("[OK] Firebase initialized (standby) — currently using MOCK DATA.")
                print("[*] For live Firebase: set USE_MOCK_DATA=false in admin/.env or use the dashboard toggle.")
            else:
                print("[OK] Firebase initialized successfully - Using REAL data")
        else:
            USE_MOCK_DATA = True
            print("[!] Firebase credentials not found. Using mock data for demonstration.")
            print(f"[*] Expected file: {_admin_firebase_cred_path}")
    except Exception as e:
        if not USE_MOCK_DATA:
            USE_MOCK_DATA = True
        print(f"[!] Firebase initialization failed: {e}. Using mock data for demonstration.")
else:
    USE_MOCK_DATA = True
    print("[!] firebase-admin not installed. Using mock data mode.")

# --------------------------
# Email Config
# --------------------------
SENDER_EMAIL = os.getenv("EMAIL_USER")
SENDER_PASS = os.getenv("EMAIL_PASS")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

_SENTINEL_IDS = frozenset({"null", "undefined", ""})

def _is_valid_visitor_id(vid):
    """Reject empty IDs and common JS sentinel values."""
    s = str(vid or "").strip()
    return bool(s) and s.lower() not in _SENTINEL_IDS

def _is_plausible_email(email):
    e = (email or "").strip().lower()
    if not e or e in ("n/a", "none", "unknown", "not provided", "no email"):
        return False
    return "@" in e

def send_email(recipient_email, registration_link):
    """Send email with registration link."""
    if not _is_plausible_email(recipient_email):
        print("[!] Invalid or missing recipient email.")
        return False
    if not (SENDER_EMAIL and SENDER_PASS):
        print("[!] Missing SMTP credentials.")
        return False

    msg = MIMEText(f"Hello,\n\nPlease register here: {registration_link}\n\nRegards,\nAdmin Team")
    msg['Subject'] = "Visitor Registration Invitation"
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        print(f"[OK] Email sent to {recipient_email}")
        return True
    except Exception as e:
        print(f"[X] Email sending failed: {e}")
        return False

def send_notification_email(recipient_email, subject, body):
    """Send a single notification email (e.g. time exceeded alert)."""
    if not _is_plausible_email(recipient_email):
        return False
    if not (SENDER_EMAIL and SENDER_PASS):
        return False
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        return True
    except Exception:
        return False


def _send_status_email(recipient_email, subject, paragraphs):
    """Send a simple HTML + plain-text status email (used for reject/blacklist notifications)."""
    if not (SENDER_EMAIL and SENDER_PASS):
        return False
    if not recipient_email or str(recipient_email).strip() in ("", "N/A"):
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email

    safe_paragraphs = [str(p) for p in (paragraphs or []) if str(p).strip()]
    if not safe_paragraphs:
        safe_paragraphs = ["This is an automated notification from the visitor management system."]

    html_body = "<html><body>" + "".join(f"<p>{p}</p>" for p in safe_paragraphs) + "</body></html>"
    text_body = "\n\n".join(safe_paragraphs)

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        return True
    except Exception:
        return False


def send_rejection_notification_email(recipient_email, visitor_name, reason=None):
    """Notify a visitor that their visit has been rejected."""
    name = visitor_name or "Visitor"
    paragraphs = [
        f"Hello {name},",
        "",
        "Your visit request has been rejected.",
    ]
    if reason:
        paragraphs.append(f"Reason: {reason}")
    paragraphs.extend(
        [
            "",
            "If you believe this is a mistake, please contact your host or the reception/security team.",
        ]
    )
    return _send_status_email(recipient_email, "Your visit has been rejected", paragraphs)


def send_blacklist_notification_email(recipient_email, visitor_name, reason=None):
    """Notify a visitor that they have been added to the blacklist."""
    name = visitor_name or "Visitor"
    paragraphs = [
        f"Hello {name},",
        "",
        "You have been added to the visitor blacklist and future visit requests will be automatically rejected.",
    ]
    if reason:
        paragraphs.append(f"Reason: {reason}")
    paragraphs.extend(
        [
            "",
            "If you believe this is a mistake, please contact security or the admin team.",
        ]
    )
    return _send_status_email(recipient_email, "You have been blacklisted from visits", paragraphs)


def _qr_image_bytes_from_payload(payload_string):
    """Generate QR code PNG bytes from payload string. Returns bytes or None."""
    try:
        import qrcode
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
        qr.add_data(payload_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def send_qr_checkin_email(recipient_email, visitor_name, checkin_link, qr_payload=None, visit_details=None):
    """Send visitor an email with full check-in content (QR + visit details). Sensitive data is only in email, not on the check-in page.
    visit_details: dict with purpose, duration, visit_date, status (optional).
    Returns (True, None) on success, (False, reason_string) on failure."""
    if not recipient_email or str(recipient_email).strip() in ("", "N/A"):
        return False, "No visitor email address"
    if not (SENDER_EMAIL and SENDER_PASS):
        return False, "SMTP not configured (set EMAIL_USER and EMAIL_PASS in admin/.env)"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your visit is approved – QR code & check-in details"
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email

    qr_img_cid = "qrcode1"
    qr_block = ""
    qr_image_part = None
    if qr_payload:
        qr_bytes = _qr_image_bytes_from_payload(qr_payload)
        if qr_bytes:
            qr_image_part = MIMEImage(qr_bytes, _subtype="png")
            qr_image_part.add_header("Content-ID", f"<{qr_img_cid}>")
            qr_image_part.add_header("Content-Disposition", "inline", filename="qrcode.png")
            qr_block = """
            <p style="margin: 16px 0 8px 0;"><strong>Your gate pass QR code (show at the gate):</strong></p>
            <p style="margin: 8px 0 16px 0;"><img src="cid:qrcode1" alt="QR Code" style="max-width: 220px; height: auto; border: 2px solid #ddd; border-radius: 8px;" /></p>
            <p style="font-size: 13px; color: #555;">Scan this at the gate kiosk. Max 2 scans (check-in + checkout). Do not share this QR with anyone.</p>
            """

    vd = visit_details or {}
    purpose = vd.get("purpose", "Not specified")
    duration = vd.get("duration", "Not specified")
    # Ensure visit date is formatted as dd-mm-yyyy for email display
    raw_visit_date = vd.get("visit_date", "—")
    visit_date = raw_visit_date
    if isinstance(raw_visit_date, str) and raw_visit_date not in ("", "—"):
        try:
            # Accept ISO format from DB and already-formatted dd-mm-yyyy; prefer dd-mm-yyyy in output
            if "-" in raw_visit_date:
                # Try ISO first
                try:
                    dt = datetime.strptime(raw_visit_date, "%Y-%m-%d")
                except ValueError:
                    dt = datetime.strptime(raw_visit_date, "%d-%m-%Y")
                visit_date = dt.strftime("%d-%m-%Y")
        except Exception:
            visit_date = raw_visit_date
    status = vd.get("status", "Approved")
    visit_block = f"""
    <table style="width: 100%; border-collapse: collapse; margin: 16px 0; background: #f8fafc; border-radius: 8px; overflow: hidden;">
        <tr><td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #475569;">Purpose</td><td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0;">{purpose}</td></tr>
        <tr><td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #475569;">Duration</td><td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0;">{duration}</td></tr>
        <tr><td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #475569;">Visit date</td><td style="padding: 10px 14px; border-bottom: 1px solid #e2e8f0;">{visit_date}</td></tr>
        <tr><td style="padding: 10px 14px; font-weight: 600; color: #475569;">Status</td><td style="padding: 10px 14px;">{status}</td></tr>
    </table>
    """

    html = f"""
    <html><body style="font-family: Arial, sans-serif; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2563eb;">Visit approved – your check-in details</h2>
            <p>Hello <strong>{visitor_name}</strong>,</p>
            <p>Your visit has been approved. <strong>Keep this email</strong> — it contains your QR code and visit details. These are not shown on the website for security.</p>
            <h3 style="color: #1e40af; margin-top: 24px;">Visit details</h3>
            {visit_block}
            <h3 style="color: #1e40af; margin-top: 24px;">QR code for the gate</h3>
            {qr_block}
            <p style="margin-top: 24px; padding: 12px; background: #fef2f2; border-left: 4px solid #dc2626; border-radius: 6px; font-size: 13px;">
                <strong>Security:</strong> Do not share this email or your QR code. They are tied to your identity and verified with face recognition at the gate.
            </p>
            <p style="margin-top: 20px; font-size: 13px; color: #64748b;">Need help? <a href="{checkin_link}">Open check-in page</a> (no sensitive data is shown there).</p>
        </div>
    </body></html>
    """
    # Plain-text fallback so the email is never blank
    plain = f"""Your visit is approved – check-in details

Hello {visitor_name},

Your visit has been approved. Keep this email; it contains your visit details. Your QR code is in the HTML version of this email (or check your gate pass).

Visit details:
- Purpose: {vd.get('purpose', 'Not specified')}
- Duration: {vd.get('duration', 'Not specified')}
- Visit date: {vd.get('visit_date', '—')}
- Status: {vd.get('status', 'Approved')}

Security: Do not share this email or your QR code. Use the QR from the HTML version at the gate.

Need help? Open: {checkin_link}
"""
    msg.attach(MIMEText(plain, "plain"))
    # HTML + inline image (client that supports HTML will show this)
    related = MIMEMultipart("related")
    related.attach(MIMEText(html, "html"))
    if qr_image_part:
        related.attach(qr_image_part)
    msg.attach(related)
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASS)
            server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        print(f"[OK] QR/check-in email sent to {recipient_email}")
        return True, None
    except Exception as e:
        err = str(e)
        print(f"[!] QR email failed to {recipient_email}: {err}")
        return False, err

def trigger_invitation(email):
    """Create a unique registration token and send a registration link to the external web app."""
    invite_token = str(uuid.uuid4())
    registration_base_url = os.getenv("REGISTRATION_APP_URL", "http://localhost:5001")
    registration_link = f"{registration_base_url}/?token={invite_token}"

    if not USE_MOCK_DATA and FIREBASE_AVAILABLE:
        db.reference(f"invitations/{invite_token}").set({
            "email": email,
            "status": "Pending"
        })

    return send_email(email, registration_link)

# --------------------------
# Mock Data Functions (for demonstration without Firebase)
# --------------------------
# In-memory blacklist overlay for mock mode so add/remove persists across page loads
_MOCK_BLACKLIST_STATE = {}

# Base caches so mock data stays stable across page refreshes (per app run)
_MOCK_VISITORS_BASE = None
_MOCK_EMPLOYEES_CACHE = None

_ADMIN_MOCK_SEED = None


def _admin_mock_seed():
    """Deterministic mock dataset: default seed is fixed so data does not change across refreshes or restarts.

    Override with MOCK_DATA_SEED in the environment when you want a different static dataset.
    """
    global _ADMIN_MOCK_SEED
    if _ADMIN_MOCK_SEED is None:
        raw = os.environ.get("MOCK_DATA_SEED", "").strip()
        if raw:
            try:
                _ADMIN_MOCK_SEED = int(raw)
            except ValueError:
                _ADMIN_MOCK_SEED = hash(raw) % (2**31)
        else:
            # Same default as historical visitor mock (stable demos; optional override via MOCK_DATA_SEED).
            _ADMIN_MOCK_SEED = 42
        print(
            f"[*] Admin mock data seed={_ADMIN_MOCK_SEED} "
            "(set MOCK_DATA_SEED to use another fixed dataset)"
        )
    return _ADMIN_MOCK_SEED


def get_mock_visitors():
    """Generate diverse mock visitor data covering normal and edge cases for analytics and occupancy.

    Uses a fixed RNG seed (``MOCK_DATA_SEED`` or default ``42``) and a cached base snapshot so the
    same visitors appear across page refreshes and app restarts; blacklist edits still apply.
    """
    global _MOCK_VISITORS_BASE

    # Build the base snapshot once per app run
    if _MOCK_VISITORS_BASE is not None:
        # Work on a copy so blacklist updates can be applied per request
        mock_visitors = copy.deepcopy(_MOCK_VISITORS_BASE)
        # Apply persisted blacklist state (so mock add/remove works across reloads)
        for vid, state in _MOCK_BLACKLIST_STATE.items():
            if vid not in mock_visitors:
                continue
            bi = mock_visitors[vid].setdefault('basic_info', {})
            bi['blacklisted'] = 'yes' if state.get('blacklisted') else 'no'
            bi['blacklist_reason'] = state.get('reason', 'No reason provided')
            bi['blacklisted_at'] = state.get('blacklisted_at', '')
            mock_visitors[vid]['blacklisted'] = state.get('blacklisted', False)
        return mock_visitors

    # Pick employee names from the same mock employee generator used by `/employees`,
    # so visitor↔employee association is consistent (and not just a rare string match).
    mock_employees = get_mock_employees()
    employee_names = [e.get("name", "") for e in mock_employees.values() if e.get("name")]

    rng = random.Random(_admin_mock_seed())
    mock_visitors = {}
    base = datetime.now()

    first_names = ['John', 'Jane', 'Bob', 'Alice', 'Charlie', 'Diana', 'Ethan', 'Fiona', 'George', 'Hannah',
                   'Michael', 'Sarah', 'David', 'Emily', 'James', 'Olivia', 'William', 'Sophia', 'Robert', 'Emma',
                   'Richard', 'Isabella', 'Joseph', 'Mia', 'Thomas', 'Charlotte', 'Christopher', 'Amelia', 'Daniel', 'Harper',
                   'Matthew', 'Evelyn', 'Anthony', 'Abigail', 'Mark', 'Elizabeth', 'Donald', 'Sofia', 'Steven', 'Avery',
                   'Priya', 'Kenji', 'Ananya', 'Diego', 'Yuki', 'Omar', 'Nina', 'Viktor', 'Zara', 'Luis']
    last_names = ['Doe', 'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis', 'Rodriguez',
                  'Martinez', 'Hernandez', 'Lopez', 'Wilson', 'Anderson', 'Thomas', 'Taylor', 'Moore', 'Jackson', 'Martin',
                  'Patel', 'Nguyen', 'Okafor', 'Silva', 'Kowalski', 'Nakamura', 'Haddad', 'Bergstrom', 'Okonkwo', 'Reyes']
    # Purposes span dashboard purpose buckets (meetings, employee-meeting, interview, delivery, maintenance, other).
    purposes = [
        'Business Meeting', 'Client Presentation', 'Product Demo', 'Training Session',
        'Meeting with employee host', 'Executive meeting with employee',
        'Job Interview', 'Panel interview for engineering role',
        'Package Delivery', 'Courier delivery — documents',
        'Maintenance Work', 'HVAC maintenance visit', 'Security Audit', 'Vendor Meeting', 'Consultation',
        'Site Visit', 'Equipment Installation', 'Network Setup', 'Software Demo', 'Contract Signing',
        'Team Collaboration', 'Project Review', 'Budget Discussion', 'Strategic Planning', 'Emergency Response',
        'Badge re-issue', 'Wellness check-in',
    ]
    departments = ['IT', 'HR', 'Sales', 'Marketing', 'Finance', 'Operations', 'Engineering', 'Legal', 'Security', 'Facilities']
    employee_first = ['Sarah', 'Mike', 'Emily', 'David', 'Lisa', 'Jennifer', 'Chris', 'Amanda', 'Ryan', 'Jessica']
    employee_last = ['Johnson', 'Chen', 'Rodriguez', 'Kim', 'Anderson', 'Martinez', 'Taylor', 'Lee', 'White', 'Harris']
    companies = ['TechCorp', 'Global Solutions', 'Innovate Inc', 'Digital Dynamics', 'Cloud Systems', 'Smart Solutions',
                 'Northwind Traders', 'Contoso Ltd', 'Fabrikam Industries']
    blacklist_reasons = ['Security violation', 'Unauthorized access attempt', 'Previous misconduct', 'Policy violation', 'No reason provided']
    positive_feedback = [
        "Great check-in experience, very smooth and fast.",
        "Staff were helpful and the process was efficient.",
        "Loved the digital flow; badge pickup was quick.",
        "Reception team was professional and welcoming.",
    ]
    neutral_feedback = [
        "Process was okay, nothing unusual.",
        "The visit went as expected.",
        "Average experience; signage could be clearer.",
    ]
    negative_feedback = [
        "Long waiting time at reception.",
        "The process felt confusing at first.",
        "Wi‑Fi guest access did not work on first try.",
        "Parking instructions were unclear.",
    ]

    room_ids = list(get_mock_rooms().keys())

    def make_visitor(visitor_id, full_name, status, check_in, check_out_time_str, expected_checkout_str,
                     purpose, dept, employee_name, expected_duration, is_blacklisted, extra_visits=None, room_id=None,
                     stay_hours=None):
        if room_id is None and room_ids:
            room_id = rng.choice(room_ids)
        first, last = full_name.split(' ', 1) if ' ' in full_name else (full_name, '')
        email = f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com"
        visit_data = {
            'check_in_time': check_in.strftime('%Y-%m-%d %H:%M:%S') if check_in else 'N/A',
            'check_out_time': check_out_time_str,
            'status': status,
            'purpose': purpose,
            'employee_name': employee_name,
            'department': dept,
            'expected_duration': expected_duration,
            'expected_checkout_time': expected_checkout_str if expected_checkout_str else 'N/A',
            'created_at': check_in.strftime('%Y-%m-%d %H:%M:%S') if check_in else base.strftime('%Y-%m-%d %H:%M:%S'),
            'room_id': room_id or '',
        }
        visits = {f"visit_{visitor_id}": visit_data}
        if extra_visits:
            visits.update(extra_visits)
        feedbacks = {}
        for j in range(rng.randint(0, 4)):
            sentiment = rng.choice(["positive", "neutral", "negative"])
            text = rng.choice(positive_feedback if sentiment == "positive" else negative_feedback if sentiment == "negative" else neutral_feedback)
            feedbacks[f"feedback_{j+1}"] = {
                "text": text,
                "timestamp": (base - timedelta(days=rng.randint(0, 45))).strftime('%Y-%m-%d %H:%M:%S'),
                "visitor_id": visitor_id,
            }
        rec = {
            'basic_info': {
                'name': full_name,
                'contact': f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
                'email': email,
                'blacklisted': is_blacklisted,
                'blacklist_reason': rng.choice(blacklist_reasons) if is_blacklisted else 'No reason provided',
                'company': rng.choice(companies) if rng.random() < 0.55 else 'N/A',
            },
            'visits': visits,
            'feedbacks': feedbacks,
        }
        rec['name'] = full_name
        rec['check_in_time'] = visit_data['check_in_time']
        rec['check_out_time'] = visit_data['check_out_time']
        rec['status'] = status
        rec['expected_checkout_time'] = expected_checkout_str or 'N/A'
        rec['purpose'] = purpose
        rec['employee_name'] = employee_name
        rec['department'] = dept
        rec['expected_duration'] = expected_duration
        rec['blacklisted'] = is_blacklisted
        rec['room_id'] = room_id or ''
        dur_h = stay_hours
        if dur_h is None and status == 'Checked-Out' and check_in and check_out_time_str and check_out_time_str != 'N/A':
            try:
                co = datetime.strptime(check_out_time_str, '%Y-%m-%d %H:%M:%S')
                dur_h = max(1, int((co - check_in).total_seconds() // 3600))
            except ValueError:
                dur_h = None
        rec['duration'] = f"{dur_h} hr" if dur_h else ''
        return rec

    idx = 0
    # Use employee names that are guaranteed to exist in `/employees` mock mode.
    if employee_names:
        emp = lambda: rng.choice(employee_names)
    else:
        # Fallback: should be rare, but keeps mock generation robust.
        emp = lambda: f"{rng.choice(employee_first)} {rng.choice(employee_last)}"
    dept = lambda: rng.choice(departments)
    name = lambda: f"{rng.choice(first_names)} {rng.choice(last_names)}"
    purpose = lambda: rng.choice(purposes)

    # --- Scenario 1: Currently checked in (last 24h) — for occupancy and "Currently Active" ---
    for hours_ago in [0, 1, 2, 3, 5, 6, 8, 10, 12, 14, 18, 21, 23]:
        idx += 1
        check_in = base - timedelta(hours=hours_ago)
        expected_checkout = check_in + timedelta(hours=3)
        mock_visitors[f"visitor_{idx}"] = make_visitor(
            idx, name(), 'Checked-In', check_in, 'N/A', expected_checkout.strftime('%Y-%m-%d %H:%M:%S'),
            purpose(), dept(), emp(), '2 hours', False)

    # --- Scenario 2: Time exceeded (checked in, expected checkout in past) ---
    for _ in range(6):
        idx += 1
        check_in = base - timedelta(hours=rng.randint(3, 8))
        expected_checkout = base - timedelta(hours=rng.randint(1, 3))
        mock_visitors[f"visitor_{idx}"] = make_visitor(
            idx, name(), 'Checked-In', check_in, 'N/A', expected_checkout.strftime('%Y-%m-%d %H:%M:%S'),
            purpose(), dept(), emp(), '1 hour', False)

    # --- Scenario 3: Checked out in last 24h (various spans for occupancy-over-time) ---
    for (start_h, stay_h) in [(23, 1), (22, 2), (20, 2), (18, 3), (15, 2), (12, 4), (10, 2), (8, 1), (6, 3), (4, 2), (2, 1), (1, 0)]:
        idx += 1
        check_in = base - timedelta(hours=start_h)
        stay = max(stay_h, 1)
        check_out = check_in + timedelta(hours=stay)
        mock_visitors[f"visitor_{idx}"] = make_visitor(
            idx, name(), 'Checked-Out', check_in, check_out.strftime('%Y-%m-%d %H:%M:%S'), 'N/A',
            purpose(), dept(), emp(), f"{stay} hours", False, stay_hours=stay)

    # --- Scenario 4: Registered, Approved, Rejected, Rescheduled (no check-in) ---
    for status in ['Registered', 'Registered', 'Approved', 'Approved', 'Rejected', 'Rescheduled', 'Registered', 'Approved']:
        idx += 1
        mock_visitors[f"visitor_{idx}"] = make_visitor(
            idx, name(), status, None, 'N/A', 'N/A', purpose(), dept(), emp(), '1 hour', False)
        mock_visitors[f"visitor_{idx}"]['check_in_time'] = 'N/A'

    # --- Scenario 5: Blacklisted mix ---
    for _ in range(8):
        idx += 1
        check_in = base - timedelta(hours=rng.randint(1, 20)) if rng.random() < 0.5 else None
        if check_in:
            stay = rng.randint(1, 4)
            check_out = check_in + timedelta(hours=stay)
            mock_visitors[f"visitor_{idx}"] = make_visitor(
                idx, name(), 'Checked-Out', check_in, check_out.strftime('%Y-%m-%d %H:%M:%S'), 'N/A',
                purpose(), dept(), emp(), '2 hours', True, stay_hours=stay)
        else:
            mock_visitors[f"visitor_{idx}"] = make_visitor(
                idx, name(), 'Registered', None, 'N/A', 'N/A', purpose(), dept(), emp(), '1 hour', True)
            mock_visitors[f"visitor_{idx}"]['check_in_time'] = 'N/A'

    # --- Scenario 6: Multiple visits (recurring visitors) ---
    for _ in range(10):
        idx += 1
        check_in = base - timedelta(hours=rng.randint(2, 22))
        stay = rng.randint(1, 5)
        check_out = check_in + timedelta(hours=stay)
        prev_visit = {
            f"visit_{idx}_prev": {
                'check_in_time': (base - timedelta(days=rng.randint(5, 30), hours=rng.randint(9, 17))).strftime('%Y-%m-%d %H:%M:%S'),
                'check_out_time': (base - timedelta(days=rng.randint(5, 30), hours=rng.randint(6, 14))).strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'Checked-Out', 'purpose': purpose(), 'employee_name': emp(), 'department': dept(),
                'expected_duration': '2 hours', 'expected_checkout_time': 'N/A', 'created_at': (base - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S'),
            }
        }
        mock_visitors[f"visitor_{idx}"] = make_visitor(
            idx, name(), 'Checked-Out', check_in, check_out.strftime('%Y-%m-%d %H:%M:%S'), 'N/A',
            purpose(), dept(), emp(), '2 hours', False, extra_visits=prev_visit, stay_hours=stay)

    # --- Scenario 7: Extra random visitors for volume and variety ---
    for _ in range(55):
        idx += 1
        days_ago = rng.randint(0, 30)
        hours_ago = rng.randint(0, 23)
        check_in = base - timedelta(days=days_ago, hours=hours_ago)
        status = rng.choices(
            ['Registered', 'Approved', 'Checked-In', 'Checked-Out', 'Time Exceeded', 'Rescheduled', 'Rejected'],
            weights=[0.12, 0.15, 0.22, 0.28, 0.05, 0.10, 0.08]
        )[0]
        if status in ['Checked-Out', 'Time Exceeded']:
            duration_h = rng.randint(1, 6)
            check_out = check_in + timedelta(hours=duration_h)
            check_out_str = check_out.strftime('%Y-%m-%d %H:%M:%S')
            expected_checkout_str = 'N/A'
        elif status == 'Checked-In':
            check_out_str = 'N/A'
            expected_checkout_str = (check_in + timedelta(hours=rng.randint(1, 4))).strftime('%Y-%m-%d %H:%M:%S')
            duration_h = None
        else:
            check_in = None
            check_out_str = 'N/A'
            expected_checkout_str = 'N/A'
            duration_h = None
        mock_visitors[f"visitor_{idx}"] = make_visitor(
            idx, name(), status,
            check_in, check_out_str, expected_checkout_str,
            purpose(), dept(), emp(), f"{rng.randint(1, 4)} hours",
            rng.random() < 0.12,
            stay_hours=duration_h if status in ('Checked-Out', 'Time Exceeded') else None)
        if check_in is None:
            mock_visitors[f"visitor_{idx}"]['check_in_time'] = 'N/A'

    # Apply persisted blacklist state (so mock add/remove works across reloads)
    for vid, state in _MOCK_BLACKLIST_STATE.items():
        if vid not in mock_visitors:
            continue
        bi = mock_visitors[vid].setdefault('basic_info', {})
        bi['blacklisted'] = 'yes' if state.get('blacklisted') else 'no'
        bi['blacklist_reason'] = state.get('reason', 'No reason provided')
        bi['blacklisted_at'] = state.get('blacklisted_at', '')
        mock_visitors[vid]['blacklisted'] = state.get('blacklisted', False)

    # Cache the base snapshot for future calls
    _MOCK_VISITORS_BASE = copy.deepcopy(mock_visitors)
    return mock_visitors

def get_mock_employees():
    """Generate diverse mock employee data.

    Uses an RNG derived from the same admin mock seed as visitors; results are cached (static across refreshes).
    """
    global _MOCK_EMPLOYEES_CACHE

    if _MOCK_EMPLOYEES_CACHE is not None:
        return _MOCK_EMPLOYEES_CACHE

    rng = random.Random(_admin_mock_seed() + 17_389_711)
    departments = [
        'IT', 'HR', 'Sales', 'Marketing', 'Finance', 'Operations', 'Engineering', 'Legal', 'Security', 'Facilities',
        'R&D', 'Executive', 'Admin',
    ]

    first_names = ['Sarah', 'Mike', 'Emily', 'David', 'Lisa', 'Jennifer', 'Chris', 'Amanda', 'Ryan', 'Jessica',
                   'Kevin', 'Nicole', 'Brian', 'Michelle', 'Jason', 'Ashley', 'Justin', 'Stephanie', 'Brandon', 'Melissa',
                   'Robert', 'Daniel', 'Lauren', 'Matthew', 'Rachel', 'Andrew', 'Samantha', 'Joshua', 'Megan',
                   'Priya', 'Kenji', 'Ananya', 'Diego', 'Yuki', 'Omar', 'Nina', 'Viktor', 'Zara', 'Luis']

    last_names = ['Johnson', 'Chen', 'Rodriguez', 'Kim', 'Anderson', 'Martinez', 'Taylor', 'Lee', 'White', 'Harris',
                  'Wilson', 'Moore', 'Jackson', 'Thompson', 'Garcia', 'Robinson', 'Clark', 'Lewis',
                  'Patel', 'Nguyen', 'Okafor', 'Silva', 'Kowalski', 'Nakamura', 'Haddad', 'Bergstrom']

    positions_by_dept = {
        'IT': ['Senior Developer', 'Software Engineer', 'DevOps Engineer', 'System Administrator', 'IT Manager', 'Network Engineer', 'SRE', 'Data Engineer'],
        'HR': ['HR Manager', 'Recruiter', 'HR Specialist', 'Talent Acquisition', 'Benefits Coordinator', 'HR Director'],
        'Sales': ['Sales Manager', 'Account Executive', 'Sales Representative', 'Business Development', 'Sales Director', 'Account Manager'],
        'Marketing': ['Marketing Manager', 'Content Creator', 'Digital Marketing Specialist', 'Brand Manager', 'Marketing Director', 'SEO Specialist'],
        'Finance': ['Financial Analyst', 'Accountant', 'Finance Manager', 'CFO', 'Controller', 'Budget Analyst'],
        'Operations': ['Operations Manager', 'Operations Analyst', 'Supply Chain Manager', 'Operations Director', 'Logistics Coordinator'],
        'Engineering': ['Senior Engineer', 'Project Engineer', 'Engineering Manager', 'Lead Engineer', 'Principal Engineer'],
        'Legal': ['Legal Counsel', 'Compliance Officer', 'Legal Assistant', 'General Counsel', 'Paralegal'],
        'Security': ['Security Manager', 'Security Analyst', 'Security Officer', 'Chief Security Officer', 'Security Specialist'],
        'Facilities': ['Facilities Manager', 'Maintenance Supervisor', 'Facilities Coordinator', 'Building Manager'],
        'R&D': ['Research Scientist', 'Lab Manager', 'Prototype Engineer', 'Innovation Lead'],
        'Executive': ['Chief of Staff', 'VP Operations', 'Director', 'Executive Assistant'],
        'Admin': ['Office Administrator', 'Executive Assistant', 'Reception Lead'],
    }

    mock_employees = {}
    # Fixed count: static demo dataset so mock dashboards are stable.
    num_employees = 112

    for i in range(num_employees):
        emp_id = f"emp_{i+1}"
        dept = rng.choice(departments)
        first_name = rng.choice(first_names)
        last_name = rng.choice(last_names)
        full_name = f"{first_name} {last_name}"

        positions = positions_by_dept.get(dept, ['Manager', 'Specialist', 'Coordinator'])
        position = rng.choice(positions)

        email_formats = [
            f"{first_name.lower()}.{last_name.lower()}@company.com",
            f"{first_name[0].lower()}{last_name.lower()}@company.com",
            f"{first_name.lower()}{last_name[0].lower()}@company.com",
            f"{first_name.lower()}{rng.randint(1, 99)}@company.com",
        ]

        mock_employees[emp_id] = {
            'name': full_name,
            'email': rng.choice(email_formats),
            'department': dept,
            'position': position,
            'role': position,
            'employee_id': f"EMP{rng.randint(1000, 9999)}",
            'phone': f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
        }

    _MOCK_EMPLOYEES_CACHE = mock_employees
    return mock_employees

def get_mock_rooms():
    """Default meeting rooms for mock mode (name, capacity, floor, amenities)."""
    return {
        'room_1': {'name': 'Conference A', 'capacity': 10, 'floor': 1, 'amenities': 'Projector, Whiteboard'},
        'room_2': {'name': 'Conference B', 'capacity': 6, 'floor': 1, 'amenities': 'TV, Video call'},
        'room_3': {'name': 'Meeting Room 101', 'capacity': 4, 'floor': 1, 'amenities': 'Whiteboard'},
        'room_4': {'name': 'Meeting Room 102', 'capacity': 4, 'floor': 1, 'amenities': 'None'},
        'room_5': {'name': 'Board Room', 'capacity': 20, 'floor': 2, 'amenities': 'Projector, Video call, Whiteboard'},
        'room_6': {'name': 'Innovation Lab', 'capacity': 8, 'floor': 2, 'amenities': 'Whiteboard, Video wall'},
        'room_7': {'name': 'Executive Suite', 'capacity': 12, 'floor': 3, 'amenities': 'Premium AV, Catering'},
        'room_8': {'name': 'Training Hall', 'capacity': 40, 'floor': 1, 'amenities': 'PA system, Mic'},
        'room_9': {'name': 'Phone Booth Cluster', 'capacity': 2, 'floor': 2, 'amenities': 'Sound dampening'},
        'room_10': {'name': 'Town Hall', 'capacity': 80, 'floor': 1, 'amenities': 'Stage, Projector'},
    }

# In-memory cache for mock meeting rooms (CRUD updates this; resets on app restart)
_mock_rooms_cache = None

def get_meeting_rooms():
    """Return all meeting rooms (mock or Firebase), merged with shared presentation demo rooms."""
    global _mock_rooms_cache
    if USE_MOCK_DATA:
        if _mock_rooms_cache is None:
            _mock_rooms_cache = dict(get_mock_rooms())
        base = dict(_mock_rooms_cache)
    else:
        ref = db.reference('meeting_rooms')
        raw = ref.get() or {}
        base = dict(raw) if isinstance(raw, dict) else {}
    for rid, meta in PRESENTATION_ROOM_OPTIONS.items():
        if rid not in base:
            entry = dict(meta)
            entry["presentation_demo"] = True
            base[rid] = entry
    return base

def save_meeting_room(room_id, data):
    """Create or update a meeting room. data: name, capacity, floor, amenities."""
    global _mock_rooms_cache
    if room_id in PRESENTATION_ROOM_IDS:
        raise ValueError("Presentation demo rooms cannot be edited")
    payload = {
        'name': str(data.get('name', '')).strip() or 'Unnamed',
        'capacity': int(data.get('capacity', 0)) if data.get('capacity') not in (None, '') else 0,
        'floor': str(data.get('floor', '')).strip() or '0',
        'amenities': str(data.get('amenities', '')).strip() or ''
    }
    if USE_MOCK_DATA:
        if _mock_rooms_cache is None:
            _mock_rooms_cache = dict(get_mock_rooms())
        _mock_rooms_cache[room_id] = payload
        return
    db.reference(f'meeting_rooms/{room_id}').set(payload)

def delete_meeting_room(room_id):
    """Remove a meeting room."""
    global _mock_rooms_cache
    if room_id in PRESENTATION_ROOM_IDS:
        return
    if USE_MOCK_DATA:
        if _mock_rooms_cache is None:
            _mock_rooms_cache = dict(get_mock_rooms())
        _mock_rooms_cache.pop(room_id, None)
        return
    db.reference(f'meeting_rooms/{room_id}').delete()


def _get_occupied_room_ids():
    """Return set of room_id that have at least one visitor currently checked in."""
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        visitors_ref = db.reference('visitors')
        all_visitors = visitors_ref.get() or {}
    occupied = set()
    for vid, vdata in all_visitors.items():
        if (vdata.get('status') or '').strip() != 'Checked-In':
            continue
        room_id = (vdata.get('room_id') or '').strip()
        if not room_id:
            visits = vdata.get('visits', {})
            if visits:
                sorted_visits = []
                for v_id, v_data in visits.items():
                    ts = v_data.get('created_at') or v_data.get('check_in_time')
                    if ts:
                        try:
                            sorted_visits.append((datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'), v_data))
                        except ValueError:
                            pass
                if sorted_visits:
                    sorted_visits.sort(key=lambda x: x[0], reverse=True)
                    room_id = (sorted_visits[0][1].get('room_id') or '').strip()
        if room_id:
            occupied.add(room_id)
    return occupied


def _sorted_visits_newest_first(visits):
    """Return [(datetime, visit_id, visit_data), ...] newest first; skips visits without a parseable timestamp."""
    if not visits:
        return []
    sorted_visits = []
    for visit_id, visit_data in visits.items():
        visit_timestamp = visit_data.get('created_at') or visit_data.get('check_in_time')
        if visit_timestamp:
            try:
                visit_dt = datetime.strptime(visit_timestamp, "%Y-%m-%d %H:%M:%S")
                sorted_visits.append((visit_dt, visit_id, visit_data))
            except ValueError:
                continue
    sorted_visits.sort(key=lambda x: x[0], reverse=True)
    return sorted_visits


def _extract_visitor_room(visitor_data, rooms_map):
    """Room from the most recent visit (registration choice), else root visitor room_id. Returns (room_id, display_label)."""
    visits = visitor_data.get('visits') or {}
    room_id = (visitor_data.get('room_id') or '').strip()
    sorted_visits = _sorted_visits_newest_first(visits)
    if sorted_visits:
        rid = (sorted_visits[0][2].get('room_id') or '').strip()
        if rid:
            room_id = rid
    if not room_id:
        return '', '—'
    meta = rooms_map.get(room_id) or {}
    label = (meta.get('name') or '').strip() or room_id
    return room_id, label


def _registered_at_from_visitor(visitor_data):
    """When the visitor first appeared in the system.

    Registration sets ``basic_info.registered_at``; the gate may add ``transactions``.
    Detail pages used only ``transactions``, so profiles showed N/A until check-in.
    """
    if not isinstance(visitor_data, dict):
        return 'N/A'
    basic_info = visitor_data.get('basic_info') or {}
    ra = basic_info.get('registered_at')
    if ra is not None and str(ra).strip() and str(ra).strip().upper() != 'N/A':
        return str(ra).strip()
    transactions = visitor_data.get('transactions') or {}
    if isinstance(transactions, dict) and transactions:
        earliest_key = min(transactions.keys())
        ts = (transactions[earliest_key] or {}).get('timestamp')
        if ts:
            return ts
    visits = visitor_data.get('visits') or {}
    if not isinstance(visits, dict) or not visits:
        return 'N/A'
    earliest_dt = None
    for v in visits.values():
        if not isinstance(v, dict):
            continue
        ca = v.get('created_at')
        if not ca:
            continue
        try:
            dt = datetime.strptime(ca, "%Y-%m-%d %H:%M:%S")
            if earliest_dt is None or dt < earliest_dt:
                earliest_dt = dt
        except ValueError:
            continue
    return earliest_dt.strftime("%Y-%m-%d %H:%M:%S") if earliest_dt else 'N/A'


def _registration_count_by_room(all_visitors):
    """Per room_id: number of visitors whose latest visit selected that room at registration."""
    counts = {}
    if not all_visitors:
        return counts
    for _vid, vdata in all_visitors.items():
        visits = vdata.get('visits') or {}
        sorted_visits = _sorted_visits_newest_first(visits)
        if sorted_visits:
            rid = (sorted_visits[0][2].get('room_id') or '').strip()
        else:
            rid = (vdata.get('room_id') or '').strip()
        if rid:
            counts[rid] = counts.get(rid, 0) + 1
    return counts


# --------------------------
# Analytics Functions
# --------------------------
def get_visitor_analytics():
    """Get comprehensive visitor analytics for dashboard"""
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        visitors_ref = db.reference('visitors')
        all_visitors = visitors_ref.get() or {}
    
    now = datetime.now()
    today = now.date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    daily_count = 0
    weekly_count = 0
    monthly_count = 0
    purpose_counts = Counter()
    status_counts = Counter()
    blacklisted_count = 0
    
    for vid, data in all_visitors.items():
        # Count visitors by time period
        check_in_time = data.get('check_in_time')
        if check_in_time:
            try:
                check_in_date = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S").date()
                if check_in_date == today:
                    daily_count += 1
                if check_in_date >= week_ago:
                    weekly_count += 1
                if check_in_date >= month_ago:
                    monthly_count += 1
            except ValueError:
                pass
        
        # Count by purpose
        purpose = data.get('purpose', 'Unknown')
        purpose_counts[purpose] += 1
        
        # Count by status
        status = data.get('status', 'Unknown')
        status_counts[status] += 1
        
        # Count blacklisted
        blacklisted = data.get('blacklisted', False)
        if isinstance(blacklisted, str):
            if blacklisted.strip().lower() in ['yes', 'true', '1']:
                blacklisted_count += 1
        elif blacklisted:
            blacklisted_count += 1
    
    return {
        'daily_count': daily_count,
        'weekly_count': weekly_count,
        'monthly_count': monthly_count,
        'purpose_counts': dict(purpose_counts),
        'status_counts': dict(status_counts),
        'blacklisted_count': blacklisted_count,
        'total_visitors': len(all_visitors)
    }

# --------------------------
# Routes
# --------------------------
@app.route('/uploads_reg/<path:filename>')
def serve_uploaded_image(filename):
    """Serve images from the uploads_reg directory"""
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "registration", "uploads_reg")
    return send_from_directory(uploads_dir, filename)


@app.route('/')
def index():
    INDEX_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Admin Panel - Workplace Intelligence Platform with Hybrid Face–QR Authentication</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {
                font-family: 'Inter', sans-serif;
                background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            }
            .card-hover {
                transition: all 0.3s ease;
                transform: translateY(0);
            }
            .card-hover:hover {
                transform: translateY(-5px);
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            .glass-effect {
                background: rgba(255, 255, 255, 0.1);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            .toggle-track {
                width: 52px; height: 28px;
                border-radius: 14px;
                background: rgba(255,255,255,0.25);
                cursor: pointer;
                transition: background 0.3s;
                position: relative;
            }
            .toggle-track.active { background: #10B981; }
            .toggle-knob {
                width: 22px; height: 22px;
                border-radius: 50%;
                background: white;
                position: absolute; top: 3px; left: 3px;
                transition: transform 0.3s;
                box-shadow: 0 1px 3px rgba(0,0,0,.3);
            }
            .toggle-track.active .toggle-knob { transform: translateX(24px); }
            .mock-badge {
                display: inline-flex; align-items: center; gap: 6px;
                font-size: 0.75rem; font-weight: 600;
                padding: 2px 10px; border-radius: 9999px;
            }
            .mock-badge.on  { background: #10B981; color: white; }
            .mock-badge.off { background: rgba(255,255,255,0.2); color: rgba(255,255,255,0.7); }
            .main-grid {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 1.5rem;
            }
            .second-row {
                grid-column: 1 / -1;
                display: flex;
                justify-content: center;
                gap: 1.5rem;
            }
            @media (max-width: 1024px) {
                .main-grid {
                    grid-template-columns: repeat(2, 1fr);
                }
                .second-row {
                    justify-content: flex-start;
                }
            }
            @media (max-width: 768px) {
                .main-grid {
                    grid-template-columns: 1fr;
                }
                .second-row {
                    flex-direction: column;
                    align-items: center;
                }
            }
        </style>
    </head>
    <body class="min-h-screen flex items-center justify-center p-4">
        <div class="max-w-6xl w-full">
            <!-- Header -->
            <div class="text-center mb-12">
                <div class="inline-flex items-center justify-center w-20 h-20 rounded-full bg-white/10 backdrop-blur-sm mb-4">
                    <i class="fas fa-shield-alt text-white text-3xl"></i>
                </div>
                <h1 class="text-4xl md:text-5xl font-bold text-white mb-3">Admin Dashboard</h1>
                <p class="text-white/80 text-lg">Workplace Intelligence Platform</p>
                <!-- Mock Data Toggle -->
                <div class="mt-4 inline-flex items-center gap-3 glass-effect rounded-full px-4 py-2">
                    <span class="text-white/80 text-sm font-medium">Demo Mode</span>
                    <div id="mockToggle" class="toggle-track {{ 'active' if use_mock else '' }}" onclick="toggleMockData()">
                        <div class="toggle-knob"></div>
                    </div>
                    <span id="mockBadge" class="mock-badge {{ 'on' if use_mock else 'off' }}">
                        {{ 'MOCK' if use_mock else 'LIVE' }}
                    </span>
                </div>
            </div>

            <!-- Main Navigation Cards -->
            <div class="main-grid">
                <!-- First Row - 3 Cards -->
                <!-- Visitors Card -->
                <a href="{{ url_for('visitors_list') }}" 
                   class="card-hover bg-white rounded-2xl p-6 shadow-xl border border-gray-100 hover:border-blue-200 group">
                    <div class="flex items-center mb-4">
                        <div class="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center group-hover:bg-blue-500 transition-colors">
                            <i class="fas fa-users text-blue-600 group-hover:text-white text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-xl font-semibold text-gray-800">Visitors Management</h3>
                            <p class="text-gray-600 text-sm">Manage all visitor records</p>
                        </div>
                    </div>
                    <div class="flex justify-between items-center text-sm text-gray-500">
                        <span>View, edit, and manage visitors</span>
                        <i class="fas fa-arrow-right group-hover:translate-x-1 transition-transform"></i>
                    </div>
                </a>

                <!-- Dashboard & Analytics Card -->
                <a href="{{ url_for('admin_dashboard') }}" 
                   class="card-hover bg-white rounded-2xl p-6 shadow-xl border border-gray-100 hover:border-emerald-200 group">
                    <div class="flex items-center mb-4">
                        <div class="w-12 h-12 bg-emerald-100 rounded-xl flex items-center justify-center group-hover:bg-emerald-500 transition-colors">
                            <i class="fas fa-chart-bar text-emerald-600 group-hover:text-white text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-xl font-semibold text-gray-800">Dashboard & Analytics</h3>
                            <p class="text-gray-600 text-sm">Comprehensive insights</p>
                        </div>
                    </div>
                    <div class="flex justify-between items-center text-sm text-gray-500">
                        <span>View analytics and reports</span>
                        <i class="fas fa-arrow-right group-hover:translate-x-1 transition-transform"></i>
                    </div>
                </a>

                <!-- Upload Invitations Card -->
                <a href="{{ url_for('upload_invitations_page') }}" 
                   class="card-hover bg-white rounded-2xl p-6 shadow-xl border border-gray-100 hover:border-indigo-200 group">
                    <div class="flex items-center mb-4">
                        <div class="w-12 h-12 bg-indigo-100 rounded-xl flex items-center justify-center group-hover:bg-indigo-500 transition-colors">
                            <i class="fas fa-envelope text-indigo-600 group-hover:text-white text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <h3 class="text-xl font-semibold text-gray-800">Upload Invitations</h3>
                            <p class="text-gray-600 text-sm">Send bulk invitations</p>
                        </div>
                    </div>
                    <div class="flex justify-between items-center text-sm text-gray-500">
                        <span>Upload Excel to send invites</span>
                        <i class="fas fa-arrow-right group-hover:translate-x-1 transition-transform"></i>
                    </div>
                </a>

                <!-- Second Row - 2 Centered Cards -->
                <div class="second-row">
                    <!-- Feedback Analysis Card -->
                    <a href="{{ url_for('feedback_analysis') }}" 
                       class="card-hover bg-white rounded-2xl p-6 shadow-xl border border-gray-100 hover:border-orange-200 group w-full max-w-md">
                        <div class="flex items-center mb-4">
                            <div class="w-12 h-12 bg-orange-100 rounded-xl flex items-center justify-center group-hover:bg-orange-500 transition-colors">
                                <i class="fas fa-comment-alt text-orange-600 group-hover:text-white text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <h3 class="text-xl font-semibold text-gray-800">Feedback Analysis</h3>
                                <p class="text-gray-600 text-sm">Sentiment and reviews</p>
                            </div>
                        </div>
                        <div class="flex justify-between items-center text-sm text-gray-500">
                            <span>Analyze visitor feedback</span>
                            <i class="fas fa-arrow-right group-hover:translate-x-1 transition-transform"></i>
                        </div>
                    </a>

                    <!-- Employee List Card -->
                    <a href="{{ url_for('employees_list') }}" 
                       class="card-hover bg-white rounded-2xl p-6 shadow-xl border border-gray-100 hover:border-purple-200 group w-full max-w-md">
                        <div class="flex items-center mb-4">
                            <div class="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center group-hover:bg-purple-500 transition-colors">
                                <i class="fas fa-user-tie text-blue-600 group-hover:text-white text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <h3 class="text-xl font-semibold text-gray-800">Employee Management</h3>
                                <p class="text-gray-600 text-sm">Manage staff records</p>
                            </div>
                        </div>
                        <div class="flex justify-between items-center text-sm text-gray-500">
                            <span>View and manage employees</span>
                            <i class="fas fa-arrow-right group-hover:translate-x-1 transition-transform"></i>
                        </div>
                    </a>

                    <!-- Blacklist Management Card -->
                    <a href="{{ url_for('blacklist_page') }}" 
                       class="card-hover bg-white rounded-2xl p-6 shadow-xl border border-gray-100 hover:border-red-200 group w-full max-w-md">
                        <div class="flex items-center mb-4">
                            <div class="w-12 h-12 bg-red-100 rounded-xl flex items-center justify-center group-hover:bg-red-500 transition-colors">
                                <i class="fas fa-ban text-red-600 group-hover:text-white text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <h3 class="text-xl font-semibold text-gray-800">Blacklist Management</h3>
                                <p class="text-gray-600 text-sm">View and manage blacklisted individuals</p>
                            </div>
                        </div>
                        <div class="flex justify-between items-center text-sm text-gray-500">
                            <span>View blacklisted visitors, remove from list</span>
                            <i class="fas fa-arrow-right group-hover:translate-x-1 transition-transform"></i>
                        </div>
                    </a>

                    <!-- Meeting Rooms Card -->
                    <a href="{{ url_for('rooms_list') }}" 
                       class="card-hover bg-white rounded-2xl p-6 shadow-xl border border-gray-100 hover:border-teal-200 group w-full max-w-md">
                        <div class="flex items-center mb-4">
                            <div class="w-12 h-12 bg-teal-100 rounded-xl flex items-center justify-center group-hover:bg-teal-500 transition-colors">
                                <i class="fas fa-door-open text-teal-600 group-hover:text-white text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <h3 class="text-xl font-semibold text-gray-800">Meeting Rooms</h3>
                                <p class="text-gray-600 text-sm">Rooms, capacity, and utilization</p>
                            </div>
                        </div>
                        <div class="flex justify-between items-center text-sm text-gray-500">
                            <span>Add, edit, delete rooms</span>
                            <i class="fas fa-arrow-right group-hover:translate-x-1 transition-transform"></i>
                        </div>
                    </a>
                </div>
            </div>

            <!-- Footer -->
            <div class="text-center mt-8">
                <p class="text-white/60 text-sm">
                    <i class="fas fa-shield-alt mr-2"></i>
                    Workplace Intelligence Platform with Hybrid Face–QR Authentication v2.0
                </p>
            </div>
        </div>

        <script>
            document.addEventListener('DOMContentLoaded', function() {
                const cards = document.querySelectorAll('.card-hover');
                cards.forEach((card, index) => {
                    card.style.opacity = '0';
                    card.style.transform = 'translateY(20px)';
                    setTimeout(() => {
                        card.style.transition = 'all 0.5s ease';
                        card.style.opacity = '1';
                        card.style.transform = 'translateY(0)';
                    }, index * 100);
                });
            });

            function toggleMockData() {
                const track = document.getElementById('mockToggle');
                const badge = document.getElementById('mockBadge');
                const enabling = !track.classList.contains('active');

                track.style.opacity = '0.5';
                track.style.pointerEvents = 'none';

                fetch('/api/mock_data', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mock: enabling})
                })
                .then(r => r.json().then(d => ({ok: r.ok, data: d})))
                .then(({ok, data}) => {
                    if (!ok) {
                        alert(data.message || 'Failed to toggle mock data');
                        return;
                    }
                    if (data.mock) {
                        track.classList.add('active');
                        badge.className = 'mock-badge on';
                        badge.textContent = 'MOCK';
                    } else {
                        track.classList.remove('active');
                        badge.className = 'mock-badge off';
                        badge.textContent = 'LIVE';
                    }
                })
                .catch(err => alert('Error toggling mock data: ' + err))
                .finally(() => {
                    track.style.opacity = '1';
                    track.style.pointerEvents = 'auto';
                });
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(INDEX_HTML, use_mock=USE_MOCK_DATA)
@app.route('/upload_invitations')
def upload_invitations_page():
    """Dedicated page for uploading invitations with clean UI"""
    UPLOAD_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Upload Invitations - Workplace Intelligence Platform</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    </head>
    <body class="bg-gray-50 min-h-screen">
        <!-- Header -->
        <div class="bg-white shadow-sm border-b">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between items-center py-4">
                    <div class="flex items-center">
                        <a href="{{ url_for('index') }}" class="text-gray-500 hover:text-gray-700 mr-4">
                            <i class="fas fa-arrow-left"></i>
                        </a>
                        <h1 class="text-2xl font-bold text-gray-900">Upload Invitations</h1>
                    </div>
                    <a href="{{ url_for('index') }}" class="text-blue-600 hover:text-blue-800 font-medium">
                        <i class="fas fa-home mr-2"></i>Back to Home
                    </a>
                </div>
            </div>
        </div>

        <div class="max-w-4xl mx-auto py-8 px-4 sm:px-6 lg:px-8">
            <!-- Upload Card -->
            <div class="bg-white rounded-2xl shadow-xl p-8">
                <div class="text-center mb-8">
                    <div class="w-20 h-20 bg-indigo-100 rounded-full flex items-center justify-center mx-auto mb-4">
                        <i class="fas fa-envelope-open-text text-indigo-600 text-3xl"></i>
                    </div>
                    <h2 class="text-3xl font-bold text-gray-900 mb-2">Send Bulk Invitations</h2>
                    <p class="text-gray-600 text-lg">Upload an Excel file to send registration invitations to multiple visitors</p>
                </div>

                <!-- Upload Form -->
                <form id="inviteForm" method="POST" action="{{ url_for('upload_invites') }}" enctype="multipart/form-data" class="space-y-6">
                    <!-- File Upload Area -->
                    <div class="border-2 border-dashed border-gray-300 rounded-2xl p-8 text-center hover:border-indigo-400 transition-colors">
                        <div class="flex flex-col items-center justify-center">
                            <i class="fas fa-file-excel text-green-500 text-5xl mb-4"></i>
                            <p class="text-lg font-semibold text-gray-700 mb-2">Upload Excel File</p>
                            <p class="text-gray-500 mb-4">Supported formats: .xlsx, .xls</p>
                            
                            <div class="relative">
                                <input type="file" name="file" id="fileInput" 
                                       accept=".xlsx,.xls" 
                                       class="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                                       required>
                                <label for="fileInput" class="bg-indigo-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-indigo-700 transition-colors cursor-pointer">
                                    <i class="fas fa-upload mr-2"></i>Choose File
                                </label>
                            </div>
                            
                            <p id="fileName" class="text-sm text-gray-500 mt-3">No file chosen</p>
                        </div>
                    </div>

                    <!-- Requirements -->
                    <div class="bg-blue-50 rounded-xl p-6">
                        <h3 class="font-semibold text-blue-900 mb-3 flex items-center">
                            <i class="fas fa-info-circle mr-2"></i>File Requirements
                        </h3>
                        <ul class="text-blue-800 space-y-2 text-sm">
                            <li class="flex items-center">
                                <i class="fas fa-check-circle mr-2 text-green-500"></i>
                                File must contain an 'Email' column (case insensitive)
                            </li>
                            <li class="flex items-center">
                                <i class="fas fa-check-circle mr-2 text-green-500"></i>
                                Each email will receive a unique registration link
                            </li>
                            <li class="flex items-center">
                                <i class="fas fa-check-circle mr-2 text-green-500"></i>
                                Duplicate emails will be automatically filtered
                            </li>
                            <li class="flex items-center">
                                <i class="fas fa-check-circle mr-2 text-green-500"></i>
                                System supports up to 1000 invitations per upload
                            </li>
                        </ul>
                    </div>

                    <!-- Submit Button -->
                    <button type="submit" 
                            id="submitBtn"
                            class="w-full bg-gradient-to-r from-indigo-600 to-purple-600 text-white py-4 px-6 rounded-xl font-semibold text-lg hover:from-indigo-700 hover:to-purple-700 transition-all transform hover:scale-105 shadow-lg">
                        <i class="fas fa-paper-plane mr-3"></i>Send Invitations
                    </button>
                </form>
            </div>
        </div>

        <script>
            // File input handling
            const fileInput = document.getElementById('fileInput');
            const fileName = document.getElementById('fileName');
            const submitBtn = document.getElementById('submitBtn');

            fileInput.addEventListener('change', function(e) {
                if (this.files.length > 0) {
                    fileName.textContent = this.files[0].name;
                    fileName.className = 'text-sm text-green-600 font-semibold mt-3';
                } else {
                    fileName.textContent = 'No file chosen';
                    fileName.className = 'text-sm text-gray-500 mt-3';
                }
            });

            // Form submission handling
            document.getElementById('inviteForm').addEventListener('submit', function(e) {
                const file = fileInput.files[0];
                if (!file) {
                    e.preventDefault();
                    alert('Please select a file to upload.');
                    return;
                }

                // Show loading state
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-3"></i>Sending Invitations...';
                submitBtn.disabled = true;
                submitBtn.classList.remove('hover:scale-105', 'hover:from-indigo-700', 'hover:to-purple-700');
                
                // Simulate processing (in real app, this would be handled by the backend)
                setTimeout(() => {
                    alert('Invitations sent successfully!');
                }, 2000);
            });

            // Drag and drop functionality
            const uploadArea = document.querySelector('form .border-dashed');
            
            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('border-indigo-400', 'bg-indigo-50');
            });

            uploadArea.addEventListener('dragleave', () => {
                uploadArea.classList.remove('border-indigo-400', 'bg-indigo-50');
            });

            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('border-indigo-400', 'bg-indigo-50');
                
                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    fileInput.files = files;
                    fileName.textContent = files[0].name;
                    fileName.className = 'text-sm text-green-600 font-semibold mt-3';
                }
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(UPLOAD_HTML)

@app.route('/dashboard')
def admin_dashboard():
    """Enhanced Admin Dashboard with Time Range Filters and Exceeded Status"""
    # Get filter parameters
    time_filter = request.args.get('time_filter', 'today')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    start_time = request.args.get('start_time', '00:00')
    end_time = request.args.get('end_time', '23:59')
    chart_type = request.args.get('chart_type', 'all')
    
    analytics = get_visitor_analytics(time_filter, start_date, end_date, start_time, end_time)
    DASHBOARD_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Workspace Intelligence Analytics Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            .metric-card {
                transition: all 0.3s ease;
                border-left: 4px solid;
            }
            .metric-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
            }
            .chart-container {
                background: white;
                border-radius: 12px;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            }
            .filter-active {
                background-color: #3B82F6;
                color: white;
            }
            .tab-active {
                border-bottom: 3px solid #3B82F6;
                color: #3B82F6;
                font-weight: 600;
            }
            .time-exceeded {
                background: linear-gradient(135deg, #EF4444, #DC2626);
                color: white;
            }
            .toggle-track {
                width: 44px; height: 24px;
                border-radius: 12px;
                background: #D1D5DB;
                cursor: pointer;
                transition: background 0.3s;
                position: relative;
                flex-shrink: 0;
            }
            .toggle-track.active { background: #10B981; }
            .toggle-knob {
                width: 18px; height: 18px;
                border-radius: 50%;
                background: white;
                position: absolute; top: 3px; left: 3px;
                transition: transform 0.3s;
                box-shadow: 0 1px 3px rgba(0,0,0,.3);
            }
            .toggle-track.active .toggle-knob { transform: translateX(20px); }
            .mock-badge {
                display: inline-flex; align-items: center;
                font-size: 0.7rem; font-weight: 600;
                padding: 1px 8px; border-radius: 9999px;
            }
            .mock-badge.on  { background: #10B981; color: white; }
            .mock-badge.off { background: #E5E7EB; color: #6B7280; }
        </style>
    </head>
    <body class="bg-gray-50 min-h-screen">
        <!-- Header -->
        <div class="bg-white shadow-sm border-b">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div class="flex justify-between items-center py-4">
                    <div>
                        <a href="{{ url_for('index') }}" class="text-gray-500 hover:text-gray-700 text-sm inline-flex items-center mb-1">
                            <i class="fas fa-arrow-left mr-1"></i>Back to Admin
                        </a>
                        <h1 class="text-2xl font-bold text-gray-900">Workspace Intelligence Analytics</h1>
                        <p class="text-sm text-gray-600">Comprehensive visitor insights with time range filters</p>
                    </div>
                    <div class="flex items-center gap-4">
                        <!-- Mock Data Toggle -->
                        <div class="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-1.5 border border-gray-200">
                            <span class="text-xs text-gray-500 font-medium">Demo</span>
                            <div id="mockToggle" class="toggle-track {{ 'active' if use_mock else '' }}" onclick="toggleMockData()">
                                <div class="toggle-knob"></div>
                            </div>
                            <span id="mockBadge" class="mock-badge {{ 'on' if use_mock else 'off' }}">
                                {{ 'MOCK' if use_mock else 'LIVE' }}
                            </span>
                        </div>
                        <a href="{{ url_for('blacklist_page') }}" class="text-red-600 hover:text-red-800 font-medium flex items-center">
                            <i class="fas fa-ban mr-2"></i>Blacklisted
                        </a>
                        <a href="{{ url_for('visitors_list') }}" class="text-blue-600 hover:text-blue-800 font-medium flex items-center">
                            <i class="fas fa-users mr-2"></i>View Visitors
                        </a>
                    </div>
                </div>
            </div>
        </div>

        <div class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
            <!-- Time Period Selector -->
            <div class="bg-white rounded-xl shadow p-6 mb-8">
                <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6">
                    <div>
                        <h2 class="text-lg font-semibold text-gray-900">Analytics Overview</h2>
                        <p class="text-sm text-gray-600" id="filterDescription">{{ analytics.filter_description }}</p>
                    </div>
                    
                    <div class="flex flex-col gap-4 w-full lg:w-auto">
                        <!-- Quick Time Filters -->
                        <div class="flex flex-wrap gap-2">
                            <button onclick="applyTimeFilter('today')" 
                                    class="px-3 py-2 text-sm rounded-lg transition {{ 'filter-active' if time_filter == 'today' else 'bg-gray-100 hover:bg-gray-200' }}">
                                Today
                            </button>
                            <button onclick="applyTimeFilter('week')" 
                                    class="px-3 py-2 text-sm rounded-lg transition {{ 'filter-active' if time_filter == 'week' else 'bg-gray-100 hover:bg-gray-200' }}">
                                This Week
                            </button>
                            <button onclick="applyTimeFilter('month')" 
                                    class="px-3 py-2 text-sm rounded-lg transition {{ 'filter-active' if time_filter == 'month' else 'bg-gray-100 hover:bg-gray-200' }}">
                                This Month
                            </button>
                            <button onclick="applyTimeFilter('year')" 
                                    class="px-3 py-2 text-sm rounded-lg transition {{ 'filter-active' if time_filter == 'year' else 'bg-gray-100 hover:bg-gray-200' }}">
                                This Year
                            </button>
                            <button onclick="applyTimeFilter('all')" 
                                    class="px-3 py-2 text-sm rounded-lg transition {{ 'filter-active' if time_filter == 'all' else 'bg-gray-100 hover:bg-gray-200' }}">
                                All Time
                            </button>
                        </div>
                        
                        <!-- Date and Time Range -->
                        <div class="flex flex-col sm:flex-row gap-4 items-start sm:items-center">
                            <!-- Date Range -->
                            <div class="flex items-center gap-2">
                                <input type="date" id="startDate" value="{{ start_date }}" 
                                       class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                                <span class="text-gray-500">to</span>
                                <input type="date" id="endDate" value="{{ end_date }}" 
                                       class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                            </div>
                            
                            <!-- Time Range -->
                            <div class="flex items-center gap-2">
                                <input type="time" id="startTime" value="{{ start_time }}" 
                                       class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                                <span class="text-gray-500">to</span>
                                <input type="time" id="endTime" value="{{ end_time }}" 
                                       class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500">
                            </div>
                            
                            <button onclick="applyCustomRange()" 
                                    class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm">
                                Apply Filters
                            </button>
                        </div>
                    </div>
                </div>
                
                <!-- Chart Type Tabs -->
                <div class="mt-6 border-b border-gray-200">
                    <div class="flex space-x-8">
                        <button onclick="setChartType('all')" 
                                class="py-2 px-1 text-sm font-medium {{ 'tab-active' if chart_type == 'all' else 'text-gray-500 hover:text-gray-700' }}">
                            All Charts
                        </button>
                        <button onclick="setChartType('purpose')" 
                                class="py-2 px-1 text-sm font-medium {{ 'tab-active' if chart_type == 'purpose' else 'text-gray-500 hover:text-gray-700' }}">
                            Purpose Analysis
                        </button>
                        <button onclick="setChartType('status')" 
                                class="py-2 px-1 text-sm font-medium {{ 'tab-active' if chart_type == 'status' else 'text-gray-500 hover:text-gray-700' }}">
                            Status Overview
                        </button>
                        <button onclick="setChartType('department')" 
                                class="py-2 px-1 text-sm font-medium {{ 'tab-active' if chart_type == 'department' else 'text-gray-500 hover:text-gray-700' }}">
                            Department View
                        </button>
                        <button onclick="setChartType('trends')" 
                                class="py-2 px-1 text-sm font-medium {{ 'tab-active' if chart_type == 'trends' else 'text-gray-500 hover:text-gray-700' }}">
                            Trends
                        </button>
                    </div>
                </div>
            </div>

            <!-- Stats Grid -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                <!-- Total Visitors in Period -->
                <div class="metric-card bg-white rounded-xl p-6 border-l-blue-500">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center">
                            <div class="flex-shrink-0 p-3 bg-blue-100 rounded-lg">
                                <i class="fas fa-users text-blue-600 text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <p class="text-sm font-medium text-gray-600">Visitors in Period</p>
                                <p class="text-2xl font-bold text-gray-900">{{ analytics.period_visitors }}</p>
                            </div>
                        </div>
                    </div>
                    <div class="text-xs text-gray-500">
                        Selected time range
                    </div>
                </div>

                <!-- Active Now -->
                <div class="metric-card bg-white rounded-xl p-6 border-l-green-500">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center">
                            <div class="flex-shrink-0 p-3 bg-green-100 rounded-lg">
                                <i class="fas fa-user-check text-green-600 text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <p class="text-sm font-medium text-gray-600">Currently Active</p>
                                <p class="text-2xl font-bold text-gray-900"><span id="occupancy-count">{{ analytics.currently_checked_in }}</span></p>
                            </div>
                        </div>
                        <div class="text-green-500">
                            <i class="fas fa-circle animate-pulse"></i>
                        </div>
                    </div>
                    <div class="text-xs text-gray-500">
                        Visitors on premises
                    </div>
                </div>

                <!-- Time Exceeded -->
                <div class="metric-card time-exceeded rounded-xl p-6 border-l-red-500">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center">
                            <div class="flex-shrink-0 p-3 bg-red-100 rounded-lg">
                                <i class="fas fa-clock text-red-600 text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <p class="text-sm font-medium text-white">Time Exceeded</p>
                                <p class="text-2xl font-bold text-white">{{ analytics.time_exceeded_count }}</p>
                            </div>
                        </div>
                        <div class="text-white">
                            <i class="fas fa-exclamation-triangle"></i>
                        </div>
                    </div>
                    <div class="text-xs text-red-100">
                        Visitors exceeded duration
                    </div>
                </div>

                <!-- Checked Out -->
                <div class="metric-card bg-white rounded-xl p-6 border-l-purple-500">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center">
                            <div class="flex-shrink-0 p-3 bg-purple-100 rounded-lg">
                                <i class="fas fa-calendar-check text-purple-600 text-xl"></i>
                            </div>
                            <div class="ml-4">
                                <p class="text-sm font-medium text-gray-600">Completed Visits</p>
                                <p class="text-2xl font-bold text-gray-900">{{ analytics.checked_out_count }}</p>
                            </div>
                        </div>
                    </div>
                    <div class="text-xs text-gray-500">
                        Successful visits in period
                    </div>
                </div>
            </div>

            <!-- Second Row Stats -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                <!-- Avg Visit Duration -->
                <div class="metric-card bg-white rounded-xl p-6 border-l-orange-500">
                    <div class="flex items-center">
                        <div class="flex-shrink-0 p-3 bg-orange-100 rounded-lg">
                            <i class="fas fa-clock text-orange-600 text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Avg Visit Duration</p>
                            <p class="text-2xl font-bold text-gray-900">{{ analytics.avg_visit_duration }}</p>
                        </div>
                    </div>
                    <div class="text-xs text-gray-500 mt-2">
                        Average time spent
                    </div>
                </div>

                <!-- Peak Hour -->
                <div class="metric-card bg-white rounded-xl p-6 border-l-indigo-500">
                    <div class="flex items-center">
                        <div class="flex-shrink-0 p-3 bg-indigo-100 rounded-lg">
                            <i class="fas fa-chart-line text-indigo-600 text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Peak Hour</p>
                            <p class="text-2xl font-bold text-gray-900">{{ analytics.peak_hour }}</p>
                        </div>
                    </div>
                    <div class="text-xs text-gray-500 mt-2">
                        Most active time
                    </div>
                </div>

                <!-- Blacklisted -->
                <div class="metric-card bg-white rounded-xl p-6 border-l-red-500">
                    <div class="flex items-center">
                        <div class="flex-shrink-0 p-3 bg-red-100 rounded-lg">
                            <i class="fas fa-ban text-red-600 text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Blacklisted</p>
                            <p class="text-2xl font-bold text-gray-900">{{ analytics.blacklisted_count }}</p>
                        </div>
                    </div>
                    <div class="text-xs text-gray-500 mt-2">
                        Restricted visitors
                    </div>
                </div>

                <!-- Multiple Visits -->
                <div class="metric-card bg-white rounded-xl p-6 border-l-pink-500">
                    <div class="flex items-center">
                        <div class="flex-shrink-0 p-3 bg-pink-100 rounded-lg">
                            <i class="fas fa-redo text-pink-600 text-xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-gray-600">Multiple Visits</p>
                            <p class="text-2xl font-bold text-gray-900">{{ analytics.multiple_visits_count }}</p>
                        </div>
                    </div>
                    <div class="text-xs text-gray-500 mt-2">
                        2+ visits in period
                    </div>
                </div>
            </div>

            <!-- Charts Section - Dynamic based on selected tab -->
            <div id="allCharts" class="{{ 'block' if chart_type == 'all' else 'hidden' }}">
                <div class="grid grid-cols-1 xl:grid-cols-2 gap-8 mb-8">
                    <!-- Purpose Distribution -->
                    <div class="chart-container p-6">
                        <div class="flex justify-between items-center mb-6">
                            <h3 class="text-lg font-semibold text-gray-900">Visit Purpose Distribution</h3>
                            <div class="text-sm text-gray-500 flex items-center">
                                <i class="fas fa-chart-pie mr-2"></i>
                                {{ analytics.filter_description }}
                            </div>
                        </div>
                        <div class="h-80">
                            <canvas id="purposeChart"></canvas>
                        </div>
                    </div>

                    <!-- Status Distribution -->
                    <div class="chart-container p-6">
                        <div class="flex justify-between items-center mb-6">
                            <h3 class="text-lg font-semibold text-gray-900">Visitor Status Overview</h3>
                            <div class="text-sm text-gray-500 flex items-center">
                                <i class="fas fa-chart-bar mr-2"></i>
                                {{ analytics.filter_description }}
                            </div>
                        </div>
                        <div class="h-80">
                            <canvas id="statusChart"></canvas>
                        </div>
                    </div>
                </div>

                <!-- Additional Charts Row -->
                <div class="grid grid-cols-1 xl:grid-cols-2 gap-8 mb-8">
                    <!-- Department Distribution -->
                    <div class="chart-container p-6">
                        <div class="flex justify-between items-center mb-6">
                            <h3 class="text-lg font-semibold text-gray-900">Department-wise Visitors</h3>
                            <div class="text-sm text-gray-500 flex items-center">
                                <i class="fas fa-sitemap mr-2"></i>
                                {{ analytics.filter_description }}
                            </div>
                        </div>
                        <div class="h-80">
                            <canvas id="departmentChart"></canvas>
                        </div>
                    </div>

                    <!-- Hourly Distribution -->
                    <div class="chart-container p-6">
                        <div class="flex justify-between items-center mb-6">
                            <h3 class="text-lg font-semibold text-gray-900">Hourly Visitor Distribution</h3>
                            <div class="text-sm text-gray-500 flex items-center">
                                <i class="fas fa-chart-line mr-2"></i>
                                {{ analytics.filter_description }}
                            </div>
                        </div>
                        <div class="h-80">
                            <canvas id="hourlyChart"></canvas>
                        </div>
                    </div>

                    <!-- Occupancy over time (last 24 hours) -->
                    <div class="chart-container p-6">
                        <div class="flex justify-between items-center mb-2">
                            <h3 class="text-lg font-semibold text-gray-900">Occupancy over time (last 24 hours)</h3>
                            <div class="text-sm text-gray-500 flex items-center">
                                <i class="fas fa-users mr-2"></i>
                                Rolling 24h
                            </div>
                        </div>
                        <p class="text-sm text-gray-500 mb-4">Number of visitors present in the building in each hour (checked in and not yet checked out).</p>
                        <div class="h-80">
                            <canvas id="occupancyOverTimeChart"></canvas>
                        </div>
                    </div>

                    <!-- Occupancy over selected date/range -->
                    <div class="chart-container p-6">
                        <div class="flex justify-between items-center mb-2">
                            <h3 class="text-lg font-semibold text-gray-900">Occupancy over selected period</h3>
                            <div class="text-sm text-gray-500 flex items-center">
                                <i class="fas fa-calendar-alt mr-2"></i>
                                {{ analytics.filter_description }}
                            </div>
                        </div>
                        <p class="text-sm text-gray-500 mb-4">Visitors present in the building by hour (single day) or by day (multi-day). Uses the current time filter above.</p>
                        <div class="flex gap-2 mb-2">
                            <button type="button" onclick="exportOccupancyCSV('last24')" class="text-sm text-purple-600 hover:underline">Export last 24h CSV</button>
                            <button type="button" onclick="exportOccupancyCSV('period')" class="text-sm text-purple-600 hover:underline">Export selected period CSV</button>
                        </div>
                        <div class="h-80">
                            <canvas id="occupancyOverTimePeriodChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Individual Chart Views -->
            <div id="purposeChartView" class="{{ 'block' if chart_type == 'purpose' else 'hidden' }}">
                <div class="chart-container p-6">
                    <div class="flex justify-between items-center mb-6">
                        <h3 class="text-lg font-semibold text-gray-900">Visit Purpose Analysis</h3>
                        <div class="text-sm text-gray-500 flex items-center">
                            <i class="fas fa-chart-pie mr-2"></i>
                            {{ analytics.filter_description }}
                        </div>
                    </div>
                    <div class="h-96">
                        <canvas id="purposeChartSingle"></canvas>
                    </div>
                </div>
            </div>

            <div id="statusChartView" class="{{ 'block' if chart_type == 'status' else 'hidden' }}">
                <div class="chart-container p-6">
                    <div class="flex justify-between items-center mb-6">
                        <h3 class="text-lg font-semibold text-gray-900">Visitor Status Analysis</h3>
                        <div class="text-sm text-gray-500 flex items-center">
                            <i class="fas fa-chart-bar mr-2"></i>
                            {{ analytics.filter_description }}
                        </div>
                    </div>
                    <div class="h-96">
                        <canvas id="statusChartSingle"></canvas>
                    </div>
                </div>
            </div>

            <div id="departmentChartView" class="{{ 'block' if chart_type == 'department' else 'hidden' }}">
                <div class="chart-container p-6">
                    <div class="flex justify-between items-center mb-6">
                        <h3 class="text-lg font-semibold text-gray-900">Department Visitor Analysis</h3>
                        <div class="text-sm text-gray-500 flex items-center">
                            <i class="fas fa-sitemap mr-2"></i>
                            {{ analytics.filter_description }}
                        </div>
                    </div>
                    <div class="h-96">
                        <canvas id="departmentChartSingle"></canvas>
                    </div>
                </div>
            </div>

            <div id="trendsChartView" class="{{ 'block' if chart_type == 'trends' else 'hidden' }}">
                <div class="chart-container p-6">
                    <div class="flex justify-between items-center mb-6">
                        <h3 class="text-lg font-semibold text-gray-900">Time-based Visitor Analysis</h3>
                        <div class="text-sm text-gray-500 flex items-center">
                            <i class="fas fa-chart-line mr-2"></i>
                            {{ analytics.filter_description }}
                        </div>
                    </div>
                    <div class="h-96">
                        <canvas id="trendsChartSingle"></canvas>
                    </div>
                </div>
            </div>

            <!-- Recent Activity & Time Exceeded Visitors -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-8">
                <!-- Recent Activity -->
                <div class="chart-container p-6">
                    <h3 class="text-lg font-semibold text-gray-900 mb-6">Recent Check-ins</h3>
                    <div class="space-y-4">
                        {% for activity in analytics.recent_activities %}
                        <div class="flex items-center space-x-4 p-3 bg-gray-50 rounded-lg">
                            <div class="flex-shrink-0">
                                <div class="h-10 w-10 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-bold">
                                    {{ activity.visitor_name[0]|upper if activity.visitor_name else '?' }}
                                </div>
                            </div>
                            <div class="flex-1 min-w-0">
                                <p class="text-sm font-medium text-gray-900">{{ activity.visitor_name or 'Unknown' }}</p>
                                <p class="text-sm text-gray-500">{{ activity.purpose or 'No purpose specified' }}</p>
                            </div>
                            <div class="text-right">
                                <p class="text-sm font-medium text-gray-900">{{ activity.status or 'Unknown' }}</p>
                                <p class="text-xs text-gray-400">{{ activity.time or 'Recently' }}</p>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>

                <!-- Time Exceeded Visitors -->
                <div class="chart-container p-6">
                    <h3 class="text-lg font-semibold text-gray-900 mb-6">Time Exceeded Visitors</h3>
                    <div class="space-y-4">
                        {% for visitor in analytics.time_exceeded_visitors %}
                        <div class="flex items-center justify-between p-3 bg-red-50 rounded-lg border border-red-200">
                            <div class="flex items-center space-x-3">
                                <div class="flex-shrink-0">
                                    <div class="h-10 w-10 bg-gradient-to-r from-red-500 to-orange-600 rounded-full flex items-center justify-center text-white font-bold">
                                        {{ visitor.name[0]|upper if visitor.name else '?' }}
                                    </div>
                                </div>
                                <div>
                                    <p class="text-sm font-medium text-gray-900">{{ visitor.name or 'Unknown' }}</p>
                                    <p class="text-xs text-red-600 font-semibold">Exceeded by {{ visitor.exceeded_by }}</p>
                                </div>
                            </div>
                            <div class="text-right flex items-center gap-3">
                                <div>
                                    <p class="text-sm font-bold text-red-600">{{ visitor.duration }}</p>
                                    <p class="text-xs text-gray-400">Expected: {{ visitor.expected_duration }}</p>
                                </div>
                                {% if visitor.visitor_id and visitor.employee_name %}
                                <button type="button" class="notify-host-btn px-3 py-1.5 text-xs font-medium bg-amber-600 hover:bg-amber-700 text-white rounded" data-visitor-id="{{ visitor.visitor_id }}">Notify host</button>
                                {% endif %}
                            </div>
                        </div>
                        {% endfor %}
                        {% if not analytics.time_exceeded_visitors %}
                        <div class="text-center py-8 text-gray-500">
                            <i class="fas fa-check-circle text-2xl mb-2"></i>
                            <p>No time exceeded visitors</p>
                        </div>
                        {% endif %}
                    </div>
                </div>
            </div>

            <!-- Room utilization -->
            <div class="mt-8">
                <div class="chart-container p-6">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="text-lg font-semibold text-gray-900">Room utilization</h3>
                        <div class="flex items-center gap-2">
                            <button type="button" onclick="exportRoomUtilizationCSV()" class="text-sm text-teal-600 hover:underline">Export CSV</button>
                            <a href="{{ url_for('rooms_list') }}" class="text-sm text-teal-600 hover:underline">Manage rooms</a>
                        </div>
                    </div>
                    <p class="text-sm text-gray-500 mb-4">Visits per meeting room in the selected period.</p>
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead class="bg-gray-50">
                                <tr>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Room</th>
                                    <th class="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Visits</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-200">
                                {% for r in (analytics.get('room_utilization_analytics') or []) %}
                                <tr class="hover:bg-gray-50">
                                    <td class="px-4 py-2 text-sm font-medium text-gray-900">{{ r.room_name or r.room_id }}</td>
                                    <td class="px-4 py-2 text-sm text-right text-gray-600">{{ r.visit_count }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                        {% if not (analytics.get('room_utilization_analytics')) %}
                        <p class="py-4 text-gray-500 text-sm">No room data in this period. <a href="{{ url_for('rooms_list') }}" class="text-teal-600 hover:underline">Add rooms</a> and link visits to them.</p>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>

        <script>
            // Initialize all charts
            document.addEventListener('DOMContentLoaded', function() {
                initializeCharts();
            });

            function initializeCharts() {
                // Purpose Distribution Chart
                initializePurposeChart('purposeChart');
                initializePurposeChart('purposeChartSingle');
                
                // Status Distribution Chart
                initializeStatusChart('statusChart');
                initializeStatusChart('statusChartSingle');
                
                // Department Distribution Chart
                initializeDepartmentChart('departmentChart');
                initializeDepartmentChart('departmentChartSingle');
                
                // Hourly Distribution Chart
                initializeHourlyChart('hourlyChart');
                initializeHourlyChart('trendsChartSingle');
                initializeOccupancyOverTimeChart();
                initializeOccupancyPeriodChart();
            }

            function initializePurposeChart(canvasId) {
                const ctx = document.getElementById(canvasId).getContext('2d');
                new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: {{ analytics.purpose_categories.keys()|list|tojson }},
                        datasets: [{
                            data: {{ analytics.purpose_categories.values()|list|tojson }},
                            backgroundColor: [
                                '#3B82F6', // Meetings - Blue
                                '#10B981', // Interviews - Green
                                '#8B5CF6', // Employee Meetings - Purple
                                '#F59E0B', // Deliveries - Orange
                                '#EF4444', // Maintenance - Red
                                '#06B6D4'  // Other - Cyan
                            ],
                            borderWidth: 3,
                            borderColor: '#fff'
                        }]
                    },
                    options: getChartOptions('Purpose Distribution')
                });
            }

            function initializeStatusChart(canvasId) {
                const ctx = document.getElementById(canvasId).getContext('2d');
                new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: {{ analytics.status_distribution.keys()|list|tojson }},
                        datasets: [{
                            label: 'Number of Visitors',
                            data: {{ analytics.status_distribution.values()|list|tojson }},
                            backgroundColor: [
                                '#3B82F6', // Registered - Blue
                                '#10B981', // Approved - Green
                                '#8B5CF6', // Checked-In - Purple
                                '#F59E0B', // Checked-Out - Orange
                                '#EF4444', // Time Exceeded - Red
                                '#06B6D4', // Rescheduled - Cyan
                                '#84CC16'  // Rejected - Lime
                            ],
                            borderColor: [
                                '#1D4ED8', '#047857', '#7C3AED', '#D97706', 
                                '#DC2626', '#0891B2', '#65A30D'
                            ],
                            borderWidth: 1,
                            borderRadius: 4
                        }]
                    },
                    options: getChartOptions('Status Distribution', true)
                });
            }

            function initializeDepartmentChart(canvasId) {
                const ctx = document.getElementById(canvasId).getContext('2d');
                new Chart(ctx, {
                    type: 'pie',
                    data: {
                        labels: {{ analytics.department_distribution.keys()|list|tojson }},
                        datasets: [{
                            data: {{ analytics.department_distribution.values()|list|tojson }},
                            backgroundColor: [
                                '#3B82F6', '#10B981', '#8B5CF6', '#F59E0B', 
                                '#EF4444', '#06B6D4', '#84CC16', '#F97316'
                            ],
                            borderWidth: 2,
                            borderColor: '#fff'
                        }]
                    },
                    options: getChartOptions('Department Distribution')
                });
            }

            function initializeHourlyChart(canvasId) {
                const ctx = document.getElementById(canvasId).getContext('2d');
                new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: {{ analytics.hourly_distribution.labels|tojson }},
                        datasets: [{
                            label: 'Visitors',
                            data: {{ analytics.hourly_distribution.data|tojson }},
                            borderColor: '#3B82F6',
                            backgroundColor: 'rgba(59, 130, 246, 0.1)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.4,
                            pointBackgroundColor: '#3B82F6',
                            pointBorderColor: '#fff',
                            pointBorderWidth: 2,
                            pointRadius: 4
                        }]
                    },
                    options: getChartOptions('Hourly Visitor Distribution', true)
                });
            }

            function initializeOccupancyOverTimeChart() {
                const occ = {{ (analytics.get('occupancy_over_time_last24') or {'labels': [], 'data': []})|tojson }};
                const ctx = document.getElementById('occupancyOverTimeChart');
                if (!ctx) return;
                new Chart(ctx.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: occ.labels || [],
                        datasets: [{
                            label: 'Occupancy',
                            data: occ.data || [],
                            borderColor: '#10B981',
                            backgroundColor: 'rgba(16, 185, 129, 0.15)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.4,
                            pointBackgroundColor: '#10B981',
                            pointBorderColor: '#fff',
                            pointBorderWidth: 2,
                            pointRadius: 4
                        }]
                    },
                    options: getChartOptions('Occupancy over time (last 24h)', true)
                });
            }
            function initializeOccupancyPeriodChart() {
                const occ = {{ (analytics.get('occupancy_over_time_period') or {'labels': [], 'data': []})|tojson }};
                const ctx = document.getElementById('occupancyOverTimePeriodChart');
                if (!ctx) return;
                new Chart(ctx.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: occ.labels || [],
                        datasets: [{
                            label: 'Occupancy',
                            data: occ.data || [],
                            borderColor: '#8B5CF6',
                            backgroundColor: 'rgba(139, 92, 246, 0.15)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.4,
                            pointBackgroundColor: '#8B5CF6',
                            pointBorderColor: '#fff',
                            pointBorderWidth: 2,
                            pointRadius: 4
                        }]
                    },
                    options: getChartOptions('Occupancy (selected period)', true)
                });
            }

            function getChartOptions(title, showGrid = false) {
                return {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                padding: 20,
                                usePointStyle: true,
                                font: { size: 11 }
                            }
                        },
                        title: {
                            display: true,
                            text: title,
                            font: { size: 16, weight: 'bold' }
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.raw || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
                                    return `${label}: ${value} (${percentage}%)`;
                                }
                            }
                        }
                    },
                    scales: showGrid ? {
                        y: {
                            beginAtZero: true,
                            ticks: { stepSize: 1 },
                            grid: { drawBorder: false }
                        },
                        x: {
                            grid: { display: false }
                        }
                    } : {}
                };
            }

            // Filter Functions
            function applyTimeFilter(filter) {
                const params = new URLSearchParams();
                params.append('time_filter', filter);
                params.append('chart_type', '{{ chart_type }}');
                // Preserve time range if set
                const startTime = document.getElementById('startTime').value;
                const endTime = document.getElementById('endTime').value;
                if (startTime && endTime) {
                    params.append('start_time', startTime);
                    params.append('end_time', endTime);
                }
                window.location.href = `${window.location.pathname}?${params.toString()}`;
            }

            function applyCustomRange() {
                const startDate = document.getElementById('startDate').value;
                const endDate = document.getElementById('endDate').value;
                const startTime = document.getElementById('startTime').value;
                const endTime = document.getElementById('endTime').value;
                
                if (!startDate || !endDate) {
                    alert('Please select both start and end dates');
                    return;
                }
                
                const params = new URLSearchParams();
                params.append('time_filter', 'custom');
                params.append('start_date', startDate);
                params.append('end_date', endDate);
                params.append('start_time', startTime);
                params.append('end_time', endTime);
                params.append('chart_type', '{{ chart_type }}');
                window.location.href = `${window.location.pathname}?${params.toString()}`;
            }

            function setChartType(type) {
                const params = new URLSearchParams(window.location.search);
                params.set('chart_type', type);
                window.location.href = `${window.location.pathname}?${params.toString()}`;
            }

            function refreshData() {
                location.reload();
            }

            // Set default time values if not set
            document.addEventListener('DOMContentLoaded', function() {
                const startTime = document.getElementById('startTime');
                const endTime = document.getElementById('endTime');
                
                if (!startTime.value) startTime.value = '00:00';
                if (!endTime.value) endTime.value = '23:59';
            });

            // Real-time occupancy: poll /api/occupancy every 5 seconds
            function updateOccupancy() {
                fetch('/api/occupancy')
                    .then(function(r) { return r.ok ? r.json() : Promise.reject(r); })
                    .then(function(data) {
                        var el = document.getElementById('occupancy-count');
                        if (el) el.textContent = data.current_occupancy;
                    })
                    .catch(function(err) { if (console && console.log) console.log('Occupancy fetch failed', err); });
            }
            setInterval(updateOccupancy, 5000);

            document.addEventListener('click', function(e) {
                var btn = e.target.closest('.notify-host-btn');
                if (!btn || btn.disabled) return;
                var vid = btn.getAttribute('data-visitor-id');
                if (!vid) return;
                btn.disabled = true;
                btn.textContent = 'Sending...';
                fetch('/api/notify_host_time_exceeded', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ visitor_id: vid }) })
                    .then(function(r) { return r.json().then(function(d) { return r.ok ? d : Promise.reject(d); }); })
                    .then(function(d) { btn.textContent = 'Sent'; if (d.message) alert(d.message); })
                    .catch(function(d) { btn.disabled = false; btn.textContent = 'Notify host'; alert(d.message || 'Failed to send'); });
            });

            var dashboardRoomUtil = {{ (analytics.get('room_utilization_analytics') or [])|tojson }};
            var dashboardOcc24 = {{ (analytics.get('occupancy_over_time_last24') or {'labels': [], 'data': []})|tojson }};
            var dashboardOccPeriod = {{ (analytics.get('occupancy_over_time_period') or {'labels': [], 'data': []})|tojson }};
            function exportRoomUtilizationCSV() {
                var headers = ['Room', 'Visits'];
                var rows = dashboardRoomUtil.map(function(r) { return [r.room_name || r.room_id, r.visit_count]; });
                var csv = [headers.join(','), rows.map(function(r) { return r.map(function(c) { return '"' + String(c).replace(/"/g, '""') + '"'; }).join(','); }).join('\\n')].join('\\n');
                var a = document.createElement('a'); a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv); a.download = 'room_utilization_' + new Date().toISOString().slice(0, 10) + '.csv'; a.click();
            }
            function exportOccupancyCSV(which) {
                var occ = which === 'last24' ? dashboardOcc24 : dashboardOccPeriod;
                var headers = ['Time', 'Occupancy'];
                var rows = (occ.labels || []).map(function(l, i) { return [l, (occ.data || [])[i] ?? 0]; });
                var csv = [headers.join(','), rows.map(function(r) { return r.join(','); }).join('\\n')].join('\\n');
                var a = document.createElement('a'); a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv); a.download = 'occupancy_' + which + '_' + new Date().toISOString().slice(0, 10) + '.csv'; a.click();
            }

            function toggleMockData() {
                var track = document.getElementById('mockToggle');
                var badge = document.getElementById('mockBadge');
                var enabling = !track.classList.contains('active');
                track.style.opacity = '0.5';
                track.style.pointerEvents = 'none';
                fetch('/api/mock_data', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mock: enabling})
                })
                .then(function(r) { return r.json().then(function(d) { return {ok: r.ok, data: d}; }); })
                .then(function(res) {
                    if (!res.ok) { alert(res.data.message || 'Failed'); return; }
                    if (res.data.mock) {
                        track.classList.add('active');
                        badge.className = 'mock-badge on';
                        badge.textContent = 'MOCK';
                    } else {
                        track.classList.remove('active');
                        badge.className = 'mock-badge off';
                        badge.textContent = 'LIVE';
                    }
                    window.location.reload();
                })
                .catch(function(e) { alert('Error: ' + e); })
                .finally(function() {
                    track.style.opacity = '1';
                    track.style.pointerEvents = 'auto';
                });
            }
        </script>
    </body>
    </html>
    """
    resp = make_response(render_template_string(DASHBOARD_HTML, analytics=analytics, time_filter=time_filter,
                                start_date=start_date, end_date=end_date, start_time=start_time,
                                end_time=end_time, chart_type=chart_type, use_mock=USE_MOCK_DATA))
    resp.headers['Cache-Control'] = 'no-store'
    return resp

def get_visitor_analytics(time_filter='today', start_date=None, end_date=None, start_time='00:00', end_time='23:59'):
    """Generate comprehensive analytics data from Firebase database with time range filters"""
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
        all_employees = get_mock_employees()
    else:
        visitors_ref = db.reference('visitors')
        employees_ref = db.reference('employees')
        all_visitors = visitors_ref.get() or {}
        all_employees = employees_ref.get() or {}
    
    today = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now()
    
    # Calculate date ranges based on filter
    date_range = calculate_date_range(time_filter, start_date, end_date, start_time, end_time)
    start_datetime = date_range['start_datetime']
    end_datetime = date_range['end_datetime']
    filter_description = date_range['description']
    
    # Initialize counters
    total_visitors = len(all_visitors)
    currently_checked_in = 0
    blacklisted_count = 0
    period_visitors = 0
    checked_out_count = 0
    pending_count = 0
    multiple_visits_count = 0
    time_exceeded_count = 0
    
    # Purpose categorization
    purpose_categories = {
        'Meetings': 0,
        'Interviews': 0,
        'Employee Meetings': 0,
        'Deliveries': 0,
        'Maintenance': 0,
        'Other': 0
    }
    
    # Status distribution (including Time Exceeded)
    status_distribution = {
        'Registered': 0,
        'Approved': 0,
        'Checked-In': 0,
        'Checked-Out': 0,
        'Time Exceeded': 0,
        'Rescheduled': 0,
        'Rejected': 0
    }
    
    # Department distribution - initialize with actual departments from employees
    department_distribution = {}
    department_employee_map = {}  # Track department -> employee -> visit count
    
    # Room utilization - count visits per room (room_id from visitor or visit)
    room_utilization = {}
    
    # Hourly distribution
    hourly_distribution = {'labels': [], 'data': []}
    for hour in range(24):
        hourly_distribution['labels'].append(f"{hour:02d}:00")
        hourly_distribution['data'].append(0)
    
    # Visit counts for recurring visitors
    visitor_visit_counts = {}
    recent_activities = []
    frequent_visitors = []
    time_exceeded_visitors = []
    
    # Calculate average duration
    total_duration_minutes = 0
    duration_count = 0
    
    # Peak hour tracking
    hourly_counts = {hour: 0 for hour in range(24)}
    
    for visitor_id, visitor_data in all_visitors.items():
        check_in_time_str = visitor_data.get('check_in_time', '')
        check_in_time = None
        check_out_time_str = visitor_data.get('check_out_time', '')
        check_out_time = None
        
        # Parse check-in time
        if check_in_time_str and check_in_time_str != 'N/A':
            try:
                check_in_time = datetime.strptime(check_in_time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
        
        # Parse check-out time
        if check_out_time_str and check_out_time_str != 'N/A':
            try:
                check_out_time = datetime.strptime(check_out_time_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
        
        # Check if visitor is in selected period (considering time range)
        in_period = False
        if check_in_time:
            # Check if within date and time range
            in_period = (start_datetime <= check_in_time <= end_datetime)
            
            # Update hourly distribution
            if in_period:
                hour = check_in_time.hour
                hourly_counts[hour] += 1
                hourly_distribution['data'][hour] += 1
        
        # Basic counts
        status = visitor_data.get('status', 'Registered')
        
        # Check for time exceeded
        is_time_exceeded = False
        expected_checkout_str = visitor_data.get('expected_checkout_time', '')
        if status == 'Checked-In' and expected_checkout_str and expected_checkout_str != 'N/A':
            try:
                expected_checkout = datetime.strptime(expected_checkout_str, '%Y-%m-%d %H:%M:%S')
                if current_time > expected_checkout:
                    is_time_exceeded = True
                    status = 'Time Exceeded'
                    time_exceeded_count += 1
                    
                    # Calculate exceeded time
                    exceeded_minutes = int((current_time - expected_checkout).total_seconds() / 60)
                    exceeded_hours = exceeded_minutes // 60
                    exceeded_remaining_minutes = exceeded_minutes % 60
                    
                    if exceeded_hours > 0:
                        exceeded_by = f"{exceeded_hours}h {exceeded_remaining_minutes}m"
                    else:
                        exceeded_by = f"{exceeded_minutes}m"
                    
                    time_exceeded_visitors.append({
                        'visitor_id': visitor_id,
                        'name': visitor_data.get('name', 'Unknown'),
                        'employee_name': visitor_data.get('employee_name', ''),
                        'duration': visitor_data.get('duration', 'Unknown'),
                        'expected_duration': visitor_data.get('expected_duration', 'Unknown'),
                        'exceeded_by': exceeded_by
                    })
            except ValueError:
                pass
        
        status_distribution[status] = status_distribution.get(status, 0) + 1
        
        if status == 'Checked-In' and not is_time_exceeded:
            currently_checked_in += 1
        
        if status == 'Checked-Out' and in_period:
            checked_out_count += 1
        
        if status in ['Registered', 'Approved'] and in_period:
            pending_count += 1
        
        # Count visitors in period
        if in_period:
            period_visitors += 1
        
        if _is_visitor_blacklisted(visitor_data):
            blacklisted_count += 1
        
        # Purpose categorization
        purpose = visitor_data.get('purpose', '').lower()
        if 'meeting' in purpose:
            if 'employee' in purpose or 'with' in purpose:
                purpose_categories['Employee Meetings'] += 1
            else:
                purpose_categories['Meetings'] += 1
        elif 'interview' in purpose:
            purpose_categories['Interviews'] += 1
        elif 'delivery' in purpose:
            purpose_categories['Deliveries'] += 1
        elif 'maintenance' in purpose:
            purpose_categories['Maintenance'] += 1
        else:
            purpose_categories['Other'] += 1
        
        # Department: prefer visit/visitor record, then employees table, never use person names
        employee_name = visitor_data.get('employee_name', '')
        department = visitor_data.get('department', '') or 'General'
        if department == 'N/A':
            department = 'General'
        employee_found = False

        if department == 'General' and employee_name and employee_name != 'N/A':
            # Look up department from employees table
            for emp_id, emp_data in all_employees.items():
                emp_name = emp_data.get('name', '')
                if emp_name and emp_name.strip().lower() == employee_name.strip().lower():
                    department = emp_data.get('department', 'General')
                    employee_found = True
                    break

            if not employee_found:
                for emp_id, emp_data in all_employees.items():
                    emp_name = emp_data.get('name', '')
                    if emp_name and (employee_name.lower() in emp_name.lower() or emp_name.lower() in employee_name.lower()):
                        department = emp_data.get('department', 'General')
                        employee_found = True
                        break

            # Fallback: keep General; do not use employee name as department
            if not employee_found:
                department = 'General'
        
        if in_period:
            department_distribution[department] = department_distribution.get(department, 0) + 1
            # Room utilization (root or from most recent visit)
            room_id = visitor_data.get('room_id', '') or ''
            if not room_id:
                visits = visitor_data.get('visits', {})
                if visits:
                    sorted_visits = []
                    for v_id, v_data in visits.items():
                        ts = v_data.get('created_at') or v_data.get('check_in_time')
                        if ts:
                            try:
                                sorted_visits.append((datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'), v_data))
                            except ValueError:
                                pass
                    if sorted_visits:
                        sorted_visits.sort(key=lambda x: x[0], reverse=True)
                        room_id = sorted_visits[0][1].get('room_id', '') or ''
            if room_id:
                room_utilization[room_id] = room_utilization.get(room_id, 0) + 1
            
            # Track which employees received visitors
            if employee_found and employee_name:
                if department not in department_employee_map:
                    department_employee_map[department] = {}
                department_employee_map[department][employee_name] = department_employee_map[department].get(employee_name, 0) + 1
        
        # Visit count for recurring visitors
        visitor_name = visitor_data.get('name', 'Unknown')
        if visitor_name and visitor_name != 'N/A':
            visitor_visit_counts[visitor_name] = visitor_visit_counts.get(visitor_name, 0) + 1
        
        # Recent activities (filtered by period)
        if in_period and status in ['Checked-In', 'Checked-Out', 'Time Exceeded'] and check_in_time_str:
            recent_activities.append({
                'visitor_name': visitor_data.get('name', 'Unknown'),
                'purpose': visitor_data.get('purpose', 'No purpose specified'),
                'status': status,
                'time': check_in_time_str
            })
        
        # Calculate duration for average
        if in_period:
            duration = visitor_data.get('duration', '')
            if duration:
                try:
                    if 'hr' in duration:
                        hours = int(duration.replace('hr', '').strip())
                        total_duration_minutes += hours * 60
                        duration_count += 1
                except ValueError:
                    pass
    
    # Sort and limit recent activities
    recent_activities.sort(key=lambda x: x['time'], reverse=True)
    recent_activities = recent_activities[:5]
    
    # Calculate multiple visits in period
    for visitor_name, count in visitor_visit_counts.items():
        if count >= 2:
            # Count how many visits are in the current period
            period_visit_count = 0
            last_visit_in_period = None
            
            for visitor_id, visitor_data in all_visitors.items():
                if visitor_data.get('name') == visitor_name:
                    check_in_time_str = visitor_data.get('check_in_time', '')
                    if check_in_time_str:
                        try:
                            visit_time = datetime.strptime(check_in_time_str, '%Y-%m-%d %H:%M:%S')
                            if start_datetime <= visit_time <= end_datetime:
                                period_visit_count += 1
                                if not last_visit_in_period or visit_time > last_visit_in_period:
                                    last_visit_in_period = visit_time
                        except ValueError:
                            pass
            
            if period_visit_count >= 2:
                multiple_visits_count += 1
                frequent_visitors.append({
                    'name': visitor_name,
                    'visit_count': period_visit_count,
                    'last_visit': last_visit_in_period.strftime('%Y-%m-%d %H:%M') if last_visit_in_period else 'Unknown'
                })
    
    # Sort frequent visitors by visit count
    frequent_visitors.sort(key=lambda x: x['visit_count'], reverse=True)
    frequent_visitors = frequent_visitors[:5]
    
    # Calculate average duration
    avg_duration_minutes = total_duration_minutes / duration_count if duration_count > 0 else 0
    avg_duration_hours = avg_duration_minutes / 60
    avg_visit_duration = f"{avg_duration_hours:.1f} hrs" if avg_duration_hours >= 1 else f"{avg_duration_minutes:.0f} mins"
    
    # Find peak hour
    peak_hour_count = max(hourly_counts.values()) if hourly_counts else 0
    peak_hours = [hour for hour, count in hourly_counts.items() if count == peak_hour_count]
    peak_hour = f"{peak_hours[0]:02d}:00" if peak_hours else "N/A"
    
    # Prepare department analytics
    department_analytics = []
    for department, visitor_count in department_distribution.items():
        employee_visitors = department_employee_map.get(department, {})
        active_employees = len(employee_visitors)
        top_employees = sorted(employee_visitors.items(), key=lambda x: x[1], reverse=True)[:3]
        
        department_analytics.append({
            'department': department,
            'visitor_count': visitor_count,
            'active_employees': active_employees,
            'top_employees': top_employees
        })
    
    # Sort departments by visitor count
    department_analytics.sort(key=lambda x: x['visitor_count'], reverse=True)
    
    # Room utilization analytics (name from meeting_rooms)
    all_rooms = get_meeting_rooms()
    room_utilization_analytics = []
    for rid, count in room_utilization.items():
        room_info = all_rooms.get(rid, {})
        room_utilization_analytics.append({
            'room_id': rid,
            'room_name': room_info.get('name', rid),
            'visit_count': count
        })
    room_utilization_analytics.sort(key=lambda x: x['visit_count'], reverse=True)
    
    result = {
        'total_visitors': total_visitors,
        'currently_checked_in': currently_checked_in,
        'blacklisted_count': blacklisted_count,
        'period_visitors': period_visitors,
        'checked_out_count': checked_out_count,
        'pending_count': pending_count,
        'multiple_visits_count': multiple_visits_count,
        'time_exceeded_count': time_exceeded_count,
        'avg_visit_duration': avg_visit_duration,
        'peak_hour': peak_hour,
        'purpose_categories': purpose_categories,
        'status_distribution': status_distribution,
        'department_distribution': department_distribution,
        'department_analytics': department_analytics,
        'hourly_distribution': hourly_distribution,
        'recent_activities': recent_activities,
        'frequent_visitors': frequent_visitors,
        'time_exceeded_visitors': time_exceeded_visitors,
        'filter_description': filter_description,
        'room_utilization_analytics': room_utilization_analytics
    }

    # Occupancy over time: last 24 hours (rolling), one bucket per hour
    occupancy_labels = []
    occupancy_data = []
    for k in range(24):
        bucket_end = current_time - timedelta(hours=23 - k)
        bucket_start = current_time - timedelta(hours=24 - k)
        occupancy_labels.append(bucket_start.strftime('%H:%M'))
        count = 0
        for vid, vdata in all_visitors.items():
            check_in_str = vdata.get('check_in_time', '')
            visits = vdata.get('visits', {})
            if not check_in_str or check_in_str == 'N/A':
                if visits:
                    sorted_visits = []
                    for visit_id, visit_data in visits.items():
                        ts = visit_data.get('created_at') or visit_data.get('check_in_time')
                        if ts:
                            try:
                                sorted_visits.append((datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'), visit_data))
                            except ValueError:
                                pass
                    if sorted_visits:
                        sorted_visits.sort(key=lambda x: x[0], reverse=True)
                        _, recent = sorted_visits[0]
                        check_in_str = recent.get('check_in_time', '')
                        check_out_str = recent.get('check_out_time', '')
                    else:
                        continue
                else:
                    continue
            else:
                check_out_str = vdata.get('check_out_time', '')
            if not check_in_str or check_in_str == 'N/A':
                continue
            try:
                check_in_dt = datetime.strptime(check_in_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
            if check_out_str and check_out_str != 'N/A':
                try:
                    check_out_dt = datetime.strptime(check_out_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    check_out_dt = current_time
            else:
                check_out_dt = current_time
            if check_in_dt <= bucket_end and check_out_dt >= bucket_start:
                count += 1
        occupancy_data.append(count)
    result['occupancy_over_time_last24'] = {'labels': occupancy_labels, 'data': occupancy_data}

    # Occupancy over selected date/range (respects dashboard time filter)
    period_occ_labels = []
    period_occ_data = []
    span_seconds = (end_datetime - start_datetime).total_seconds()
    if span_seconds <= (24 * 3600 + 1):
        # Single day or under 24h: hourly buckets
        bucket_duration = timedelta(hours=1)
        t = start_datetime
        while t < end_datetime:
            bucket_end = min(t + bucket_duration, end_datetime)
            period_occ_labels.append(t.strftime('%H:%M'))
            count = 0
            for vid, vdata in all_visitors.items():
                check_in_str = vdata.get('check_in_time', '')
                visits = vdata.get('visits', {})
                if not check_in_str or check_in_str == 'N/A':
                    if visits:
                        sorted_visits = []
                        for visit_id, visit_data in visits.items():
                            ts = visit_data.get('created_at') or visit_data.get('check_in_time')
                            if ts:
                                try:
                                    sorted_visits.append((datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'), visit_data))
                                except ValueError:
                                    pass
                        if sorted_visits:
                            sorted_visits.sort(key=lambda x: x[0], reverse=True)
                            _, recent = sorted_visits[0]
                            check_in_str = recent.get('check_in_time', '')
                            check_out_str = recent.get('check_out_time', '')
                        else:
                            continue
                    else:
                        continue
                else:
                    check_out_str = vdata.get('check_out_time', '')
                if not check_in_str or check_in_str == 'N/A':
                    continue
                try:
                    check_in_dt = datetime.strptime(check_in_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                if check_out_str and check_out_str != 'N/A':
                    try:
                        check_out_dt = datetime.strptime(check_out_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        check_out_dt = current_time
                else:
                    check_out_dt = current_time
                if check_in_dt <= bucket_end and check_out_dt >= t:
                    count += 1
            period_occ_data.append(count)
            t = bucket_end
    else:
        # Multi-day: one bucket per day
        day = start_datetime.date()
        end_day = end_datetime.date()
        while day <= end_day:
            day_start = datetime.combine(day, start_datetime.time()) if day == start_datetime.date() else datetime.combine(day, datetime.min.time())
            day_end = datetime.combine(day, end_datetime.time()) if day == end_datetime.date() else datetime.combine(day, datetime.max.time().replace(microsecond=999999))
            day_start = max(day_start, start_datetime)
            day_end = min(day_end, end_datetime)
            period_occ_labels.append(day.strftime('%Y-%m-%d'))
            count = 0
            for vid, vdata in all_visitors.items():
                check_in_str = vdata.get('check_in_time', '')
                visits = vdata.get('visits', {})
                if not check_in_str or check_in_str == 'N/A':
                    if visits:
                        sorted_visits = []
                        for visit_id, visit_data in visits.items():
                            ts = visit_data.get('created_at') or visit_data.get('check_in_time')
                            if ts:
                                try:
                                    sorted_visits.append((datetime.strptime(ts, '%Y-%m-%d %H:%M:%S'), visit_data))
                                except ValueError:
                                    pass
                        if sorted_visits:
                            sorted_visits.sort(key=lambda x: x[0], reverse=True)
                            _, recent = sorted_visits[0]
                            check_in_str = recent.get('check_in_time', '')
                            check_out_str = recent.get('check_out_time', '')
                        else:
                            continue
                    else:
                        continue
                else:
                    check_out_str = vdata.get('check_out_time', '')
                if not check_in_str or check_in_str == 'N/A':
                    continue
                try:
                    check_in_dt = datetime.strptime(check_in_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                if check_out_str and check_out_str != 'N/A':
                    try:
                        check_out_dt = datetime.strptime(check_out_str, '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        check_out_dt = current_time
                else:
                    check_out_dt = current_time
                if check_in_dt <= day_end and check_out_dt >= day_start:
                    count += 1
            period_occ_data.append(count)
            day += timedelta(days=1)
    result['occupancy_over_time_period'] = {'labels': period_occ_labels, 'data': period_occ_data}
    return result

def calculate_date_range(time_filter, start_date, end_date, start_time='00:00', end_time='23:59'):
    """Calculate date range based on filter with time support"""
    from datetime import datetime, timedelta
    
    current_time = datetime.now()
    
    # Parse time components
    start_hour, start_minute = map(int, start_time.split(':'))
    end_hour, end_minute = map(int, end_time.split(':'))
    
    if time_filter == 'today':
        start_datetime = current_time.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end_datetime = current_time.replace(hour=end_hour, minute=end_minute, second=59, microsecond=999999)
        time_desc = f" ({start_time} to {end_time})" if start_time != '00:00' or end_time != '23:59' else ""
        description = f"Today's Data{time_desc}"
    
    elif time_filter == 'week':
        start_datetime = current_time - timedelta(days=current_time.weekday())
        start_datetime = start_datetime.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end_datetime = current_time.replace(hour=end_hour, minute=end_minute, second=59, microsecond=999999)
        time_desc = f" ({start_time} to {end_time})" if start_time != '00:00' or end_time != '23:59' else ""
        description = f"This Week's Data{time_desc}"
    
    elif time_filter == 'month':
        start_datetime = current_time.replace(day=1, hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end_datetime = current_time.replace(hour=end_hour, minute=end_minute, second=59, microsecond=999999)
        time_desc = f" ({start_time} to {end_time})" if start_time != '00:00' or end_time != '23:59' else ""
        description = f"This Month's Data{time_desc}"
    
    elif time_filter == 'year':
        start_datetime = current_time.replace(month=1, day=1, hour=start_hour, minute=start_minute, second=0, microsecond=0)
        end_datetime = current_time.replace(hour=end_hour, minute=end_minute, second=59, microsecond=999999)
        time_desc = f" ({start_time} to {end_time})" if start_time != '00:00' or end_time != '23:59' else ""
        description = f"This Year's Data{time_desc}"
    
    elif time_filter == 'custom' and start_date and end_date:
        try:
            start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
            start_datetime = start_datetime.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
            end_datetime = end_datetime.replace(hour=end_hour, minute=end_minute, second=59, microsecond=999999)
            time_desc = f" ({start_time} to {end_time})"
            description = f"Custom Range: {start_datetime.strftime('%b %d, %Y')} to {end_datetime.strftime('%b %d, %Y')}{time_desc}"
        except ValueError:
            # Fallback to all time if date parsing fails
            start_datetime = datetime.min
            end_datetime = datetime.max
            description = "All Time Data"
    
    else:  # all time
        start_datetime = datetime.min
        end_datetime = datetime.max
        description = "All Time Data"
    
    return {
        'start_datetime': start_datetime,
        'end_datetime': end_datetime,
        'description': description
    }
@app.route('/upload_invites', methods=['POST'])
def upload_invites():
    """Upload Excel of visitor emails and send registration invites."""
    if 'file' not in request.files:
        flash('No file part in request')
        return redirect(url_for('admin_dashboard'))

    file = request.files['file']
    if not file.filename:
        flash('No file selected')
        return redirect(url_for('admin_dashboard'))

    if file.filename.endswith(('.xlsx', '.xls')):
        filename = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filename)
        df = pd.read_excel(filename)
        email_column = next((col for col in df.columns if 'email' in col.lower()), None)
        if not email_column:
            flash("No 'Email' column found")
            return redirect(url_for('admin_dashboard'))

        sent = 0
        for email in df[email_column].dropna().astype(str).unique():
            if '@' in email and '.' in email:
                if trigger_invitation(email):
                    sent += 1
        flash(f'Sent {sent} invitation(s)')
        os.remove(filename)
        return redirect(url_for('admin_dashboard'))

    flash('Invalid file type')
    return redirect(url_for('admin_dashboard'))


def _parse_visit_date_for_filter(visitor):
    """Parse visit date for filtering: try visit_date in multiple formats, then last_visit_time."""
    visit_date_val = visitor.get('visit_date') or ''
    if visit_date_val and visit_date_val != 'N/A':
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(str(visit_date_val).strip()[:10], fmt).date()
            except (ValueError, TypeError):
                continue
    last = visitor.get('last_visit_time')
    if last and hasattr(last, 'date'):
        return last.date()
    return None


def _visitor_export_row(v):
    """Single export row for CSV (shared by list page and export endpoint)."""
    return {
        'unique_id': str(v.get('unique_id', v.get('id', ''))),
        'name': str(v.get('name', '')),
        'contact': str(v.get('contact', '')),
        'purpose': str(v.get('purpose', '')),
        'room': str(v.get('room_name') or '—'),
        'status': str(v.get('status', '')),
        'visit_date': str(v.get('visit_date', '')),
        'num_visits': v.get('num_visits', 0),
        'blacklisted': bool(v.get('blacklisted', False)),
        'blacklist_reason': str(v.get('blacklist_reason', '')),
        'registered_at': str(v.get('registered_at', '')),
    }


@app.route('/visitors/export')
def visitors_export():
    """Export filtered visitors as CSV (uses same filters as /visitors)."""
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        visitors_ref = db.reference('visitors')
        all_visitors = visitors_ref.get() or {}
    search_name = request.args.get('search_name', '').lower()
    search_status = request.args.get('search_status', 'all')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    time_range = request.args.get('time_range', 'all')
    now = datetime.now()
    rooms_map = get_meeting_rooms()
    visitors_data = []
    if all_visitors:
        for vid, data in all_visitors.items():
            basic_info = data.get('basic_info', {})
            visitor_name = str(basic_info.get('name') or 'N/A')
            visitor_contact = str(basic_info.get('contact') or 'N/A')
            blacklisted = str(basic_info.get('blacklisted', 'no')).lower() in ['yes', 'true', '1']
            blacklist_reason = basic_info.get('blacklist_reason', 'No reason provided')
            visits = data.get('visits', {})
            current_status = 'Registered'
            check_in_time = None
            expected_checkout_time = None
            purpose = 'N/A'
            employee_name = 'N/A'
            visit_date = 'N/A'
            duration = 'N/A'
            last_visit_time = None
            exceeded = False
            if visits:
                sorted_visits = []
                for visit_id, visit_data in visits.items():
                    visit_timestamp = visit_data.get('created_at') or visit_data.get('check_in_time')
                    if visit_timestamp:
                        try:
                            visit_dt = datetime.strptime(visit_timestamp, "%Y-%m-%d %H:%M:%S")
                            sorted_visits.append((visit_dt, visit_id, visit_data))
                        except ValueError:
                            continue
                if sorted_visits:
                    sorted_visits.sort(key=lambda x: x[0], reverse=True)
                    last_visit_time, _, recent_visit_data = sorted_visits[0]
                    status_from_visit = recent_visit_data.get('status', 'Registered')
                    if status_from_visit.lower() in ['checked_out', 'checked-out', 'checked out']:
                        current_status = 'Checked Out'
                    elif status_from_visit.lower() in ['checked_in', 'checked-in', 'checked in']:
                        current_status = 'Checked In'
                        check_in_time = recent_visit_data.get('check_in_time')
                        expected_checkout_time = recent_visit_data.get('expected_checkout_time')
                        if check_in_time and expected_checkout_time:
                            try:
                                checkin_dt = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S")
                                checkout_dt = datetime.strptime(expected_checkout_time, "%Y-%m-%d %H:%M:%S")
                                if now > checkout_dt:
                                    exceeded = True
                                    current_status = 'Exceeded'
                            except ValueError:
                                pass
                    elif status_from_visit.lower() in ['approved', 'approve']:
                        current_status = 'Approved'
                    elif status_from_visit.lower() in ['registered', 'register']:
                        current_status = 'Registered'
                    elif status_from_visit.lower() in ['rejected', 'reject']:
                        current_status = 'Rejected'
                    elif status_from_visit.lower() in ['rescheduled', 'reschedule']:
                        current_status = 'Rescheduled'
                    elif status_from_visit.lower() in ['exceeded', 'time_exceeded']:
                        current_status = 'Exceeded'
                        exceeded = True
                    else:
                        current_status = str(status_from_visit) if status_from_visit else 'Registered'
                    purpose = recent_visit_data.get('purpose', 'N/A')
                    employee_name = recent_visit_data.get('employee_name', 'N/A')
                    visit_date = recent_visit_data.get('visit_date', 'N/A')
                    duration = recent_visit_data.get('duration', 'N/A')
            transactions = data.get('transactions', {})
            num_visits = len(visits) if visits else len(transactions) if isinstance(transactions, dict) else 0
            registered_at = 'N/A'
            if transactions:
                earliest_transaction = min(transactions.keys())
                registered_at = transactions[earliest_transaction].get('timestamp', 'N/A')
            room_id, room_name = _extract_visitor_room(data, rooms_map)
            visitors_data.append({
                'id': vid, 'unique_id': vid, 'name': visitor_name, 'contact': visitor_contact,
                'purpose': purpose, 'status': current_status, 'exceeded': exceeded, 'blacklisted': blacklisted,
                'blacklist_reason': blacklist_reason, 'transactions': transactions, 'visits': visits,
                'visit_date': visit_date, 'last_visit_time': last_visit_time, 'check_in_time': check_in_time,
                'num_visits': num_visits, 'check_out_time': None, 'expected_checkout_time': expected_checkout_time,
                'registered_at': registered_at, 'employee_name': employee_name, 'duration': duration,
                'photo_path': basic_info.get('photo_path', 'N/A'), 'profile_link': basic_info.get('profile_link', 'N/A'),
                'room_id': room_id, 'room_name': room_name,
            })
    filtered_visitors = []
    for visitor in visitors_data:
        include_visitor = True
        name_str = str(visitor.get('name') or 'N/A').lower()
        if search_name and search_name not in name_str:
            include_visitor = False
        visitor_status_normalized = str(visitor.get('status') or '').lower().replace(' ', '_').replace('-', '_')
        if search_status != 'all' and search_status != visitor_status_normalized:
            include_visitor = False
        if start_date and end_date:
            visit_dt = _parse_visit_date_for_filter(visitor)
            if visit_dt is not None:
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
                    if not (start_dt <= visit_dt <= end_dt):
                        include_visitor = False
                except ValueError:
                    pass
        use_time_range = time_range != 'all' and not (start_date and end_date)
        if use_time_range and visitor.get('last_visit_time'):
            try:
                lt = visitor['last_visit_time']
                if time_range == 'today' and lt.date() != now.date():
                    include_visitor = False
                elif time_range == 'week' and lt < (now - timedelta(days=7)):
                    include_visitor = False
                elif time_range == 'month' and lt < (now - timedelta(days=30)):
                    include_visitor = False
                elif time_range == '<1hr' and lt < (now - timedelta(hours=1)):
                    include_visitor = False
                elif time_range == '<3hr' and lt < (now - timedelta(hours=3)):
                    include_visitor = False
                elif time_range == '<6hr' and lt < (now - timedelta(hours=6)):
                    include_visitor = False
            except (ValueError, TypeError):
                pass
        if include_visitor:
            filtered_visitors.append(visitor)
    filtered_visitors.sort(key=lambda x: x['last_visit_time'] or datetime.min, reverse=True)
    export_visitors = [_visitor_export_row(v) for v in filtered_visitors]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Unique ID', 'Name', 'Contact', 'Purpose', 'Room', 'Status', 'Visit Date', 'Visits', 'Blacklisted', 'Blacklist Reason', 'Registered At'])
    for v in export_visitors:
        writer.writerow([
            v['unique_id'], v['name'], v['contact'], v['purpose'], v['room'], v['status'], v['visit_date'],
            v['num_visits'], 'Yes' if v['blacklisted'] else 'No', v['blacklist_reason'], v['registered_at']
        ])
    filename = 'visitors_report_' + datetime.now().strftime('%Y-%m-%d') + '.csv'
    resp = make_response(buf.getvalue().encode('utf-8-sig'))
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename="' + filename + '"'
    return resp


@app.route('/visitors')
def visitors_list():
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        visitors_ref = db.reference('visitors')
        all_visitors = visitors_ref.get() or {}
    visitors_data = []
    rooms_map = get_meeting_rooms()

    now = datetime.now()
    
    # Get filter parameters from request
    search_name = request.args.get('search_name', '').lower()
    search_status = request.args.get('search_status', 'all')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    time_range = request.args.get('time_range', 'all')  # all, today, week, month, <1hr, <3hr, <6hr
    
    # Pagination parameters
    page = int(request.args.get('page', 1))
    per_page = 10

    if all_visitors:
        for vid, data in all_visitors.items():
            # Extract basic_info
            basic_info = data.get('basic_info', {})
            
            # Get visitor details from basic_info (normalize to string for safe filtering/display)
            visitor_name = str(basic_info.get('name') or 'N/A')
            visitor_contact = str(basic_info.get('contact') or 'N/A')
            blacklisted = str(basic_info.get('blacklisted', 'no')).lower() in ['yes', 'true', '1']
            blacklist_reason = basic_info.get('blacklist_reason', 'No reason provided')
            
            # Get visits and find the most recent one for status
            visits = data.get('visits', {})
            recent_visit = None
            current_status = 'Registered'  # Default status
            check_in_time = None
            check_out_time = None
            expected_checkout_time = None
            purpose = 'N/A'
            employee_name = 'N/A'
            visit_date = 'N/A'
            duration = 'N/A'
            last_visit_time = None
            exceeded = False

            if visits:
                # Find the most recent visit by timestamp
                sorted_visits = []
                for visit_id, visit_data in visits.items():
                    visit_timestamp = visit_data.get('created_at') or visit_data.get('check_in_time')
                    if visit_timestamp:
                        try:
                            visit_dt = datetime.strptime(visit_timestamp, "%Y-%m-%d %H:%M:%S")
                            sorted_visits.append((visit_dt, visit_id, visit_data))
                        except ValueError:
                            continue
                
                if sorted_visits:
                    # Sort by timestamp (most recent first)
                    sorted_visits.sort(key=lambda x: x[0], reverse=True)
                    last_visit_time, recent_visit_id, recent_visit_data = sorted_visits[0]
                    
                    # Get status from the most recent visit - handle different status formats
                    status_from_visit = recent_visit_data.get('status', 'Registered')
                    # Normalize status values
                    if status_from_visit.lower() in ['checked_out', 'checked-out', 'checked out']:
                        current_status = 'Checked Out'
                    elif status_from_visit.lower() in ['checked_in', 'checked-in', 'checked in']:
                        current_status = 'Checked In'
                        # Check if time exceeded for checked-in visitors
                        check_in_time = recent_visit_data.get('check_in_time')
                        expected_checkout_time = recent_visit_data.get('expected_checkout_time')
                        if check_in_time and expected_checkout_time:
                            try:
                                checkin_dt = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S")
                                checkout_dt = datetime.strptime(expected_checkout_time, "%Y-%m-%d %H:%M:%S")
                                if now > checkout_dt:
                                    exceeded = True
                                    current_status = 'Exceeded'
                            except ValueError:
                                pass
                    elif status_from_visit.lower() in ['approved', 'approve']:
                        current_status = 'Approved'
                    elif status_from_visit.lower() in ['registered', 'register']:
                        current_status = 'Registered'
                    elif status_from_visit.lower() in ['rejected', 'reject']:
                        current_status = 'Rejected'
                    elif status_from_visit.lower() in ['rescheduled', 'reschedule']:
                        current_status = 'Rescheduled'
                    elif status_from_visit.lower() in ['exceeded', 'time_exceeded']:
                        current_status = 'Exceeded'
                        exceeded = True
                    else:
                        current_status = str(status_from_visit) if status_from_visit else 'Registered'
                    
                    purpose = recent_visit_data.get('purpose', 'N/A')
                    employee_name = recent_visit_data.get('employee_name', 'N/A')
                    visit_date = recent_visit_data.get('visit_date', 'N/A')
                    duration = recent_visit_data.get('duration', 'N/A')

            # Calculate number of visits from transactions or visits
            transactions = data.get('transactions', {})
            num_visits = len(visits) if visits else len(transactions) if isinstance(transactions, dict) else 0
            
            # Get registered_at from the earliest transaction or use current time
            registered_at = 'N/A'
            if transactions:
                earliest_transaction = min(transactions.keys())
                registered_at = transactions[earliest_transaction].get('timestamp', 'N/A')

            # Use visitor ID as unique_id
            unique_id = vid
            room_id, room_name = _extract_visitor_room(data, rooms_map)

            visitors_data.append({
                'id': vid,
                'unique_id': unique_id,
                'name': visitor_name,
                'contact': visitor_contact,
                'purpose': purpose,
                'status': current_status,
                'exceeded': exceeded,
                'blacklisted': blacklisted,
                'blacklist_reason': blacklist_reason,
                'transactions': transactions,
                'visits': visits,
                'visit_date': visit_date,
                'last_visit_time': last_visit_time,
                'check_in_time': check_in_time,
                'num_visits': num_visits,
                'check_out_time': check_out_time,
                'expected_checkout_time': expected_checkout_time,
                'registered_at': registered_at,
                'employee_name': employee_name,
                'duration': duration,
                'photo_path': basic_info.get('photo_path', 'N/A'),
                'profile_link': basic_info.get('profile_link', 'N/A'),
                'room_id': room_id,
                'room_name': room_name,
            })

    # Apply filters
    filtered_visitors = []
    for visitor in visitors_data:
        include_visitor = True
        
        # Filter by name search (normalize to string to avoid type errors from Firebase)
        name_str = str(visitor.get('name') or 'N/A').lower()
        if search_name and search_name not in name_str:
            include_visitor = False
        
        # Filter by status (normalize to string and consistent format)
        visitor_status_normalized = str(visitor.get('status') or '').lower().replace(' ', '_').replace('-', '_')
        if search_status != 'all':
            if search_status != visitor_status_normalized:
                include_visitor = False
        
        # Filter by date range (support multiple date formats and fallback to last_visit_time)
        if start_date and end_date:
            visit_dt = _parse_visit_date_for_filter(visitor)
            if visit_dt is not None:
                try:
                    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
                    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
                    if not (start_dt <= visit_dt <= end_dt):
                        include_visitor = False
                except ValueError:
                    pass
        
        # Filter by time range (only when no custom date range is set - otherwise it would contradict)
        use_time_range = time_range != 'all' and not (start_date and end_date)
        if use_time_range and visitor['last_visit_time']:
            try:
                if time_range == 'today':
                    if visitor['last_visit_time'].date() != now.date():
                        include_visitor = False
                elif time_range == 'week':
                    week_ago = now - timedelta(days=7)
                    if visitor['last_visit_time'] < week_ago:
                        include_visitor = False
                elif time_range == 'month':
                    month_ago = now - timedelta(days=30)
                    if visitor['last_visit_time'] < month_ago:
                        include_visitor = False
                elif time_range == '<1hr':
                    one_hour_ago = now - timedelta(hours=1)
                    if visitor['last_visit_time'] < one_hour_ago:
                        include_visitor = False
                elif time_range == '<3hr':
                    three_hours_ago = now - timedelta(hours=3)
                    if visitor['last_visit_time'] < three_hours_ago:
                        include_visitor = False
                elif time_range == '<6hr':
                    six_hours_ago = now - timedelta(hours=6)
                    if visitor['last_visit_time'] < six_hours_ago:
                        include_visitor = False
            except (ValueError, TypeError):
                pass
        
        if include_visitor:
            filtered_visitors.append(visitor)

    # Sort by last visit time (most recent first)
    filtered_visitors.sort(key=lambda x: x['last_visit_time'] or datetime.min, reverse=True)

    # Calculate comprehensive statistics - now including Exceeded status
    total_visitors = len(filtered_visitors)
    registered_count = sum(1 for v in filtered_visitors if v['status'] == 'Registered')
    approved_count = sum(1 for v in filtered_visitors if v['status'] == 'Approved')
    checked_in_count = sum(1 for v in filtered_visitors if v['status'] == 'Checked In')
    checked_out_count = sum(1 for v in filtered_visitors if v['status'] == 'Checked Out')
    rescheduled_count = sum(1 for v in filtered_visitors if v['status'] == 'Rescheduled')
    rejected_count = sum(1 for v in filtered_visitors if v['status'] == 'Rejected')
    exceeded_count = sum(1 for v in filtered_visitors if v['status'] == 'Exceeded')
    blacklisted_count = sum(1 for v in filtered_visitors if v['blacklisted'])
    
    # Calculate percentages
    status_distribution = {
        'registered': (registered_count / total_visitors * 100) if total_visitors > 0 else 0,
        'approved': (approved_count / total_visitors * 100) if total_visitors > 0 else 0,
        'checked_in': (checked_in_count / total_visitors * 100) if total_visitors > 0 else 0,
        'checked_out': (checked_out_count / total_visitors * 100) if total_visitors > 0 else 0,
        'rescheduled': (rescheduled_count / total_visitors * 100) if total_visitors > 0 else 0,
        'rejected': (rejected_count / total_visitors * 100) if total_visitors > 0 else 0,
        'exceeded': (exceeded_count / total_visitors * 100) if total_visitors > 0 else 0,
    }

    # Pagination
    total_pages = max(1, (total_visitors + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_visitors = filtered_visitors[start_idx:end_idx]

    # Calculate display range for template
    showing_start = start_idx + 1 if total_visitors > 0 else 0
    showing_end = min(end_idx, total_visitors)

    export_visitors = [_visitor_export_row(v) for v in filtered_visitors]
    VISITORS_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Workplace Intelligence Platform | Admin Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            .status-badge {
                display: inline-flex;
                align-items: center;
                padding: 2px 10px;
                border-radius: 9999px;
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: capitalize;
            }
            .metric-card {
                transition: all 0.3s ease;
                border-left: 4px solid;
            }
            .metric-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
            }
            .progress-bar {
                height: 6px;
                border-radius: 3px;
                overflow: hidden;
                background: #e5e7eb;
            }
            .progress-fill {
                height: 100%;
                transition: width 0.5s ease-in-out;
            }
            .fade-in {
                animation: fadeIn 0.5s ease-in;
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
        </style>
    </head>
    <body class="min-h-screen bg-gray-50 p-6">
        <div class="max-w-7xl mx-auto space-y-6">
            <!-- Header -->
            <div class="flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4">
                <div>
                    <a href="{{ url_for('index') }}" class="text-gray-500 hover:text-gray-700 text-sm inline-flex items-center mb-1">
                        <i class="fas fa-arrow-left mr-1"></i>Back to Admin
                    </a>
                    <h1 class="text-3xl font-bold text-gray-900">Workplace Intelligence Platform</h1>
                    <p class="text-gray-600">Manage and track all visitor activities</p>
                </div>
                <div class="flex flex-wrap gap-3">
                    <a href="{{ url_for('blacklist_page') }}" 
                       class="bg-white hover:bg-gray-50 text-red-700 font-medium px-4 py-2 rounded-lg border border-red-200 shadow-sm transition flex items-center">
                        <i class="fas fa-ban mr-2"></i>View blacklisted only
                    </a>
                    <a href="{{ url_for('visitors_export') }}{% if request.query_string %}?{{ request.query_string.decode() }}{% endif %}" 
                       class="bg-white hover:bg-gray-50 text-gray-700 font-medium px-4 py-2 rounded-lg border border-gray-300 shadow-sm transition inline-flex items-center">
                        <i class="fas fa-file-export mr-2"></i>Export CSV
                    </a>
                </div>
            </div>

            <!-- Filters Section: GET form so filters work without JavaScript -->
            <div class="bg-white rounded-xl p-6 shadow-sm">
                <h3 class="text-lg font-semibold text-gray-900 mb-4">Filters</h3>
                <form method="get" action="{{ url_for('visitors_list') }}" id="visitorsFilterForm">
                    <input type="hidden" name="page" value="1">
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">Search by Name</label>
                            <input type="text" name="search_name" id="searchInput"
                                   placeholder="Enter visitor name..."
                                   value="{{ request.args.get('search_name', '') }}"
                                   class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">Status</label>
                            <select name="search_status" id="statusFilter"
                                    class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <option value="all" {{ 'selected' if request.args.get('search_status', 'all') == 'all' else '' }}>All Status</option>
                                <option value="registered" {{ 'selected' if request.args.get('search_status') == 'registered' else '' }}>Registered</option>
                                <option value="approved" {{ 'selected' if request.args.get('search_status') == 'approved' else '' }}>Approved</option>
                                <option value="checked_in" {{ 'selected' if request.args.get('search_status') == 'checked_in' else '' }}>Checked In</option>
                                <option value="checked_out" {{ 'selected' if request.args.get('search_status') == 'checked_out' else '' }}>Checked Out</option>
                                <option value="rescheduled" {{ 'selected' if request.args.get('search_status') == 'rescheduled' else '' }}>Rescheduled</option>
                                <option value="rejected" {{ 'selected' if request.args.get('search_status') == 'rejected' else '' }}>Rejected</option>
                                <option value="exceeded" {{ 'selected' if request.args.get('search_status') == 'exceeded' else '' }}>Exceeded</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">Date Range</label>
                            <div class="space-y-2">
                                <input type="date" name="start_date" id="startDate"
                                       value="{{ request.args.get('start_date', '') }}"
                                       class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                       placeholder="Start date">
                                <input type="date" name="end_date" id="endDate"
                                       value="{{ request.args.get('end_date', '') }}"
                                       class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                       placeholder="End date">
                            </div>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-2">Time Range</label>
                            <select name="time_range" id="timeRange" class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <option value="all" {{ 'selected' if request.args.get('time_range', 'all') == 'all' else '' }}>All Time</option>
                                <option value="today" {{ 'selected' if request.args.get('time_range') == 'today' else '' }}>Today</option>
                                <option value="week" {{ 'selected' if request.args.get('time_range') == 'week' else '' }}>This Week</option>
                                <option value="month" {{ 'selected' if request.args.get('time_range') == 'month' else '' }}>This Month</option>
                                <option value="<1hr" {{ 'selected' if request.args.get('time_range') == '<1hr' else '' }}>Last 1 Hour</option>
                                <option value="<3hr" {{ 'selected' if request.args.get('time_range') == '<3hr' else '' }}>Last 3 Hours</option>
                                <option value="<6hr" {{ 'selected' if request.args.get('time_range') == '<6hr' else '' }}>Last 6 Hours</option>
                            </select>
                            <p class="text-xs text-gray-500 mt-1">Ignored when a date range is set above.</p>
                        </div>
                    </div>
                    <div class="flex gap-3 mt-4">
                        <button type="submit"
                                class="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-6 rounded-lg transition">
                            Apply Filters
                        </button>
                        <a href="{{ url_for('visitors_list') }}"
                           class="bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium py-2 px-6 rounded-lg transition inline-block">
                            Clear All
                        </a>
                    </div>
                </form>
            </div>

            <!-- Key Metrics -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div class="metric-card bg-white rounded-xl p-4 shadow-sm border-l-blue-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Total Visitors</p>
                            <p class="text-2xl font-bold text-gray-900">{{ total_visitors }}</p>
                        </div>
                        <div class="p-3 bg-blue-100 rounded-lg">
                            <i class="fas fa-users text-blue-600 text-xl"></i>
                        </div>
                    </div>
                </div>

                <div class="metric-card bg-white rounded-xl p-4 shadow-sm border-l-green-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Active Now</p>
                            <p class="text-2xl font-bold text-gray-900">{{ checked_in_count }}</p>
                        </div>
                        <div class="p-3 bg-green-100 rounded-lg">
                            <i class="fas fa-user-check text-green-600 text-xl"></i>
                        </div>
                    </div>
                </div>

                <div class="metric-card bg-white rounded-xl p-4 shadow-sm border-l-purple-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Pending</p>
                            <p class="text-2xl font-bold text-gray-900">{{ registered_count + approved_count }}</p>
                        </div>
                        <div class="p-3 bg-purple-100 rounded-lg">
                            <i class="fas fa-clock text-purple-600 text-xl"></i>
                        </div>
                    </div>
                </div>

                <div class="metric-card bg-white rounded-xl p-4 shadow-sm border-l-red-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Exceeded Time</p>
                            <p class="text-2xl font-bold text-gray-900">{{ exceeded_count }}</p>
                        </div>
                        <div class="p-3 bg-red-100 rounded-lg">
                            <i class="fas fa-exclamation-triangle text-red-600 text-xl"></i>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Status Distribution -->
            <div class="bg-white rounded-xl p-6 shadow-sm">
                <div class="flex justify-between items-center mb-6">
                    <h3 class="text-lg font-semibold text-gray-900">Status Distribution</h3>
                    <span class="text-sm text-gray-500">Real-time overview</span>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4">
                    <div class="text-center">
                        <div class="mx-auto w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mb-2">
                            <span class="text-gray-700 font-bold">{{ registered_count }}</span>
                        </div>
                        <p class="text-xs font-medium text-gray-600">Registered</p>
                        <div class="progress-bar mt-1">
                            <div class="progress-fill bg-gray-500" style="width: {{ status_distribution.registered }}%"></div>
                        </div>
                    </div>
                    <div class="text-center">
                        <div class="mx-auto w-12 h-12 bg-yellow-100 rounded-full flex items-center justify-center mb-2">
                            <span class="text-yellow-700 font-bold">{{ approved_count }}</span>
                        </div>
                        <p class="text-xs font-medium text-gray-600">Approved</p>
                        <div class="progress-bar mt-1">
                            <div class="progress-fill bg-yellow-500" style="width: {{ status_distribution.approved }}%"></div>
                        </div>
                    </div>
                    <div class="text-center">
                        <div class="mx-auto w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mb-2">
                            <span class="text-green-700 font-bold">{{ checked_in_count }}</span>
                        </div>
                        <p class="text-xs font-medium text-gray-600">Checked In</p>
                        <div class="progress-bar mt-1">
                            <div class="progress-fill bg-green-500" style="width: {{ status_distribution.checked_in }}%"></div>
                        </div>
                    </div>
                    <div class="text-center">
                        <div class="mx-auto w-12 h-12 bg-purple-100 rounded-full flex items-center justify-center mb-2">
                            <span class="text-purple-700 font-bold">{{ checked_out_count }}</span>
                        </div>
                        <p class="text-xs font-medium text-gray-600">Checked Out</p>
                        <div class="progress-bar mt-1">
                            <div class="progress-fill bg-purple-500" style="width: {{ status_distribution.checked_out }}%"></div>
                        </div>
                    </div>
                    <div class="text-center">
                        <div class="mx-auto w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center mb-2">
                            <span class="text-blue-700 font-bold">{{ rescheduled_count }}</span>
                        </div>
                        <p class="text-xs font-medium text-gray-600">Rescheduled</p>
                        <div class="progress-bar mt-1">
                            <div class="progress-fill bg-blue-500" style="width: {{ status_distribution.rescheduled }}%"></div>
                        </div>
                    </div>
                    <div class="text-center">
                        <div class="mx-auto w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mb-2">
                            <span class="text-red-700 font-bold">{{ rejected_count }}</span>
                        </div>
                        <p class="text-xs font-medium text-gray-600">Rejected</p>
                        <div class="progress-bar mt-1">
                            <div class="progress-fill bg-red-500" style="width: {{ status_distribution.rejected }}%"></div>
                        </div>
                    </div>
                    <div class="text-center">
                        <div class="mx-auto w-12 h-12 bg-orange-100 rounded-full flex items-center justify-center mb-2">
                            <span class="text-orange-700 font-bold">{{ exceeded_count }}</span>
                        </div>
                        <p class="text-xs font-medium text-gray-600">Exceeded</p>
                        <div class="progress-bar mt-1">
                            <div class="progress-fill bg-orange-500" style="width: {{ status_distribution.exceeded }}%"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Visitors Table -->
            <div class="bg-white rounded-xl shadow-sm overflow-hidden">
                <div class="px-6 py-4 border-b border-gray-200">
                    <div class="flex justify-between items-center">
                        <h3 class="text-lg font-semibold text-gray-900">Visitor Records</h3>
                        <div class="text-sm text-gray-500">
                            Showing {{ showing_start }} to {{ showing_end }} of {{ total_visitors }} visitors
                        </div>
                    </div>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Visitor ID</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Visitor Details</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Purpose</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Room</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Visits</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Blacklist</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {% for visitor in paginated_visitors %}
                            <tr class="hover:bg-gray-50 transition-colors fade-in">
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <a href="/visitor/{{ visitor.id }}" 
                                       class="text-blue-600 hover:text-blue-900 font-medium cursor-pointer"
                                       title="Click to view full details">
                                        {{ visitor.unique_id }}
                                    </a>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="flex items-center">
                                        <div class="flex-shrink-0 h-10 w-10 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-bold">
                                            {{ visitor.name[0]|upper if visitor.name and visitor.name != 'N/A' else '?' }}
                                        </div>
                                        <div class="ml-4">
                                            <div class="text-sm font-medium text-gray-900">{{ visitor.name }}</div>
                                            <div class="text-sm text-gray-500">{{ visitor.contact }}</div>
                                            <div class="text-xs text-gray-400">{{ visitor.employee_name if visitor.employee_name != 'N/A' else 'No employee' }}</div>
                                        </div>
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm text-gray-900">{{ visitor.purpose }}</div>
                                    <div class="text-sm text-gray-500">{{ visitor.visit_date if visitor.visit_date != 'N/A' else 'No date' }}</div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm text-gray-900">{{ visitor.room_name }}</div>
                                    {% if visitor.room_id %}
                                    <div class="text-xs text-gray-400 font-mono">{{ visitor.room_id }}</div>
                                    {% endif %}
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    {% set status_config = {
                                        'Registered': {'color': 'gray', 'icon': 'user-plus'},
                                        'Approved': {'color': 'yellow', 'icon': 'check-circle'},
                                        'Checked In': {'color': 'green', 'icon': 'user-check'},
                                        'Checked Out': {'color': 'purple', 'icon': 'user-times'},
                                        'Rescheduled': {'color': 'blue', 'icon': 'calendar-alt'},
                                        'Rejected': {'color': 'red', 'icon': 'times-circle'},
                                        'Exceeded': {'color': 'orange', 'icon': 'exclamation-triangle'}
                                    } %}
                                    {% set config = status_config.get(visitor.status, {'color': 'gray', 'icon': 'question'}) %}
                                    <span class="status-badge bg-{{ config.color }}-100 text-{{ config.color }}-800 inline-flex items-center">
                                        <i class="fas fa-{{ config.icon }} mr-1 text-xs"></i>
                                        {{ visitor.status }}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm font-medium text-gray-900 text-center">
                                        <span class="inline-flex items-center justify-center w-8 h-8 rounded-full bg-blue-100 text-blue-800">
                                            {{ visitor.num_visits }}
                                        </span>
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    {% if visitor.blacklisted %}
                                    <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                                        <i class="fas fa-ban mr-1"></i>Blacklisted
                                    </span>
                                    <div class="text-xs text-gray-500 mt-1 max-w-xs truncate" title="{{ visitor.blacklist_reason }}">{{ visitor.blacklist_reason }}</div>
                                    <a href="{{ url_for('visitor_detail', visitor_id=visitor.id) }}#blacklist" class="text-xs text-blue-600 hover:underline mt-1 inline-block">Manage</a>
                                    {% else %}
                                    <span class="text-gray-400 text-sm">—</span>
                                    <a href="{{ url_for('visitor_detail', visitor_id=visitor.id) }}#blacklist" class="text-xs text-blue-600 hover:underline mt-1 inline-block">Add to blacklist</a>
                                    {% endif %}
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="flex flex-wrap items-center gap-1">
                                        <a href="/visitor/{{ visitor.id }}" class="inline-flex items-center px-2 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded text-xs font-medium">View</a>
                                        {% if visitor.status == 'Registered' or visitor.status == 'Pending Approval' %}
                                        <button type="button" onclick="listVisitorAction('{{ visitor.id|e }}', 'approve')" class="inline-flex items-center px-2 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-xs font-medium" title="Approve">Approve</button>
                                        <button type="button" onclick="listVisitorAction('{{ visitor.id|e }}', 'reject')" class="inline-flex items-center px-2 py-1 bg-red-600 hover:bg-red-700 text-white rounded text-xs font-medium" title="Reject">Reject</button>
                                        {% elif visitor.status == 'Approved' %}
                                        <button type="button" onclick="listVisitorAction('{{ visitor.id|e }}', 'checkin')" class="inline-flex items-center px-2 py-1 bg-green-600 hover:bg-green-700 text-white rounded text-xs font-medium" title="Check-in">Check-in</button>
                                        {% elif visitor.status == 'Checked In' %}
                                        <button type="button" onclick="listVisitorAction('{{ visitor.id|e }}', 'checkout')" class="inline-flex items-center px-2 py-1 bg-purple-600 hover:bg-purple-700 text-white rounded text-xs font-medium" title="Check-out">Check-out</button>
                                        {% endif %}
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>

                <!-- Pagination -->
                {% if total_pages > 1 %}
                <div class="px-6 py-4 border-t border-gray-200 bg-gray-50">
                    <div class="flex items-center justify-between">
                        <div class="text-sm text-gray-700">
                            Page {{ page }} of {{ total_pages }}
                        </div>
                        <div class="flex space-x-1">
                            {% if page > 1 %}
                            <button onclick="changePage({{ page - 1 }})" 
                                    class="px-3 py-1 text-sm bg-white border border-gray-300 rounded hover:bg-gray-50">
                                Previous
                            </button>
                            {% endif %}
                            
                            {% for p in range(1, total_pages + 1) %}
                                {% if p == page %}
                                <span class="px-3 py-1 text-sm bg-blue-600 text-white border border-blue-600 rounded">
                                    {{ p }}
                                </span>
                                {% else %}
                                <button onclick="changePage({{ p }})" 
                                        class="px-3 py-1 text-sm bg-white border border-gray-300 rounded hover:bg-gray-50">
                                    {{ p }}
                                </button>
                                {% endif %}
                            {% endfor %}
                            
                            {% if page < total_pages %}
                            <button onclick="changePage({{ page + 1 }})" 
                                    class="px-3 py-1 text-sm bg-white border border-gray-300 rounded hover:bg-gray-50">
                                Next
                            </button>
                            {% endif %}
                        </div>
                    </div>
                </div>
                {% endif %}
            </div>
        </div>

        <script>
            function changePage(page) {
                var params = new URLSearchParams(window.location.search);
                params.set('page', page);
                window.location.href = window.location.pathname + '?' + params.toString();
            }
            async function listVisitorAction(visitorId, action) {
                var endpoint = '/visitor/' + encodeURIComponent(visitorId) + '/' + action;
                var msg = action === 'approve' ? 'Approved' : action === 'reject' ? 'Rejected' : action === 'checkin' ? 'Checked in' : 'Checked out';
                if (action === 'reject' && !confirm('Reject this visitor?')) return;
                try {
                    var r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
                    var data = r.ok ? await r.json().catch(function() { return {}; }) : null;
                    if (r.ok && (data === null || data.success !== false)) {
                        var fullMsg = msg + ' successfully.';
                        if (action === 'approve' && data && data.email_sent !== undefined) {
                            fullMsg += data.email_sent ? ' QR email sent to visitor.' : ' QR email not sent: ' + (data.email_message || 'unknown');
                        }
                        alert(fullMsg);
                        location.reload();
                    } else {
                        alert('Error: ' + (data && data.message ? data.message : r.status));
                    }
                } catch (e) {
                    alert('Error: ' + e.message);
                }
            }
        </script>
    </body>
    </html>
    """
    resp = make_response(render_template_string(VISITORS_HTML,
                            paginated_visitors=paginated_visitors,
                            all_filtered_visitors=filtered_visitors,
                            export_visitors=export_visitors,
                            total_visitors=total_visitors,
                            registered_count=registered_count,
                            approved_count=approved_count,
                            checked_in_count=checked_in_count,
                            checked_out_count=checked_out_count,
                            rescheduled_count=rescheduled_count,
                            rejected_count=rejected_count,
                            exceeded_count=exceeded_count,
                            blacklisted_count=blacklisted_count,
                            status_distribution=status_distribution,
                            request=request,
                            page=page,
                            total_pages=total_pages,
                            showing_start=showing_start,
                            showing_end=showing_end))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _build_visitor_list_from_raw(all_visitors):
    """Build list of visitor dicts from raw all_visitors (same extraction as visitors_list). Includes email and company for verbose views."""
    visitors_data = []
    now = datetime.now()
    rooms_map = get_meeting_rooms()
    if not all_visitors:
        return visitors_data
    for vid, data in all_visitors.items():
        if not isinstance(data, dict) or not _is_valid_visitor_id(vid):
            continue
        basic_info = data.get('basic_info') or {}
        visitor_name = basic_info.get('name', 'N/A')
        visitor_contact = basic_info.get('contact', 'N/A')
        visitor_email = basic_info.get('email', 'N/A')
        company = basic_info.get('company', 'N/A')
        blacklisted = _is_visitor_blacklisted(data)
        blacklist_reason = basic_info.get('blacklist_reason', 'No reason provided')
        blacklisted_at = basic_info.get('blacklisted_at', '') or ''
        visits = data.get('visits') or {}
        current_status = 'Registered'
        check_in_time = None
        check_out_time = None
        expected_checkout_time = None
        purpose = 'N/A'
        employee_name = 'N/A'
        visit_date = 'N/A'
        duration = 'N/A'
        last_visit_time = None
        exceeded = False
        if visits:
            sorted_visits = []
            for visit_id, visit_data in visits.items():
                visit_timestamp = visit_data.get('created_at') or visit_data.get('check_in_time')
                if visit_timestamp:
                    try:
                        visit_dt = datetime.strptime(visit_timestamp, "%Y-%m-%d %H:%M:%S")
                        sorted_visits.append((visit_dt, visit_id, visit_data))
                    except ValueError:
                        continue
            if sorted_visits:
                sorted_visits.sort(key=lambda x: x[0], reverse=True)
                last_visit_time, recent_visit_id, recent_visit_data = sorted_visits[0]
                status_from_visit = recent_visit_data.get('status') or 'Registered'
                if status_from_visit.lower() in ['checked_out', 'checked-out', 'checked out']:
                    current_status = 'Checked Out'
                elif status_from_visit.lower() in ['checked_in', 'checked-in', 'checked in']:
                    current_status = 'Checked In'
                    check_in_time = recent_visit_data.get('check_in_time')
                    expected_checkout_time = recent_visit_data.get('expected_checkout_time')
                    if check_in_time and expected_checkout_time:
                        try:
                            checkin_dt = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S")
                            checkout_dt = datetime.strptime(expected_checkout_time, "%Y-%m-%d %H:%M:%S")
                            if now > checkout_dt:
                                exceeded = True
                                current_status = 'Exceeded'
                        except ValueError:
                            pass
                elif status_from_visit.lower() in ['approved', 'approve']:
                    current_status = 'Approved'
                elif status_from_visit.lower() in ['registered', 'register']:
                    current_status = 'Registered'
                elif status_from_visit.lower() in ['rejected', 'reject']:
                    current_status = 'Rejected'
                elif status_from_visit.lower() in ['rescheduled', 'reschedule']:
                    current_status = 'Rescheduled'
                elif status_from_visit.lower() in ['exceeded', 'time_exceeded']:
                    current_status = 'Exceeded'
                    exceeded = True
                else:
                    current_status = status_from_visit
                purpose = recent_visit_data.get('purpose', 'N/A')
                employee_name = recent_visit_data.get('employee_name', 'N/A')
                visit_date = recent_visit_data.get('visit_date', 'N/A')
                duration = recent_visit_data.get('duration', 'N/A')
                check_in_time = recent_visit_data.get('check_in_time')
                check_out_time = recent_visit_data.get('check_out_time')
        transactions = data.get('transactions') or {}
        num_visits = len(visits) if visits else len(transactions) if isinstance(transactions, dict) else 0
        registered_at = 'N/A'
        if transactions:
            earliest_transaction = min(transactions.keys())
            registered_at = transactions[earliest_transaction].get('timestamp', 'N/A')
        room_id, room_name = _extract_visitor_room(data, rooms_map)
        visitors_data.append({
            'id': vid,
            'unique_id': vid,
            'name': visitor_name,
            'contact': visitor_contact,
            'email': visitor_email,
            'company': company,
            'purpose': purpose,
            'status': current_status,
            'exceeded': exceeded,
            'blacklisted': blacklisted,
            'blacklist_reason': blacklist_reason,
            'blacklisted_at': blacklisted_at,
            'transactions': transactions,
            'visits': visits,
            'visit_date': visit_date,
            'last_visit_time': last_visit_time,
            'check_in_time': check_in_time,
            'num_visits': num_visits,
            'check_out_time': check_out_time,
            'expected_checkout_time': expected_checkout_time,
            'registered_at': registered_at,
            'employee_name': employee_name,
            'duration': duration,
            'photo_path': basic_info.get('photo_path', 'N/A'),
            'profile_link': basic_info.get('profile_link', 'N/A'),
            'room_id': room_id,
            'room_name': room_name,
        })
    return visitors_data


@app.route('/blacklist')
def blacklist_page():
    """List only blacklisted individuals with verbose details and option to remove from blacklist."""
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        visitors_ref = db.reference('visitors')
        all_visitors = visitors_ref.get() or {}
    visitors_data = _build_visitor_list_from_raw(all_visitors)
    filtered_visitors = [v for v in visitors_data if v['blacklisted']]
    filtered_visitors.sort(key=lambda x: x['last_visit_time'] or datetime.min, reverse=True)
    total_blacklisted = len(filtered_visitors)
    per_page = 10
    page = int(request.args.get('page', 1))
    total_pages = max(1, (total_blacklisted + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = filtered_visitors[start_idx:end_idx]
    showing_start = start_idx + 1 if total_blacklisted else 0
    showing_end = min(end_idx, total_blacklisted)

    BLACKLIST_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Blacklisted Individuals | Admin Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            .card-hover { transition: all 0.2s ease; }
            .card-hover:hover { box-shadow: 0 10px 25px -5px rgba(0,0,0,0.08); }
            #toast-container { position: fixed; top: 1rem; right: 1rem; z-index: 9999; display: flex; flex-direction: column; gap: 0.5rem; pointer-events: none; }
            .toast { padding: 0.75rem 1.25rem; border-radius: 0.5rem; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.15); font-medium; pointer-events: auto; animation: toast-in 0.25s ease; }
            .toast.success { background: #10b981; color: white; }
            .toast.error { background: #ef4444; color: white; }
            @keyframes toast-in { from { opacity: 0; transform: translateX(100%); } to { opacity: 1; transform: translateX(0); } }
            .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 9000; display: flex; align-items: center; justify-content: center; padding: 1rem; opacity: 0; visibility: hidden; transition: opacity 0.2s, visibility 0.2s; }
            .modal-overlay.show { opacity: 1; visibility: visible; }
            .modal-box { background: white; border-radius: 0.75rem; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); max-width: 28rem; width: 100%; padding: 1.5rem; }
            .modal-box h3 { margin: 0 0 1rem 0; font-size: 1.125rem; font-weight: 600; color: #111; }
            .modal-box textarea { width: 100%; min-height: 100px; padding: 0.5rem 0.75rem; border: 1px solid #d1d5db; border-radius: 0.5rem; font-size: 0.875rem; resize: vertical; box-sizing: border-box; }
            .modal-box .modal-actions { margin-top: 1rem; display: flex; gap: 0.5rem; justify-content: flex-end; }
            .modal-box .modal-actions button { padding: 0.5rem 1rem; border-radius: 0.5rem; font-weight: 500; font-size: 0.875rem; cursor: pointer; }
            .modal-box .modal-actions .btn-primary { background: #2563eb; color: white; border: none; }
            .modal-box .modal-actions .btn-primary:hover { background: #1d4ed8; }
            .modal-box .modal-actions .btn-secondary { background: #e5e7eb; color: #374151; border: none; }
            .modal-box .modal-actions .btn-secondary:hover { background: #d1d5db; }
            .modal-box .modal-actions .btn-danger { background: #dc2626; color: white; border: none; }
            .modal-box .modal-actions .btn-danger:hover { background: #b91c1c; }
        </style>
    </head>
    <body class="bg-gray-50 min-h-screen">
        <div class="bg-white shadow-sm border-b">
            <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
                <div class="flex flex-wrap items-center justify-between gap-4">
                    <div>
                        <h1 class="text-2xl font-bold text-gray-900">Blacklisted Individuals</h1>
                        <p class="text-sm text-gray-600 mt-1">View details and remove visitors from the blacklist. Total: <strong>{{ total_blacklisted }}</strong></p>
                    </div>
                    <div class="flex items-center gap-3">
                        <a href="{{ url_for('blacklist_export') }}" class="inline-flex items-center px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 text-gray-700 font-medium text-sm">
                            <i class="fas fa-file-export mr-2"></i>Export CSV
                        </a>
                        <a href="{{ url_for('index') }}" class="text-gray-600 hover:text-gray-900 flex items-center">
                            <i class="fas fa-home mr-2"></i>Admin Home
                        </a>
                        <a href="{{ url_for('visitors_list') }}" class="text-blue-600 hover:text-blue-800 flex items-center font-medium">
                            <i class="fas fa-users mr-2"></i>All Visitors
                        </a>
                    </div>
                </div>
            </div>
        </div>

        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            {% if total_blacklisted == 0 %}
            <div class="bg-white rounded-xl border border-gray-200 p-12 text-center">
                <div class="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-100 text-green-600 mb-4">
                    <i class="fas fa-check-circle text-3xl"></i>
                </div>
                <h2 class="text-xl font-semibold text-gray-800 mb-2">No blacklisted individuals</h2>
                <p class="text-gray-600 mb-6">There are no visitors currently on the blacklist.</p>
                <a href="{{ url_for('visitors_list') }}" class="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                    <i class="fas fa-users mr-2"></i>View all visitors
                </a>
            </div>
            {% else %}
            <p class="text-sm text-gray-500 mb-4">Showing {{ showing_start }}–{{ showing_end }} of {{ total_blacklisted }}</p>
            <div class="space-y-6">
                {% for visitor in paginated %}
                <div class="bg-white rounded-xl border border-red-100 shadow-sm overflow-hidden card-hover">
                    <div class="p-6">
                        <div class="flex flex-wrap items-start justify-between gap-4">
                            <div class="flex-1 min-w-0">
                                <h3 class="text-lg font-semibold text-gray-900">{{ visitor.name }}</h3>
                                <p class="text-sm text-gray-500 font-mono mt-0.5">ID: {{ visitor.unique_id }}</p>
                                <div class="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2 text-sm">
                                    <div><span class="text-gray-500">Contact:</span> <span class="text-gray-900">{{ visitor.contact }}</span></div>
                                    <div><span class="text-gray-500">Email:</span> <span class="text-gray-900">{{ visitor.email }}</span></div>
                                    <div><span class="text-gray-500">Company:</span> <span class="text-gray-900">{{ visitor.company }}</span></div>
                                </div>
                                <div class="mt-4 p-3 bg-red-50 rounded-lg border border-red-100">
                                    <p class="text-xs font-medium text-red-800 uppercase tracking-wide">Blacklist reason</p>
                                    <p class="text-sm text-gray-800 mt-1" id="reason-{{ visitor.id|e }}">{{ visitor.blacklist_reason }}</p>
                                    {% if visitor.blacklisted_at %}
                                    <p class="text-xs text-gray-500 mt-2">Added on {{ visitor.blacklisted_at }}</p>
                                    {% endif %}
                                </div>
                                <div class="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-2 text-sm">
                                    <div><span class="text-gray-500">Visits:</span> <span class="text-gray-900">{{ visitor.num_visits }}</span></div>
                                    <div><span class="text-gray-500">Last visit:</span> <span class="text-gray-900">{{ visitor.visit_date }}</span></div>
                                    <div><span class="text-gray-500">Last purpose:</span> <span class="text-gray-900">{{ visitor.purpose }}</span></div>
                                    <div><span class="text-gray-500">Employee met:</span> <span class="text-gray-900">{{ visitor.employee_name }}</span></div>
                                    <div><span class="text-gray-500">Last status:</span> <span class="text-gray-900">{{ visitor.status }}</span></div>
                                    <div><span class="text-gray-500">Check-in:</span> <span class="text-gray-900">{{ visitor.check_in_time or 'N/A' }}</span></div>
                                    <div><span class="text-gray-500">Check-out:</span> <span class="text-gray-900">{{ visitor.check_out_time or 'N/A' }}</span></div>
                                    <div><span class="text-gray-500">Registered at:</span> <span class="text-gray-900">{{ visitor.registered_at }}</span></div>
                                </div>
                            </div>
                            <div class="flex flex-col gap-2 shrink-0">
                                <a href="{{ url_for('visitor_detail', visitor_id=visitor.id) }}#blacklist" class="inline-flex items-center justify-center px-4 py-2 bg-gray-100 text-gray-800 rounded-lg hover:bg-gray-200 text-sm font-medium">
                                    <i class="fas fa-user mr-2"></i>View full profile
                                </a>
                                <button type="button" class="edit-reason-btn inline-flex items-center justify-center px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 text-sm font-medium" data-visitor-id="{{ visitor.id|e }}" data-current-reason="{{ visitor.blacklist_reason|e }}">
                                    <i class="fas fa-edit mr-2"></i>Edit reason
                                </button>
                                <button type="button" class="remove-from-blacklist-btn inline-flex items-center justify-center px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium" data-visitor-id="{{ visitor.id|e }}">
                                    <i class="fas fa-user-check mr-2"></i>Remove from blacklist
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>

            {% if total_pages > 1 %}
            <div class="mt-8 flex flex-wrap items-center justify-center gap-2">
                {% if page > 1 %}
                <a href="{{ url_for('blacklist_page') }}?page={{ page - 1 }}" class="px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">Previous</a>
                {% endif %}
                <span class="px-4 py-2 text-gray-600">Page {{ page }} of {{ total_pages }}</span>
                {% if page < total_pages %}
                <a href="{{ url_for('blacklist_page') }}?page={{ page + 1 }}" class="px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">Next</a>
                {% endif %}
            </div>
            {% endif %}
            {% endif %}
        </div>

        <div id="toast-container" aria-live="polite"></div>

        <div id="edit-reason-modal" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="edit-reason-title">
            <div class="modal-box">
                <h3 id="edit-reason-title">Edit blacklist reason</h3>
                <textarea id="edit-reason-input" placeholder="Enter reason..." aria-label="Blacklist reason"></textarea>
                <div class="modal-actions">
                    <button type="button" class="btn-secondary" id="edit-reason-cancel">Cancel</button>
                    <button type="button" class="btn-primary" id="edit-reason-save">Save</button>
                </div>
            </div>
        </div>

        <div id="remove-confirm-modal" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="remove-confirm-title">
            <div class="modal-box">
                <h3 id="remove-confirm-title">Remove from blacklist?</h3>
                <p class="text-sm text-gray-600 mt-1">This visitor will be able to check in again.</p>
                <div class="modal-actions">
                    <button type="button" class="btn-secondary" id="remove-confirm-cancel">Cancel</button>
                    <button type="button" class="btn-danger" id="remove-confirm-yes">Remove from blacklist</button>
                </div>
            </div>
        </div>

        <script>
            document.addEventListener('DOMContentLoaded', function() {
                var toastContainer = document.getElementById('toast-container');
                function showToast(message, type) {
                    type = type || 'success';
                    var el = document.createElement('div');
                    el.className = 'toast ' + type;
                    el.setAttribute('role', 'status');
                    el.textContent = message;
                    toastContainer.appendChild(el);
                    setTimeout(function() { if (el.parentNode) el.parentNode.removeChild(el); }, 5000);
                }
                function doBlacklistPost(visitorId, blacklisted, reason, doneMsg) {
                    var url = '/blacklist/' + encodeURIComponent(visitorId);
                    fetch(url, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ blacklisted: blacklisted, reason: reason || '' })
                    }).then(function(r) { return r.text(); }).then(function(text) {
                        var data;
                        try { data = JSON.parse(text); } catch (_) { showToast('Server error or invalid response.', 'error'); return; }
                        if (data.success) { showToast(data.message || (blacklisted ? 'Reason updated.' : 'Removed from blacklist.'), 'success'); window.location.reload(); }
                        else showToast('Error: ' + (data.message || 'Request failed'), 'error');
                    }).catch(function(e) { showToast('Error: ' + (e.message || 'Could not update blacklist.'), 'error'); });
                }

                var editModal = document.getElementById('edit-reason-modal');
                var editInput = document.getElementById('edit-reason-input');
                var editSave = document.getElementById('edit-reason-save');
                var editCancel = document.getElementById('edit-reason-cancel');
                var pendingEditVisitorId = null;
                function openEditReasonModal(visitorId, currentReason) {
                    pendingEditVisitorId = visitorId;
                    editInput.value = currentReason || '';
                    editModal.classList.add('show');
                    editInput.focus();
                }
                function closeEditReasonModal() {
                    editModal.classList.remove('show');
                    pendingEditVisitorId = null;
                }
                editCancel.addEventListener('click', closeEditReasonModal);
                editModal.addEventListener('click', function(e) { if (e.target === editModal) closeEditReasonModal(); });
                editSave.addEventListener('click', function() {
                    var reason = (editInput.value || '').trim();
                    if (!reason) { showToast('Reason cannot be empty.', 'error'); return; }
                    if (!pendingEditVisitorId) return;
                    var visitorId = pendingEditVisitorId;
                    closeEditReasonModal();
                    doBlacklistPost(visitorId, true, reason, 'updated');
                });

                var removeModal = document.getElementById('remove-confirm-modal');
                var removeYes = document.getElementById('remove-confirm-yes');
                var removeCancel = document.getElementById('remove-confirm-cancel');
                var pendingRemoveVisitorId = null;
                function openRemoveConfirmModal(visitorId) {
                    pendingRemoveVisitorId = visitorId;
                    removeModal.classList.add('show');
                }
                function closeRemoveConfirmModal() {
                    removeModal.classList.remove('show');
                    pendingRemoveVisitorId = null;
                }
                removeCancel.addEventListener('click', closeRemoveConfirmModal);
                removeModal.addEventListener('click', function(e) { if (e.target === removeModal) closeRemoveConfirmModal(); });
                removeYes.addEventListener('click', function() {
                    if (!pendingRemoveVisitorId) return;
                    var vid = pendingRemoveVisitorId;
                    closeRemoveConfirmModal();
                    doBlacklistPost(vid, false, '', 'removed');
                });

                document.querySelectorAll('.remove-from-blacklist-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var visitorId = btn.getAttribute('data-visitor-id');
                        if (visitorId) openRemoveConfirmModal(visitorId);
                    });
                });
                document.querySelectorAll('.edit-reason-btn').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var visitorId = btn.getAttribute('data-visitor-id');
                        var currentReason = btn.getAttribute('data-current-reason') || '';
                        if (visitorId) openEditReasonModal(visitorId, currentReason);
                    });
                });
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(
        BLACKLIST_HTML,
        paginated=paginated,
        total_blacklisted=total_blacklisted,
        page=page,
        total_pages=total_pages,
        showing_start=showing_start,
        showing_end=showing_end
    )


@app.route('/blacklist/export')
def blacklist_export():
    """Export blacklisted visitors as CSV."""
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        visitors_ref = db.reference('visitors')
        all_visitors = visitors_ref.get() or {}
    visitors_data = _build_visitor_list_from_raw(all_visitors)
    filtered = [v for v in visitors_data if v.get('blacklisted')]
    filtered.sort(key=lambda x: x.get('blacklisted_at') or '', reverse=True)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Unique ID', 'Name', 'Contact', 'Email', 'Company', 'Blacklist Reason', 'Blacklisted At', 'Visits', 'Last Visit', 'Status'])
    for v in filtered:
        writer.writerow([
            v.get('unique_id', ''),
            v.get('name', ''),
            v.get('contact', ''),
            v.get('email', ''),
            v.get('company', ''),
            v.get('blacklist_reason', ''),
            v.get('blacklisted_at', ''),
            v.get('num_visits', 0),
            v.get('visit_date', ''),
            v.get('status', ''),
        ])
    filename = 'blacklist_report_' + datetime.now().strftime('%Y-%m-%d') + '.csv'
    resp = make_response(buf.getvalue().encode('utf-8-sig'))
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename="' + filename + '"'
    return resp


@app.route('/blacklist/<visitor_id>', methods=['POST'])
def toggle_blacklist(visitor_id):
    """Toggle or update blacklist status for a visitor (updates basic_info; stores blacklisted_at when adding)."""
    try:
        data = request.get_json() or {}
        visitor_id = str(visitor_id or '').strip()
        if not visitor_id:
            return jsonify({'success': False, 'message': 'Invalid visitor id'}), 400
        raw_blacklisted = data.get('blacklisted', False)
        if isinstance(raw_blacklisted, str):
            blacklisted = raw_blacklisted.strip().lower() in ('true', '1', 'yes', 'on')
        else:
            blacklisted = bool(raw_blacklisted)
        reason = (data.get('reason') or '').strip() or 'No reason provided'

        if USE_MOCK_DATA:
            all_visitors = get_mock_visitors()
            if visitor_id not in all_visitors:
                return jsonify({'success': False, 'message': 'Visitor not found'}), 404
            prev = _MOCK_BLACKLIST_STATE.get(visitor_id, {})
            # Editing reason for an already-blacklisted visitor should not create/refresh timestamp.
            prev_blacklisted_at = prev.get('blacklisted_at', '')
            _MOCK_BLACKLIST_STATE[visitor_id] = {
                'blacklisted': blacklisted,
                'reason': reason if blacklisted else 'No reason provided',
                'blacklisted_at': (
                    prev_blacklisted_at if (blacklisted and prev_blacklisted_at)
                    else (datetime.now().strftime('%Y-%m-%d %H:%M:%S') if blacklisted else '')
                )
            }
            return jsonify({
                'success': True,
                'message': f'Visitor {"blacklisted" if blacklisted else "unblacklisted"} successfully'
            })

        visitors_ref = db.reference('visitors')
        visitor_ref = visitors_ref.child(visitor_id)
        visitor_snapshot = visitor_ref.get() or {}
        # Backward compatibility: allow edits/removals for legacy malformed IDs
        # only when such a record already exists in Firebase.
        if not _is_valid_visitor_id(visitor_id) and not visitor_snapshot:
            return jsonify({'success': False, 'message': 'Invalid visitor id'}), 400
        if not visitor_snapshot:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        basic_info_ref = visitor_ref.child('basic_info')

        update_payload = {
            'blacklisted': 'yes' if blacklisted else 'no',
            'blacklist_reason': reason if blacklisted else 'No reason provided'
        }
        existing_basic = visitor_snapshot.get('basic_info') or {}
        existing_blacklisted = str(existing_basic.get('blacklisted', 'no')).strip().lower() in ('yes', 'true', '1')
        existing_blacklisted_at = existing_basic.get('blacklisted_at', '')
        if blacklisted:
            # Editing reason should keep original added-on time.
            update_payload['blacklisted_at'] = existing_blacklisted_at if existing_blacklisted and existing_blacklisted_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            update_payload['blacklisted_at'] = ''

        basic_info_ref.update(update_payload)

        # Send blacklist notification email when adding to blacklist (not when removing)
        if blacklisted and not existing_blacklisted:
            try:
                basic_info = visitor_snapshot.get('basic_info') or {}
                visitor_email = basic_info.get('contact') or basic_info.get('email')
                visitor_name = basic_info.get('name', 'Visitor')
                send_blacklist_notification_email(visitor_email, visitor_name, reason)
            except Exception as e:
                print(f"[!] Error sending blacklist notification email: {e}")

        return jsonify({
            'success': True,
            'message': f'Visitor {"blacklisted" if blacklisted else "unblacklisted"} successfully'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error updating blacklist status: {str(e)}'
        }), 500


def _get_most_recent_visit_id(visitor_data):
    """Return (visit_id, visit_data) for the most recent visit, or (None, None)."""
    visits = visitor_data.get('visits') or {}
    if not visits:
        return None, None
    sorted_visits = []
    for vid, vdata in visits.items():
        ts = vdata.get('created_at') or vdata.get('check_in_time')
        if ts:
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                sorted_visits.append((dt, vid, vdata))
            except ValueError:
                pass
    if not sorted_visits:
        return None, None
    sorted_visits.sort(key=lambda x: x[0], reverse=True)
    return sorted_visits[0][1], sorted_visits[0][2]


def _is_visitor_blacklisted(visitor_data):
    """Return True if visitor is blacklisted (basic_info.blacklisted or top-level blacklisted)."""
    if not visitor_data:
        return False
    basic_info = visitor_data.get('basic_info') or {}
    raw = basic_info.get('blacklisted', visitor_data.get('blacklisted', 'no'))
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ('yes', 'true', '1')


@app.route('/visitor/<visitor_id>/approve', methods=['POST'])
def visitor_approve(visitor_id):
    """Set visitor status to Approved (most recent visit + top-level). Blocked if visitor is blacklisted.
    Sends visitor an email with QR / check-in page link if SMTP is configured."""
    visitor_id = str(visitor_id or '').strip()
    if not _is_valid_visitor_id(visitor_id):
        return jsonify({'success': False, 'message': 'Invalid visitor id'}), 400
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
        data = all_visitors.get(visitor_id)
        if not data:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        if _is_visitor_blacklisted(data):
            return jsonify({'success': False, 'message': 'Cannot approve: visitor is blacklisted.'}), 403
        return jsonify({'success': True})
    try:
        ref = db.reference(f'visitors/{visitor_id}')
        data = ref.get()
        if not data:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        if _is_visitor_blacklisted(data):
            return jsonify({'success': False, 'message': 'Cannot approve: visitor is blacklisted.'}), 403
        visit_id, _ = _get_most_recent_visit_id(data)
        if visit_id:
            ref.child('visits').child(visit_id).update({'status': 'Approved'})
        ref.update({'status': 'Approved'})
        # Send QR / check-in link to visitor email (with QR image if payload exists)
        email_sent = False
        email_message = None
        try:
            basic_info = data.get("basic_info") or {}
            visitor_email = basic_info.get("contact") or basic_info.get("email") or ""
            visitor_name = basic_info.get("name", "Visitor")
            visit_data = (data.get("visits") or {}).get(visit_id) if visit_id else {}
            qr_payload = visit_data.get("qr_payload")

            # Normalize visit_date from DB (stored as YYYY-MM-DD) to dd-mm-yyyy for emails
            raw_date = visit_data.get("visit_date", "—")
            formatted_date = raw_date
            if isinstance(raw_date, str) and raw_date not in ("", "—"):
                try:
                    dt = datetime.strptime(raw_date, "%Y-%m-%d")
                    formatted_date = dt.strftime("%d-%m-%Y")
                except Exception:
                    formatted_date = raw_date

            visit_details = {
                "purpose": visit_data.get("purpose", "Not specified"),
                "duration": visit_data.get("duration", "Not specified"),
                "visit_date": formatted_date,
                "status": visit_data.get("status", "Approved"),
            }
            if visitor_email and str(visitor_email).strip() and str(visitor_email).strip() != "N/A":
                reg_url = os.getenv("REGISTRATION_APP_URL", "http://localhost:5001").rstrip("/")
                checkin_link = f"{reg_url}/check_in?visitor_id={visitor_id}"
                email_sent, email_message = send_qr_checkin_email(
                    visitor_email, visitor_name, checkin_link,
                    qr_payload=qr_payload, visit_details=visit_details
                )
                # Mark on the visit that a QR/check-in email was sent successfully
                if email_sent and not USE_MOCK_DATA and FIREBASE_AVAILABLE and visit_id:
                    try:
                        db.reference(f"visitors/{visitor_id}/visits/{visit_id}").update({
                            "qr_email_sent": True,
                            "qr_email_sent_at": datetime.utcnow().isoformat()
                        })
                    except Exception as flag_err:
                        print(f"[!] Failed to set qr_email_sent flag: {flag_err}")
            else:
                email_message = "No visitor email on file"
        except Exception as mail_err:
            email_message = str(mail_err)
        return jsonify({
            'success': True,
            'email_sent': email_sent,
            'email_message': email_message or ("QR email sent to visitor" if email_sent else None)
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/visitor/<visitor_id>/reject', methods=['POST'])
def visitor_reject(visitor_id):
    """Set visitor status to Rejected and notify them via email."""
    visitor_id = str(visitor_id or '').strip()
    if not _is_valid_visitor_id(visitor_id):
        return jsonify({'success': False, 'message': 'Invalid visitor id'}), 400
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
        if visitor_id not in all_visitors:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        return jsonify({'success': True})
    try:
        ref = db.reference(f'visitors/{visitor_id}')
        data = ref.get()
        if not data:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404

        # Optional rejection reason from JSON body (if provided by UI)
        rejection_reason = None
        if request.is_json:
            try:
                payload = request.get_json() or {}
                rejection_reason = (payload.get('reason') or '').strip() or None
            except Exception:
                rejection_reason = None

        visit_id, _ = _get_most_recent_visit_id(data)
        if visit_id:
            updates = {'status': 'Rejected'}
            if rejection_reason:
                updates['rejection_reason'] = rejection_reason
            ref.child('visits').child(visit_id).update(updates)
        ref.update({'status': 'Rejected'})

        # Send rejection email
        try:
            basic_info = data.get('basic_info') or {}
            visitor_email = basic_info.get('contact') or basic_info.get('email')
            visitor_name = basic_info.get('name', 'Visitor')
            send_rejection_notification_email(visitor_email, visitor_name, rejection_reason)
        except Exception as mail_err:
            print(f"[!] Failed to send rejection email: {mail_err}")

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/visitor/<visitor_id>/checkin', methods=['POST'])
def visitor_checkin(visitor_id):
    """Set visitor status to Checked In, set check_in_time and expected_checkout_time. Blocked if visitor is blacklisted."""
    visitor_id = str(visitor_id or '').strip()
    if not _is_valid_visitor_id(visitor_id):
        return jsonify({'success': False, 'message': 'Invalid visitor id'}), 400
    now = datetime.now()
    checkout_at = now + timedelta(hours=2)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    checkout_str = checkout_at.strftime('%Y-%m-%d %H:%M:%S')
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
        data = all_visitors.get(visitor_id)
        if not data:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        if _is_visitor_blacklisted(data):
            return jsonify({'success': False, 'message': 'Cannot check in: visitor is blacklisted.'}), 403
        return jsonify({'success': True})
    try:
        ref = db.reference(f'visitors/{visitor_id}')
        data = ref.get()
        if not data:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        if _is_visitor_blacklisted(data):
            return jsonify({'success': False, 'message': 'Cannot check in: visitor is blacklisted.'}), 403
        visit_id, _ = _get_most_recent_visit_id(data)
        if visit_id:
            ref.child('visits').child(visit_id).update({
                'status': 'Checked-In',
                'check_in_time': now_str,
                'expected_checkout_time': checkout_str
            })
        ref.update({
            'status': 'Checked-In',
            'check_in_time': now_str,
            'expected_checkout_time': checkout_str
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/visitor/<visitor_id>/checkout', methods=['POST'])
def visitor_checkout(visitor_id):
    """Set visitor status to Checked Out, set check_out_time."""
    visitor_id = str(visitor_id or '').strip()
    if not _is_valid_visitor_id(visitor_id):
        return jsonify({'success': False, 'message': 'Invalid visitor id'}), 400
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
        if visitor_id not in all_visitors:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        return jsonify({'success': True})
    try:
        ref = db.reference(f'visitors/{visitor_id}')
        data = ref.get()
        if not data:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        visit_id, _ = _get_most_recent_visit_id(data)
        if visit_id:
            ref.child('visits').child(visit_id).update({
                'status': 'Checked-Out',
                'check_out_time': now_str
            })
        ref.update({'status': 'Checked-Out', 'check_out_time': now_str})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/occupancy', methods=['GET'])
def api_occupancy():
    """Return current building occupancy (visitors with status Checked-In, not time-exceeded)."""
    try:
        if USE_MOCK_DATA:
            all_visitors = get_mock_visitors()
        else:
            visitors_ref = db.reference('visitors')
            all_visitors = visitors_ref.get() or {}

        current_time = datetime.now()
        current_occupancy = 0

        for visitor_id, visitor_data in all_visitors.items():
            status = visitor_data.get('status', 'Registered')
            if status != 'Checked-In':
                continue
            expected_checkout_str = visitor_data.get('expected_checkout_time', '')
            if expected_checkout_str and expected_checkout_str != 'N/A':
                try:
                    expected_checkout = datetime.strptime(
                        expected_checkout_str, '%Y-%m-%d %H:%M:%S'
                    )
                    if current_time > expected_checkout:
                        continue  # time exceeded, do not count
                except ValueError:
                    pass
            current_occupancy += 1

        return jsonify({
            'current_occupancy': current_occupancy,
            'timestamp': current_time.isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/occupancy_over_time', methods=['GET'])
def api_occupancy_over_time():
    """Return occupancy over the last 24 hours (24 one-hour buckets)."""
    try:
        analytics = get_visitor_analytics()
        occ = analytics.get('occupancy_over_time_last24', {'labels': [], 'data': []})
        return jsonify({
            'occupancy_over_time_last24': occ,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Load your trained sentiment model once (optional; may already be set above)
try:
    with open("sentiment_analysis.pkl", "rb") as f:
        sentiment_model = pickle.load(f)
except (FileNotFoundError, Exception):
    pass  # sentiment_model already set earlier or unavailable
from flask import Flask, render_template_string, request, abort # Import abort for 404
from datetime import datetime, timedelta
# Assuming db and db.reference are properly imported

# Removed duplicate commented-out route definition

@app.route('/visitor/<visitor_id>')
def visitor_detail(visitor_id):
    """Fetches and displays detailed information for a single visitor."""
    visitor_id = str(visitor_id or '').strip()
    if not _is_valid_visitor_id(visitor_id):
        return abort(400, description="Invalid visitor ID.")
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
        visitor_data = all_visitors.get(visitor_id)
    else:
        visitors_ref = db.reference('visitors')
        visitor_data = visitors_ref.child(visitor_id).get()
    
    if not visitor_data:
        # Return a 404 error if the ID is not found in the database
        return abort(404, description="Visitor record not found.")

    rooms_map = get_meeting_rooms()
    room_id, room_name = _extract_visitor_room(visitor_data, rooms_map)

    # 2. Extract data from the updated storage structure
    basic_info = visitor_data.get('basic_info', {})
    
    # Get visitor details from basic_info
    visitor_name = basic_info.get('name', 'N/A')
    visitor_contact = basic_info.get('contact', 'N/A')
    
    # Blacklist info from basic_info
    raw_blacklist = basic_info.get('blacklisted', 'no')
    if isinstance(raw_blacklist, str):
        blacklisted = raw_blacklist.strip().lower() in ['yes', 'true', '1']
    else:
        blacklisted = bool(raw_blacklist)
    blacklist_reason = basic_info.get('blacklist_reason', 'No reason provided')
    blacklisted_at = basic_info.get('blacklisted_at', '') or ''
    
    # Get photo information - use photo_url from basic_info
    photo_url = basic_info.get('photo_url', '')
    # Photos are served by registration app; use full URL so admin (different port) can load them
    if photo_url and str(photo_url).startswith('/'):
        registration_base = os.getenv('REGISTRATION_APP_URL', 'http://localhost:5001').rstrip('/')
        image_path = registration_base + photo_url
    else:
        image_path = photo_url if photo_url else None
    
    # Get visits collection
    visits = visitor_data.get('visits', {})
    num_visits = len(visits) if isinstance(visits, dict) else 0
    
    # Get the most recent visit details for main display
    current_status = 'Registered'
    purpose = 'N/A'
    employee_name = 'N/A'
    visit_date = 'N/A'
    duration = 'N/A'
    check_in_time = 'N/A'
    check_out_time = 'N/A'
    expected_checkout_time = 'N/A'
    
    if visits:
        # Find the most recent visit by timestamp
        sorted_visits = []
        for visit_id, visit_data in visits.items():
            visit_timestamp = visit_data.get('created_at') or visit_data.get('check_in_time')
            if visit_timestamp:
                try:
                    visit_dt = datetime.strptime(visit_timestamp, "%Y-%m-%d %H:%M:%S")
                    sorted_visits.append((visit_dt, visit_id, visit_data))
                except ValueError:
                    continue
        
        if sorted_visits:
            # Sort by timestamp (most recent first)
            sorted_visits.sort(key=lambda x: x[0], reverse=True)
            last_visit_time, recent_visit_id, recent_visit_data = sorted_visits[0]
            
            # Get status and details from the most recent visit
            status_from_visit = recent_visit_data.get('status', 'Registered')
            # Normalize status values
            if status_from_visit.lower() in ['checked_out', 'checked-out', 'checked out']:
                current_status = 'Checked Out'
            elif status_from_visit.lower() in ['checked_in', 'checked-in', 'checked in']:
                current_status = 'Checked In'
            elif status_from_visit.lower() in ['approved', 'approve']:
                current_status = 'Approved'
            elif status_from_visit.lower() in ['registered', 'register']:
                current_status = 'Registered'
            elif status_from_visit.lower() in ['rejected', 'reject']:
                current_status = 'Rejected'
            elif status_from_visit.lower() in ['rescheduled', 'reschedule']:
                current_status = 'Rescheduled'
            elif status_from_visit.lower() in ['exceeded', 'time_exceeded']:
                current_status = 'Exceeded'
            else:
                current_status = status_from_visit
            
            purpose = recent_visit_data.get('purpose', 'N/A')
            employee_name = recent_visit_data.get('employee_name', 'N/A')
            visit_date = recent_visit_data.get('visit_date', 'N/A')
            duration = recent_visit_data.get('duration', 'N/A')
            check_in_time = recent_visit_data.get('check_in_time', 'N/A')
            check_out_time = recent_visit_data.get('check_out_time', 'N/A')
            expected_checkout_time = recent_visit_data.get('expected_checkout_time', 'N/A')

    # Determine if visitor has exceeded allowed time
    now = datetime.now()
    status = current_status
    if status == 'Checked In' and check_in_time != 'N/A' and expected_checkout_time != 'N/A':
        try:
            checkout_dt = datetime.strptime(expected_checkout_time, "%Y-%m-%d %H:%M:%S")
            if now > checkout_dt:
                status = 'Exceeded'
        except ValueError:
            pass

    # Get transactions for history
    transactions = visitor_data.get('transactions', {})
    registered_at = _registered_at_from_visitor(visitor_data)

    # Prepare visit history for display
    visit_history = []
    for visit_id, visit in visits.items():
        vrid = (visit.get('room_id') or '').strip()
        vroom_label = '—'
        if vrid:
            vroom_label = (rooms_map.get(vrid) or {}).get('name', '').strip() or vrid
        visit_history.append({
            'id': visit_id,
            'purpose': visit.get('purpose', 'N/A'),
            'employee_name': visit.get('employee_name', 'N/A'),
            'visit_date': visit.get('visit_date', 'N/A'),
            'check_in_time': visit.get('check_in_time', 'N/A'),
            'check_out_time': visit.get('check_out_time', 'N/A'),
            'expected_checkout_time': visit.get('expected_checkout_time', 'N/A'),
            'duration': visit.get('duration', 'N/A'),
            'status': visit.get('status', 'N/A'),
            'created_at': visit.get('created_at', 'N/A'),
            'room_id': vrid,
            'room_name': vroom_label,
        })
    
    # Sort visit history by date (newest first)
    visit_history.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    # Prepare the final data structure
    visitor = {
        'id': visitor_id,
        'unique_id': visitor_id,
        'name': visitor_name,
        'contact': visitor_contact,
        'purpose': purpose,
        'employee_name': employee_name,
        'duration': duration,
        'status': status,
        'blacklisted': blacklisted,
        'blacklist_reason': blacklist_reason,
        'blacklisted_at': blacklisted_at,
        'transactions': transactions,
        'visits': visits,
        'visit_history': visit_history,
        'visit_date': visit_date,
        'num_visits': num_visits,
        'check_in_time': check_in_time,
        'check_out_time': check_out_time,
        'expected_checkout_time': expected_checkout_time,
        'registered_at': registered_at,
        'image_path': image_path,
        'room_id': room_id,
        'room_name': room_name,
    }

    # 3. HTML Template for Detailed View
    DETAIL_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Visitor Detail: {{ visitor.name }}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            .status-badge {
                display: inline-flex;
                align-items: center;
                padding: 2px 10px;
                border-radius: 9999px;
                font-size: 0.75rem;
                font-weight: 600;
                text-transform: capitalize;
            }
            .card-hover {
                transition: all 0.3s ease;
            }
            .card-hover:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 25px -5px rgba(0, 0, 0, 0.1);
            }
            .gradient-bg {
                background: linear-gradient(135deg, #0f766e 0%, #134e4a 100%);
            }
            /* Toggle Switch Styles */
            .toggle-switch {
                position: relative;
                display: inline-block;
                width: 50px;
                height: 24px;
            }
            .toggle-switch input {
                opacity: 0;
                width: 0;
                height: 0;
            }
            .toggle-slider {
                position: absolute;
                cursor: pointer;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background-color: #ccc;
                transition: .4s;
                border-radius: 24px;
            }
            .toggle-slider:before {
                position: absolute;
                content: "";
                height: 16px;
                width: 16px;
                left: 4px;
                bottom: 4px;
                background-color: white;
                transition: .4s;
                border-radius: 50%;
            }
            input:checked + .toggle-slider {
                background-color: #EF4444;
            }
            input:checked + .toggle-slider:before {
                transform: translateX(26px);
            }
            .detail-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 9000; display: flex; align-items: center; justify-content: center; padding: 1rem; opacity: 0; visibility: hidden; transition: opacity 0.2s, visibility 0.2s; }
            .detail-modal-overlay.show { opacity: 1; visibility: visible; }
            .detail-modal-box { background: white; border-radius: 0.75rem; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); max-width: 28rem; width: 100%; padding: 1.5rem; }
            .detail-modal-box h3 { margin: 0 0 1rem 0; font-size: 1.125rem; font-weight: 600; color: #111; }
            .detail-modal-box textarea { width: 100%; min-height: 100px; padding: 0.5rem 0.75rem; border: 1px solid #d1d5db; border-radius: 0.5rem; font-size: 0.875rem; resize: vertical; box-sizing: border-box; }
            .detail-modal-box .modal-actions { margin-top: 1rem; display: flex; gap: 0.5rem; justify-content: flex-end; }
            .detail-modal-box .modal-actions button { padding: 0.5rem 1rem; border-radius: 0.5rem; font-weight: 500; font-size: 0.875rem; cursor: pointer; }
            .detail-modal-box .modal-actions .btn-primary { background: #2563eb; color: white; border: none; }
            .detail-modal-box .modal-actions .btn-primary:hover { background: #1d4ed8; }
            .detail-modal-box .modal-actions .btn-secondary { background: #e5e7eb; color: #374151; border: none; }
            .detail-modal-box .modal-actions .btn-secondary:hover { background: #d1d5db; }
            .detail-modal-box .modal-actions .btn-danger { background: #dc2626; color: white; border: none; }
            .detail-modal-box .modal-actions .btn-danger:hover { background: #b91c1c; }
        </style>
        <script>
            async function doVisitorAction(visitorId, action) {
                var endpoint = '/visitor/' + encodeURIComponent(visitorId) + '/' + action;
                var msg = action === 'approve' ? 'Approve' : action === 'reject' ? 'Reject' : action === 'checkin' ? 'Check-in' : 'Check-out';
                if (action === 'reject' && !confirm('Reject this visitor? You can add a reason on the next screen.')) return;
                try {
                    var r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
                    var data = r.ok ? await r.json().catch(function() { return {}; }) : null;
                    if (r.ok && (data === null || data.success !== false)) {
                        var fullMsg = msg + ' successful.';
                        if (action === 'approve' && data && data.email_sent !== undefined) {
                            fullMsg += data.email_sent ? ' QR email sent to visitor.' : ' QR email not sent: ' + (data.email_message || 'unknown');
                        }
                        showNotification(fullMsg, 'success');
                        setTimeout(function() { location.reload(); }, 800);
                    } else {
                        showNotification('Error: ' + (data && data.message ? data.message : r.status), 'error');
                    }
                } catch (e) {
                    showNotification('Error: ' + e.message, 'error');
                }
            }
            async function doBlacklistAction(visitorId, blacklisted, reason) {
                try {
                    const r = await fetch('/blacklist/' + encodeURIComponent(visitorId), {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ blacklisted: blacklisted, reason: reason || '' })
                    });
                    const text = await r.text();
                    let result;
                    try { result = JSON.parse(text); } catch (_) { throw new Error(r.status ? 'Server error ' + r.status : 'Invalid response'); }
                    if (result.success) { showNotification(result.message, 'success'); setTimeout(function() { location.reload(); }, 1000); }
                    else throw new Error(result.message || 'Request failed');
                } catch (e) { showNotification('Error: ' + e.message, 'error'); }
            }
            function showNotification(message, type) {
                var existing = document.getElementById('visitor-detail-notification');
                if (existing) existing.remove();
                var el = document.createElement('div');
                el.id = 'visitor-detail-notification';
                el.className = 'fixed top-4 right-4 z-50 px-6 py-3 rounded-lg shadow-lg text-white font-medium ' + (type === 'success' ? 'bg-green-500' : type === 'error' ? 'bg-red-500' : 'bg-blue-500');
                el.textContent = message;
                document.body.appendChild(el);
                setTimeout(function() { if (el.parentNode) el.parentNode.removeChild(el); }, 5000);
            }
            document.addEventListener('DOMContentLoaded', function() {
                var reasonModal = document.getElementById('detail-reason-modal');
                var reasonTitle = document.getElementById('detail-reason-title');
                var reasonInput = document.getElementById('detail-reason-input');
                var reasonSave = document.getElementById('detail-reason-save');
                var reasonCancel = document.getElementById('detail-reason-cancel');
                function openReasonModal(title, initialValue, onSave) {
                    reasonTitle.textContent = title;
                    reasonInput.value = initialValue || '';
                    reasonModal.classList.add('show');
                    reasonInput.focus();
                    reasonSave.onclick = function() {
                        var reason = (reasonInput.value || '').trim();
                        if (!reason) { showNotification('Reason cannot be empty.', 'error'); return; }
                    reasonModal.classList.remove('show');
                    onSave(reason);
                    };
                }
                function closeReasonModal() {
                    reasonModal.classList.remove('show');
                }
                reasonCancel.addEventListener('click', closeReasonModal);
                reasonModal.addEventListener('click', function(e) { if (e.target === reasonModal) closeReasonModal(); });

                var removeModal = document.getElementById('detail-remove-confirm-modal');
                var removeYes = document.getElementById('detail-remove-confirm-yes');
                var removeCancel = document.getElementById('detail-remove-confirm-cancel');
                var pendingRemoveVisitorId = null;
                function openRemoveConfirmModal(visitorId, onConfirm) {
                    pendingRemoveVisitorId = visitorId;
                    removeModal.classList.add('show');
                    removeYes.onclick = function() {
                        removeModal.classList.remove('show');
                        var vid = pendingRemoveVisitorId;
                        pendingRemoveVisitorId = null;
                        if (vid) onConfirm(vid);
                    };
                }
                function closeRemoveConfirmModal() {
                    removeModal.classList.remove('show');
                    pendingRemoveVisitorId = null;
                }
                removeCancel.addEventListener('click', closeRemoveConfirmModal);
                removeModal.addEventListener('click', function(e) { if (e.target === removeModal) closeRemoveConfirmModal(); });

                document.querySelectorAll('.btn-add-blacklist-detail').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var visitorId = btn.getAttribute('data-visitor-id');
                        if (!visitorId) return;
                        openReasonModal('Add to blacklist', '', function(reason) {
                            doBlacklistAction(visitorId, true, reason);
                        });
                    });
                });
                document.querySelectorAll('.btn-remove-blacklist-detail').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var visitorId = btn.getAttribute('data-visitor-id');
                        if (visitorId) openRemoveConfirmModal(visitorId, function(vid) { doBlacklistAction(vid, false, ''); });
                    });
                });
                document.querySelectorAll('.btn-edit-reason-detail').forEach(function(btn) {
                    btn.addEventListener('click', function() {
                        var visitorId = btn.getAttribute('data-visitor-id');
                        var currentReason = btn.getAttribute('data-current-reason') || '';
                        if (!visitorId) return;
                        openReasonModal('Edit blacklist reason', currentReason, function(reason) {
                            doBlacklistAction(visitorId, true, reason);
                        });
                    });
                });
            });

        </script>
    </head>
    <body class="min-h-screen bg-gray-50">
        <!-- Header -->
        <div class="gradient-bg text-white p-6 shadow-lg">
            <div class="max-w-7xl mx-auto">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-4">
                        <a href="/visitors" class="text-white/90 hover:text-white transition-colors inline-flex items-center">
                            <i class="fas fa-arrow-left text-xl mr-2"></i>Back to Visitors
                        </a>
                        <div>
                            <h1 class="text-3xl font-bold">Visitor Details</h1>
                            <p class="text-teal-100">Complete information for {{ visitor.name }}</p>
                        </div>
                    </div>
                    <div class="text-right">
                        <p class="text-sm text-teal-200">Total Visits</p>
                        <p class="text-2xl font-bold">{{ visitor.num_visits }}</p>
                    </div>
                </div>
            </div>
        </div>

        <div class="max-w-7xl mx-auto p-6 -mt-8">
            <!-- Main Card -->
            <div class="bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
                <!-- Visitor Header -->
                <div class="bg-gradient-to-r from-slate-50 to-gray-100 p-8 border-b border-gray-200">
                    <div class="flex flex-col lg:flex-row items-start lg:items-center justify-between">
                        <div class="flex items-center space-x-6 mb-4 lg:mb-0">
                            <div class="relative">
                                {% if visitor.image_path %}
                                <img src="{{ visitor.image_path }}" 
                                     alt="{{ visitor.name }}" 
                                     class="w-24 h-24 rounded-2xl object-cover border-4 border-white shadow-lg">
                                {% else %}
                                <div class="w-24 h-24 rounded-2xl bg-gradient-to-br from-teal-600 to-cyan-700 flex items-center justify-center text-white text-2xl font-bold border-4 border-white shadow-lg">
                                    {{ visitor.name[0]|upper if visitor.name and visitor.name != 'N/A' else '?' }}
                                </div>
                                {% endif %}
                                <div class="absolute -bottom-2 -right-2 bg-white rounded-full p-1 shadow-lg">
                                    {% if visitor.status == 'Checked In' %}
                                    <div class="w-6 h-6 bg-green-500 rounded-full border-2 border-white"></div>
                                    {% elif visitor.status == 'Exceeded' %}
                                    <div class="w-6 h-6 bg-red-500 rounded-full border-2 border-white"></div>
                                    {% elif visitor.status == 'Checked Out' %}
                                    <div class="w-6 h-6 bg-gray-500 rounded-full border-2 border-white"></div>
                                    {% else %}
                                    <div class="w-6 h-6 bg-yellow-500 rounded-full border-2 border-white"></div>
                                    {% endif %}
                                </div>
                            </div>
                            <div>
                                <h2 class="text-3xl font-bold text-gray-900">{{ visitor.name }}</h2>
                                <p class="text-gray-600 mt-1">{{ visitor.contact }}</p>
                                <p class="text-sm text-gray-500 mt-1">ID: {{ visitor.unique_id }}</p>
                            </div>
                        </div>
                        
                        <!-- Status Badge -->
                        <div class="bg-white rounded-xl px-6 py-3 shadow-lg border">
                            {% set status_config = {
                                'Registered': {'color': 'gray', 'icon': 'user-plus', 'text': 'text-gray-700'},
                                'Pending Approval': {'color': 'gray', 'icon': 'clock', 'text': 'text-gray-700'},
                                'Approved': {'color': 'yellow', 'icon': 'check-circle', 'text': 'text-yellow-700'},
                                'Checked In': {'color': 'green', 'icon': 'user-check', 'text': 'text-green-700'},
                                'Checked Out': {'color': 'purple', 'icon': 'user-times', 'text': 'text-purple-700'},
                                'Rescheduled': {'color': 'blue', 'icon': 'calendar-alt', 'text': 'text-blue-700'},
                                'Rejected': {'color': 'red', 'icon': 'times-circle', 'text': 'text-red-700'},
                                'Exceeded': {'color': 'orange', 'icon': 'exclamation-triangle', 'text': 'text-orange-700'}
                            } %}
                            {% set config = status_config.get(visitor.status, {'color': 'gray', 'icon': 'question', 'text': 'text-gray-700'}) %}
                            <div class="flex items-center space-x-3">
                                <div class="flex items-center">
                                    <i class="fas fa-{{ config.icon }} text-2xl {{ config.text }}"></i>
                                </div>
                                <div>
                                    <p class="text-sm text-gray-500">Current Status</p>
                                    <p class="text-lg font-bold {{ config.text }}">{{ visitor.status }}</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Main Content Grid -->
                <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 p-8">
                    <!-- Personal Information -->
                    <div class="lg:col-span-2 space-y-6">
                        <h3 class="text-xl font-semibold text-gray-900 border-b pb-3 flex items-center">
                            <i class="fas fa-user-circle mr-3 text-blue-500"></i>
                            Personal Information
                        </h3>
                        
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div class="bg-gray-50 rounded-xl p-4 card-hover">
                                <div class="flex items-center space-x-3">
                                    <div class="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
                                        <i class="fas fa-envelope text-blue-600"></i>
                                    </div>
                                    <div>
                                        <p class="text-sm text-gray-500">Contact</p>
                                        <p class="font-semibold text-gray-900">{{ visitor.contact }}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="bg-gray-50 rounded-xl p-4 card-hover">
                                <div class="flex items-center space-x-3">
                                    <div class="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                                        <i class="fas fa-calendar-day text-green-600"></i>
                                    </div>
                                    <div>
                                        <p class="text-sm text-gray-500">Registered</p>
                                        <p class="font-semibold text-gray-900">{{ visitor.registered_at }}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="bg-gray-50 rounded-xl p-4 card-hover">
                                <div class="flex items-center space-x-3">
                                    <div class="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center">
                                        <i class="fas fa-bullseye text-purple-600"></i>
                                    </div>
                                    <div>
                                        <p class="text-sm text-gray-500">Purpose</p>
                                        <p class="font-semibold text-gray-900">{{ visitor.purpose }}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="bg-gray-50 rounded-xl p-4 card-hover">
                                <div class="flex items-center space-x-3">
                                    <div class="w-10 h-10 bg-indigo-100 rounded-lg flex items-center justify-center">
                                        <i class="fas fa-user-tie text-indigo-600"></i>
                                    </div>
                                    <div>
                                        <p class="text-sm text-gray-500">Employee</p>
                                        <p class="font-semibold text-gray-900">{{ visitor.employee_name if visitor.employee_name != 'N/A' else 'Not specified' }}</p>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="bg-gray-50 rounded-xl p-4 card-hover">
                                <div class="flex items-center space-x-3">
                                    <div class="w-10 h-10 bg-teal-100 rounded-lg flex items-center justify-center">
                                        <i class="fas fa-door-open text-teal-600"></i>
                                    </div>
                                    <div>
                                        <p class="text-sm text-gray-500">Meeting room</p>
                                        <p class="font-semibold text-gray-900">{{ visitor.room_name }}</p>
                                        {% if visitor.room_id %}
                                        <p class="text-xs text-gray-400 font-mono mt-0.5">{{ visitor.room_id }}</p>
                                        {% endif %}
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Visit Timeline -->
                        <div class="mt-8">
                            <h3 class="text-xl font-semibold text-gray-900 border-b pb-3 flex items-center">
                                <i class="fas fa-clock mr-3 text-green-500"></i>
                                Current Visit Details
                            </h3>
                            
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                                <div class="bg-gradient-to-br from-green-50 to-emerald-50 rounded-xl p-4 border border-green-200 card-hover">
                                    <div class="flex items-center space-x-3">
                                        <div class="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
                                            <i class="fas fa-sign-in-alt text-green-600"></i>
                                        </div>
                                        <div>
                                            <p class="text-sm text-gray-500">Check-In</p>
                                            <p class="font-semibold text-gray-900">{{ visitor.check_in_time }}</p>
                                        </div>
                                    </div>
                                </div>
                                
                                <div class="bg-gradient-to-br from-blue-50 to-cyan-50 rounded-xl p-4 border border-blue-200 card-hover">
                                    <div class="flex items-center space-x-3">
                                        <div class="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
                                            <i class="fas fa-hourglass-end text-blue-600"></i>
                                        </div>
                                        <div>
                                            <p class="text-sm text-gray-500">Expected Check-Out</p>
                                            <p class="font-semibold text-gray-900">{{ visitor.expected_checkout_time }}</p>
                                        </div>
                                    </div>
                                </div>
                                
                                <div class="bg-gradient-to-br from-purple-50 to-violet-50 rounded-xl p-4 border border-purple-200 card-hover">
                                    <div class="flex items-center space-x-3">
                                        <div class="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
                                            <i class="fas fa-sign-out-alt text-purple-600"></i>
                                        </div>
                                        <div>
                                            <p class="text-sm text-gray-500">Check-Out</p>
                                            <p class="font-semibold text-gray-900">{{ visitor.check_out_time if visitor.check_out_time != 'N/A' else 'Not checked out' }}</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Security & Actions -->
                    <div class="space-y-6" id="blacklist">
                        <!-- Blacklist module: add / remove / edit from here only -->
                        <div class="bg-white rounded-xl border {% if visitor.blacklisted %}border-red-300 bg-red-50{% else %}border-gray-200{% endif %} p-6 card-hover">
                            <h4 class="font-semibold text-gray-900 mb-4 flex items-center">
                                <i class="fas fa-ban text-red-600 mr-2"></i>
                                Blacklist
                            </h4>
                            {% if visitor.blacklisted %}
                            <p class="text-sm text-gray-700 mb-2"><strong>Reason:</strong> {{ visitor.blacklist_reason }}</p>
                            {% if visitor.blacklisted_at %}
                            <p class="text-xs text-gray-500 mb-4">Added on {{ visitor.blacklisted_at }}</p>
                            {% endif %}
                            <div class="flex flex-wrap gap-2">
                                <button type="button" class="btn-remove-blacklist-detail inline-flex items-center px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium" data-visitor-id="{{ visitor.id|e }}">
                                    <i class="fas fa-user-check mr-2"></i>Remove from blacklist
                                </button>
                                <button type="button" class="btn-edit-reason-detail inline-flex items-center px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 text-sm font-medium" data-visitor-id="{{ visitor.id|e }}" data-current-reason="{{ visitor.blacklist_reason|e }}">
                                    <i class="fas fa-edit mr-2"></i>Edit reason
                                </button>
                                <a href="{{ url_for('blacklist_page') }}" class="inline-flex items-center px-4 py-2 bg-gray-100 text-gray-800 rounded-lg hover:bg-gray-200 text-sm font-medium">
                                    <i class="fas fa-list mr-2"></i>View all blacklisted
                                </a>
                            </div>
                            {% else %}
                            <p class="text-sm text-gray-600 mb-4">This visitor is not on the blacklist. Add them to block check-in and access.</p>
                            <div class="flex flex-wrap gap-2">
                                <button type="button" class="btn-add-blacklist-detail inline-flex items-center px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm font-medium" data-visitor-id="{{ visitor.id|e }}">
                                    <i class="fas fa-ban mr-2"></i>Add to blacklist
                                </button>
                                <a href="{{ url_for('blacklist_page') }}" class="inline-flex items-center px-4 py-2 bg-gray-100 text-gray-800 rounded-lg hover:bg-gray-200 text-sm font-medium">
                                    <i class="fas fa-list mr-2"></i>View blacklist
                                </a>
                            </div>
                            {% endif %}
                        </div>

                        <!-- Quick Actions -->
                        <div class="bg-white rounded-xl border border-gray-200 p-6 card-hover">
                            <h4 class="font-semibold text-gray-900 mb-4 flex items-center">
                                <i class="fas fa-bolt text-yellow-500 mr-2"></i>
                                Quick Actions
                            </h4>
                            <div class="space-y-3">
                                {% if visitor.status == 'Registered' or visitor.status == 'Pending Approval' %}
                                <button type="button" onclick="doVisitorAction('{{ visitor.id|e }}', 'approve')"
                                        class="w-full bg-green-600 hover:bg-green-700 text-white font-medium py-2.5 px-4 rounded-lg transition flex items-center justify-center">
                                    <i class="fas fa-check-circle mr-2"></i> Approve
                                </button>
                                <button type="button" onclick="doVisitorAction('{{ visitor.id|e }}', 'reject')"
                                        class="w-full bg-red-600 hover:bg-red-700 text-white font-medium py-2.5 px-4 rounded-lg transition flex items-center justify-center">
                                    <i class="fas fa-times-circle mr-2"></i> Reject
                                </button>
                                {% elif visitor.status == 'Approved' %}
                                <button type="button" onclick="doVisitorAction('{{ visitor.id|e }}', 'checkin')"
                                        class="w-full bg-green-600 hover:bg-green-700 text-white font-medium py-2.5 px-4 rounded-lg transition flex items-center justify-center">
                                    <i class="fas fa-sign-in-alt mr-2"></i> Check-in
                                </button>
                                {% elif visitor.status == 'Checked In' %}
                                <button type="button" onclick="doVisitorAction('{{ visitor.id|e }}', 'checkout')"
                                        class="w-full bg-amber-600 hover:bg-amber-700 text-white font-medium py-2.5 px-4 rounded-lg transition flex items-center justify-center">
                                    <i class="fas fa-sign-out-alt mr-2"></i> Check-out
                                </button>
                                {% endif %}
                                <button onclick="window.print()"
                                        class="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2.5 px-4 rounded-lg transition flex items-center justify-center">
                                    <i class="fas fa-print mr-2"></i> Print Record
                                </button>
                                <button onclick="window.location.href='/visitors'"
                                        class="w-full bg-gray-200 hover:bg-gray-300 text-gray-800 font-medium py-2.5 px-4 rounded-lg transition flex items-center justify-center border border-gray-300">
                                    <i class="fas fa-arrow-left mr-2"></i> Back to Visitors
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Visit History -->
                <div class="border-t border-gray-200 p-8">
                    <h3 class="text-xl font-semibold text-gray-900 mb-6 flex items-center">
                        <i class="fas fa-history mr-3 text-purple-500"></i>
                        Visit History ({{ visitor.num_visits }} visits)
                    </h3>
                    
                    {% if visitor.visit_history %}
                    <div class="space-y-4">
                        {% for visit in visitor.visit_history %}
                        <div class="bg-gray-50 rounded-xl p-6 border border-gray-200 card-hover">
                            <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between">
                                <div class="flex-1">
                                    <div class="flex items-center space-x-4 mb-3">
                                        <span class="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm font-medium">
                                            Visit {{ loop.index }}
                                        </span>
                                        <span class="text-sm text-gray-500">{{ visit.visit_date }}</span>
                                        {% set visit_status_config = {
                                            'Checked In': {'color': 'green', 'icon': 'user-check'},
                                            'Checked Out': {'color': 'purple', 'icon': 'user-times'},
                                            'Exceeded': {'color': 'orange', 'icon': 'exclamation-triangle'},
                                            'Approved': {'color': 'yellow', 'icon': 'check-circle'},
                                            'Registered': {'color': 'gray', 'icon': 'user-plus'}
                                        } %}
                                        {% set visit_config = visit_status_config.get(visit.status, {'color': 'gray', 'icon': 'question'}) %}
                                        <span class="status-badge bg-{{ visit_config.color }}-100 text-{{ visit_config.color }}-800">
                                            <i class="fas fa-{{ visit_config.icon }} mr-1"></i>
                                            {{ visit.status }}
                                        </span>
                                    </div>
                                    
                                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                                        <div>
                                            <p class="text-gray-500">Purpose</p>
                                            <p class="font-medium text-gray-900">{{ visit.purpose }}</p>
                                        </div>
                                        <div>
                                            <p class="text-gray-500">Employee</p>
                                            <p class="font-medium text-gray-900">{{ visit.employee_name if visit.employee_name != 'N/A' else 'Not specified' }}</p>
                                        </div>
                                        <div>
                                            <p class="text-gray-500">Room</p>
                                            <p class="font-medium text-gray-900">{{ visit.room_name }}</p>
                                        </div>
                                        <div>
                                            <p class="text-gray-500">Duration</p>
                                            <p class="font-medium text-gray-900">{{ visit.duration if visit.duration != 'N/A' else 'Not specified' }}</p>
                                        </div>
                                    </div>
                                    
                                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3 text-xs">
                                        <div class="flex items-center space-x-2 text-gray-500">
                                            <i class="fas fa-sign-in-alt"></i>
                                            <span>Check-in: {{ visit.check_in_time if visit.check_in_time != 'N/A' else 'Not recorded' }}</span>
                                        </div>
                                        <div class="flex items-center space-x-2 text-gray-500">
                                            <i class="fas fa-sign-out-alt"></i>
                                            <span>Check-out: {{ visit.check_out_time if visit.check_out_time != 'N/A' else 'Not recorded' }}</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                    {% else %}
                    <div class="text-center py-12 text-gray-500">
                        <i class="fas fa-history text-5xl mb-4 opacity-50"></i>
                        <p class="text-lg font-medium">No visit history available</p>
                        <p class="text-sm mt-2">This visitor hasn't completed any visits yet.</p>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <div id="detail-reason-modal" class="detail-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="detail-reason-title">
            <div class="detail-modal-box">
                <h3 id="detail-reason-title">Blacklist reason</h3>
                <textarea id="detail-reason-input" placeholder="Enter reason..." aria-label="Blacklist reason"></textarea>
                <div class="modal-actions">
                    <button type="button" class="btn-secondary" id="detail-reason-cancel">Cancel</button>
                    <button type="button" class="btn-primary" id="detail-reason-save">Save</button>
                </div>
            </div>
        </div>

        <div id="detail-remove-confirm-modal" class="detail-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="detail-remove-confirm-title">
            <div class="detail-modal-box">
                <h3 id="detail-remove-confirm-title">Remove from blacklist?</h3>
                <p class="text-sm text-gray-600 mt-1">This visitor will be able to check in again.</p>
                <div class="modal-actions">
                    <button type="button" class="btn-secondary" id="detail-remove-confirm-cancel">Cancel</button>
                    <button type="button" class="btn-danger" id="detail-remove-confirm-yes">Remove from blacklist</button>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    registration_app_url = os.getenv('REGISTRATION_APP_URL', 'http://localhost:5001').rstrip('/')
    return render_template_string(DETAIL_HTML, visitor=visitor, registration_app_url=registration_app_url)
@app.route('/feedback_analysis')
def feedback_analysis():
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        visitors_ref = db.reference('visitors')
        all_visitors = visitors_ref.get() or {}

    feedback_results = []
    sentiment_counts = {"Positive": 0, "Neutral": 0, "Negative": 0}

    def analyze_sentiment(text):
        """Analyze sentiment of text using the loaded model"""
        if not text or not sentiment_model:
            return "Neutral"
        
        # Clean and preprocess text
        text = str(text).strip()
        if len(text) < 3:
            return "Neutral"
        
        # Skip irrelevant texts
        irrelevant_keywords = ['irrelevant', 'not relevant', 'none', 'na', 'n/a', 'no feedback']
        if any(keyword in text.lower() for keyword in irrelevant_keywords):
            return "Neutral"
        
        try:
            # Predict sentiment - adjust this based on your model's predict method
            prediction = sentiment_model.predict([text])[0]
            
            # Map prediction to sentiment labels
            # Adjust these mappings based on your model's output format
            if isinstance(prediction, (int, np.integer)):
                # If model returns 0, 1, 2 etc.
                if prediction == 0:
                    return "Negative"
                elif prediction == 1:
                    return "Neutral"
                elif prediction == 2:
                    return "Positive"
                else:
                    return "Neutral"
            elif isinstance(prediction, str):
                # If model returns string labels
                prediction_lower = prediction.lower()
                if 'pos' in prediction_lower:
                    return "Positive"
                elif 'neg' in prediction_lower:
                    return "Negative"
                else:
                    return "Neutral"
            else:
                return "Neutral"
                
        except Exception as e:
            print(f"Sentiment analysis error for text '{text}': {e}")
            return "Neutral"

    if all_visitors:
        for visitor_id, visitor_data in all_visitors.items():
            # Get basic_info for visitor details
            basic_info = visitor_data.get('basic_info', {})
            feedbacks = visitor_data.get('feedbacks', {})
            
            # Extract visitor name and contact from basic_info
            visitor_name = basic_info.get('name', 'Unknown')
            visitor_email = basic_info.get('contact', 'N/A')
            
            # Process all feedbacks for this visitor
            for feedback_id, feedback_data in feedbacks.items():
                text = feedback_data.get('text', '')
                timestamp = feedback_data.get('timestamp', 'N/A')
                
                # Skip empty feedback
                if not text:
                    continue

                # Perform Sentiment Analysis
                sentiment_label = analyze_sentiment(text)

                # Count sentiments
                if sentiment_label in sentiment_counts:
                    sentiment_counts[sentiment_label] += 1
                else:
                    sentiment_counts["Neutral"] += 1

                feedback_results.append({
                    "visitor_name": visitor_name,
                    "visitor_email": visitor_email,
                    "text": text,
                    "timestamp": timestamp,
                    "sentiment": sentiment_label
                })

    # Sort feedback by timestamp (newest first)
    feedback_results.sort(key=lambda x: x['timestamp'], reverse=True)

    return render_template_string("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Feedback Analysis</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body class="bg-gray-50 min-h-screen p-8">
        <div class="max-w-7xl mx-auto">
            <a href="{{ url_for('index') }}" class="text-gray-500 hover:text-gray-700 text-sm inline-flex items-center mb-2">
                <i class="fas fa-arrow-left mr-1"></i>Back to Admin
            </a>
            <h1 class="text-3xl font-bold text-gray-900 mb-8">Feedback Sentiment Analysis</h1>
            
            <!-- Sentiment Summary Cards -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                <div class="bg-green-100 border-l-4 border-green-500 p-6 rounded-lg shadow">
                    <div class="flex items-center">
                        <div class="flex-shrink-0">
                            <i class="fas fa-smile text-green-600 text-2xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-green-800">Positive</p>
                            <p class="text-2xl font-bold text-green-900">{{ sentiment_counts.Positive }}</p>
                        </div>
                    </div>
                </div>
                
                <div class="bg-yellow-100 border-l-4 border-yellow-500 p-6 rounded-lg shadow">
                    <div class="flex items-center">
                        <div class="flex-shrink-0">
                            <i class="fas fa-meh text-yellow-600 text-2xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-yellow-800">Neutral</p>
                            <p class="text-2xl font-bold text-yellow-900">{{ sentiment_counts.Neutral }}</p>
                        </div>
                    </div>
                </div>
                
                <div class="bg-red-100 border-l-4 border-red-500 p-6 rounded-lg shadow">
                    <div class="flex items-center">
                        <div class="flex-shrink-0">
                            <i class="fas fa-frown text-red-600 text-2xl"></i>
                        </div>
                        <div class="ml-4">
                            <p class="text-sm font-medium text-red-800">Negative</p>
                            <p class="text-2xl font-bold text-red-900">{{ sentiment_counts.Negative }}</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sentiment Chart -->
            <div class="bg-white p-6 rounded-lg shadow mb-8">
                <h2 class="text-xl font-semibold mb-4">Sentiment Distribution</h2>
                <div class="h-64">
                    <canvas id="sentimentChart"></canvas>
                </div>
            </div>

            <!-- Feedback Count -->
            <div class="bg-white p-4 rounded-lg shadow mb-4">
                <p class="text-lg font-semibold text-gray-700">
                    Total Feedback: {{ feedback_results|length }}
                </p>
            </div>

            <!-- Feedback List -->
            {% if feedback_results %}
            <div class="bg-white p-6 rounded-lg shadow mb-8 overflow-x-auto">
                <h2 class="text-xl font-semibold mb-4">Recent Feedback</h2>
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Visitor</th>
                            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Contact</th>
                            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Feedback</th>
                            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Sentiment</th>
                            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {% for r in feedback_results %}
                        <tr>
                            <td class="px-4 py-2 text-sm text-gray-900">{{ r.visitor_name }}</td>
                            <td class="px-4 py-2 text-sm text-gray-600">{{ r.visitor_email }}</td>
                            <td class="px-4 py-2 text-sm text-gray-700 max-w-md">{{ r.text }}</td>
                            <td class="px-4 py-2"><span class="px-2 py-1 text-xs font-medium rounded {% if r.sentiment == 'Positive' %}bg-green-100 text-green-800{% elif r.sentiment == 'Negative' %}bg-red-100 text-red-800{% else %}bg-yellow-100 text-yellow-800{% endif %}">{{ r.sentiment }}</span></td>
                            <td class="px-4 py-2 text-sm text-gray-500">{{ r.timestamp }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% endif %}

        </div>

        <script>
            // Sentiment Chart
            const ctx = document.getElementById('sentimentChart').getContext('2d');
            const sentimentChart = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: ['Positive', 'Neutral', 'Negative'],
                    datasets: [{
                        data: [
                            {{ sentiment_counts.Positive }},
                            {{ sentiment_counts.Neutral }},
                            {{ sentiment_counts.Negative }}
                        ],
                        backgroundColor: [
                            '#10B981',
                            '#F59E0B',
                            '#EF4444'
                        ],
                        borderWidth: 2,
                        borderColor: '#fff'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom'
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    const label = context.label || '';
                                    const value = context.raw || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = total > 0 ? Math.round((value / total) * 100) : 0;
                                    return `${label}: ${value} (${percentage}%)`;
                                }
                            }
                        }
                    }
                }
            });
        </script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    </body>
    </html>
    """, feedback_results=feedback_results, sentiment_counts=sentiment_counts)
# --------------------------
# Visitor Registration Page
# --------------------------
# Add preprocessing to clean text
def preprocess_feedback(text):
    # Remove extra whitespace, normalize text
    if not text:
        return ""
    text = ' '.join(str(text).split())
    if text.lower() in ['irrelevant', 'none', 'na', 'n/a']:
        return ""
    return text

@app.route('/register', methods=['GET', 'POST'])
def visitor_registration():
    token = request.args.get('token')
    if not token:
        return "Invalid registration link", 400

    invitation = db.reference(f'invitations/{token}').get()
    if not invitation:
        return "Token not found", 404

    if request.method == 'GET':
        REG_HTML = f"""
        <h1>Register for {invitation['email']}</h1>
        <form method="POST">
            <input type="text" name="name" placeholder="Full Name" required>
            <input type="text" name="purpose" placeholder="Purpose" required>
            <button type="submit">Submit</button>
        </form>
        """
        return render_template_string(REG_HTML)

    name = request.form.get('name')
    purpose = request.form.get('purpose')

    db.reference(f'visitors/{uuid.uuid4()}').set({
        'unique_id': str(uuid.uuid4())[:8],
        'name': name,
        'email': invitation['email'],
        'purpose': purpose,
        'status': 'Enrolled',
        'blacklisted': False,
        'transactions': {}
    })
    db.reference(f'invitations/{token}').update({'status': 'Completed'})
    return f"Registration complete for {name}"

# --------------------------
# Meeting Rooms Routes
# --------------------------
@app.route('/rooms')
def rooms_list():
    """List meeting rooms with add/edit/delete and status (Available/Occupied)."""
    rooms = get_meeting_rooms()
    rooms_list_data = [{'id': rid, **data} for rid, data in rooms.items()]
    occupied_room_ids = _get_occupied_room_ids()
    if USE_MOCK_DATA:
        all_visitors_for_rooms = get_mock_visitors()
    else:
        all_visitors_for_rooms = db.reference('visitors').get() or {}
    registration_by_room = _registration_count_by_room(all_visitors_for_rooms)
    ROOMS_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Meeting Rooms - Admin</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    </head>
    <body class="bg-gray-50 min-h-screen">
        <div class="max-w-6xl mx-auto p-6">
            <div class="flex flex-wrap justify-between items-start gap-4 mb-6">
                <div>
                    <a href="/" class="text-blue-600 hover:underline text-sm mb-2 inline-block"><i class="fas fa-arrow-left mr-1"></i>Back to Admin</a>
                    <h1 class="text-2xl font-bold text-gray-900">Meeting Rooms</h1>
                    <p class="text-gray-500 text-sm">Add, edit, or remove rooms. &quot;Registered&quot; counts visitors whose latest visit selected that room when registering. Available/Occupied reflects check-in status.</p>
                </div>
                <button onclick="openAddModal()" class="bg-teal-600 hover:bg-teal-700 text-white px-4 py-2 rounded-lg flex items-center">
                    <i class="fas fa-plus mr-2"></i>Add Room
                </button>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" id="roomsCardContainer">
                {% for r in rooms_list_data %}
                <div class="bg-white rounded-xl shadow border border-gray-100 overflow-hidden flex flex-col">
                    <div class="p-4 flex-1">
                        <div class="flex justify-between items-start gap-2 mb-2">
                            <h3 class="text-lg font-semibold text-gray-900 truncate">{{ r.name }}</h3>
                            <span class="room-status-badge shrink-0 px-2 py-0.5 rounded-full text-xs font-medium
                                {% if r.id in occupied_room_ids %}bg-red-100 text-red-800{% else %}bg-green-100 text-green-800{% endif %}">
                                {% if r.id in occupied_room_ids %}Occupied{% else %}Available{% endif %}
                            </span>
                        </div>
                        <dl class="space-y-1 text-sm text-gray-600">
                            <div><span class="text-gray-500">Registered selection</span> <span class="font-semibold text-gray-800">{{ registration_by_room.get(r.id, 0) }}</span> <span class="text-gray-400">visitor(s)</span></div>
                            <div><span class="text-gray-500">Capacity</span> {{ r.capacity or '-' }}</div>
                            <div><span class="text-gray-500">Floor</span> {{ r.floor or '-' }}</div>
                            <div><span class="text-gray-500">Amenities</span> {{ (r.amenities or '-')[:50] }}{% if (r.amenities or '')|length > 50 %}...{% endif %}</div>
                        </dl>
                    </div>
                    <div class="px-4 py-3 bg-gray-50 border-t border-gray-100 flex flex-wrap gap-2 items-center">
                        {% if r.get('presentation_demo') %}
                        <span class="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1 font-medium">Demo room (read-only)</span>
                        {% else %}
                        <button type="button" class="text-blue-600 hover:underline text-sm" data-action="edit" data-id="{{ r.id }}" data-name="{{ r.name|e }}" data-capacity="{{ r.capacity }}" data-floor="{{ (r.floor or '')|e }}" data-amenities="{{ (r.amenities or '')|e }}">Edit</button>
                        <button type="button" class="text-red-600 hover:underline text-sm" data-action="delete" data-id="{{ r.id }}" data-name="{{ r.name|e }}">Delete</button>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
            {% if not rooms_list_data %}
            <p class="p-6 text-gray-500 text-center bg-white rounded-xl shadow">No rooms yet. Click "Add Room" to create one.</p>
            {% endif %}
        </div>
        <!-- Add/Edit Room Modal -->
        <div id="roomModal" class="fixed inset-0 bg-black/50 items-center justify-center z-50" style="display: none;">
            <div class="bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
                <h2 id="modalTitle" class="text-lg font-semibold mb-4">Add Room</h2>
                <form id="roomForm" onsubmit="submitRoom(event)">
                    <input type="hidden" id="roomId" name="room_id">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Name</label>
                            <input type="text" id="roomName" name="name" required class="w-full border rounded-lg px-3 py-2" placeholder="e.g. Conference A">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Capacity</label>
                            <input type="number" id="roomCapacity" name="capacity" min="1" class="w-full border rounded-lg px-3 py-2" placeholder="10">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Floor</label>
                            <input type="text" id="roomFloor" name="floor" class="w-full border rounded-lg px-3 py-2" placeholder="1">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Amenities</label>
                            <input type="text" id="roomAmenities" name="amenities" class="w-full border rounded-lg px-3 py-2" placeholder="Projector, Whiteboard">
                        </div>
                    </div>
                    <div class="flex justify-end gap-2 mt-6">
                        <button type="button" onclick="closeModal()" class="px-4 py-2 border rounded-lg hover:bg-gray-50">Cancel</button>
                        <button type="submit" class="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700">Save</button>
                    </div>
                </form>
            </div>
        </div>
        <script>
            function openAddModal() {
                document.getElementById('modalTitle').textContent = 'Add Room';
                document.getElementById('roomId').value = '';
                document.getElementById('roomName').value = '';
                document.getElementById('roomCapacity').value = '';
                document.getElementById('roomFloor').value = '';
                document.getElementById('roomAmenities').value = '';
                document.getElementById('roomModal').style.display = 'flex';
            }
            function openEditModal(id, name, capacity, floor, amenities) {
                document.getElementById('modalTitle').textContent = 'Edit Room';
                document.getElementById('roomId').value = id || '';
                document.getElementById('roomName').value = name || '';
                document.getElementById('roomCapacity').value = capacity !== undefined && capacity !== '' ? capacity : '';
                document.getElementById('roomFloor').value = floor || '';
                document.getElementById('roomAmenities').value = amenities || '';
                document.getElementById('roomModal').style.display = 'flex';
            }
            function closeModal() {
                document.getElementById('roomModal').style.display = 'none';
            }
            function submitRoom(e) {
                e.preventDefault();
                var id = document.getElementById('roomId').value;
                var data = {
                    name: document.getElementById('roomName').value,
                    capacity: document.getElementById('roomCapacity').value,
                    floor: document.getElementById('roomFloor').value,
                    amenities: document.getElementById('roomAmenities').value
                };
                var url = id ? '/api/rooms/' + encodeURIComponent(id) : '/api/rooms';
                var method = id ? 'PUT' : 'POST';
                fetch(url, { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
                    .then(function(r) { return r.json().then(function(d) { return r.ok ? d : Promise.reject(d); }); })
                    .then(function() { window.location.reload(); })
                    .catch(function(err) { alert(err.message || 'Failed to save'); });
            }
            function deleteRoom(id, name) {
                if (!confirm('Delete room "' + (name || id) + '"?')) return;
                fetch('/api/rooms/' + encodeURIComponent(id), { method: 'DELETE' })
                    .then(function(r) { return r.ok ? Promise.resolve() : r.json().then(function(d) { return Promise.reject(d); }); })
                    .then(function() { window.location.reload(); })
                    .catch(function() { alert('Failed to delete'); });
            }
            document.addEventListener('DOMContentLoaded', function() {
                var container = document.getElementById('roomsCardContainer');
                if (container) {
                    container.addEventListener('click', function(ev) {
                        var btn = ev.target.closest('button[data-action]');
                        if (!btn) return;
                        var action = btn.getAttribute('data-action');
                        if (action === 'edit') {
                            openEditModal(btn.getAttribute('data-id'), btn.getAttribute('data-name'), btn.getAttribute('data-capacity'), btn.getAttribute('data-floor') || '', btn.getAttribute('data-amenities') || '');
                        } else if (action === 'delete') {
                            deleteRoom(btn.getAttribute('data-id'), btn.getAttribute('data-name'));
                        }
                    });
                }
            });
        </script>
    </body>
    </html>
    """
    return render_template_string(ROOMS_HTML, rooms_list_data=rooms_list_data, occupied_room_ids=occupied_room_ids, registration_by_room=registration_by_room)

@app.route('/api/rooms', methods=['POST'])
def api_rooms_create():
    """Create a new meeting room. JSON: name, capacity, floor, amenities."""
    try:
        data = request.get_json() or {}
        room_id = 'room_' + str(uuid.uuid4())[:8]
        save_meeting_room(room_id, data)
        return jsonify({'success': True, 'room_id': room_id})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/rooms/<room_id>', methods=['PUT'])
def api_rooms_update(room_id):
    """Update a meeting room. JSON: name, capacity, floor, amenities."""
    try:
        if room_id in PRESENTATION_ROOM_IDS:
            return jsonify({'success': False, 'message': 'Demo rooms cannot be edited'}), 403
        data = request.get_json() or {}
        save_meeting_room(room_id, data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/rooms/<room_id>', methods=['DELETE'])
def api_rooms_delete(room_id):
    """Delete a meeting room."""
    try:
        if room_id in PRESENTATION_ROOM_IDS:
            return jsonify({'success': False, 'message': 'Demo rooms cannot be deleted'}), 403
        delete_meeting_room(room_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/api/rooms/list')
def api_rooms_list():
    """Return all meeting rooms (for registration app or other consumers). Each value includes registration_count from latest visit room selection."""
    rooms = get_meeting_rooms()
    if USE_MOCK_DATA:
        all_visitors = get_mock_visitors()
    else:
        all_visitors = db.reference('visitors').get() or {}
    counts = _registration_count_by_room(all_visitors)
    out = {}
    for rid, meta in rooms.items():
        row = dict(meta)
        row['registration_count'] = int(counts.get(rid, 0))
        out[rid] = row
    return jsonify(out)


@app.route('/api/notify_host_time_exceeded', methods=['POST'])
def api_notify_host_time_exceeded():
    """Send a notification email to the host (employee) for a time-exceeded visitor."""
    try:
        data = request.get_json() or {}
        visitor_id = str(data.get('visitor_id') or '').strip()
        if not _is_valid_visitor_id(visitor_id):
            return jsonify({'success': False, 'message': 'visitor_id required'}), 400
        if USE_MOCK_DATA:
            all_visitors = get_mock_visitors()
            all_employees = get_mock_employees()
        else:
            all_visitors = (db.reference('visitors').get() or {})
            all_employees = (db.reference('employees').get() or {})
        visitor_data = all_visitors.get(visitor_id)
        if not visitor_data:
            return jsonify({'success': False, 'message': 'Visitor not found'}), 404
        employee_name = (visitor_data.get('employee_name') or '').strip()
        if not employee_name:
            return jsonify({'success': False, 'message': 'No host (employee) assigned to this visit'}), 400
        host_email = None
        for eid, emp in all_employees.items():
            if (emp.get('name') or '').strip().lower() == employee_name.lower():
                host_email = (emp.get('email') or '').strip()
                break
        if not host_email:
            return jsonify({'success': False, 'message': f'Host "{employee_name}" has no email on file'}), 400
        visitor_name = visitor_data.get('name', 'Unknown')
        subject = "Time exceeded: visitor still on premises"
        body = f"Hello,\n\nVisitor \"{visitor_name}\" has exceeded their expected stay and is still on premises.\n\nPlease follow up as needed.\n\n— Workplace Intelligence Platform Admin"
        if send_notification_email(host_email, subject, body):
            return jsonify({'success': True, 'message': f'Notification sent to {host_email}'})
        return jsonify({'success': False, 'message': 'Email could not be sent (check SMTP config)'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/rooms/suggest')
def api_rooms_suggest():
    """Suggest rooms by capacity: rooms with capacity >= count, sorted by capacity (best fit), top N."""
    try:
        count = request.args.get('count', type=int, default=5)
        if count is None or count < 1:
            count = 5
        top = min(request.args.get('top', type=int, default=3) or 3, 10)
        rooms = get_meeting_rooms()
        suitable = [(rid, r) for rid, r in rooms.items() if (r.get('capacity') or 0) >= count]
        suitable.sort(key=lambda x: x[1].get('capacity', 0))
        result = [{'room_id': rid, 'name': r.get('name', rid), 'capacity': r.get('capacity'), 'floor': r.get('floor'), 'amenities': r.get('amenities', '')} for rid, r in suitable[:top]]
        return jsonify({'suggestions': result})
    except Exception as e:
        return jsonify({'suggestions': [], 'error': str(e)})

# --------------------------
# Employee Management Routes
# --------------------------
@app.route('/employees')
def employees_list():
    if USE_MOCK_DATA:
        all_employees = get_mock_employees()
        all_visitors = get_mock_visitors()
    else:
        employees_ref = db.reference('employees')
        visitors_ref = db.reference('visitors')
        all_employees = employees_ref.get() or {}
        all_visitors = visitors_ref.get() or {}
    
    # Calculate visitor counts for each employee
    employee_analytics = {}
    
    for emp_id, emp_data in all_employees.items():
        employee_name = emp_data.get('name', '')
        visitor_count = 0
        visitor_names = []
        
        # Check all visitors for association with this employee
        for visitor_id, visitor_data in all_visitors.items():
            # Get basic info from visitor
            basic_info = visitor_data.get('basic_info', {})
            visitor_name = basic_info.get('name', 'Unknown')
            
            # Check visits collection for employee association
            visits = visitor_data.get('visits', {})
            for visit_id, visit_data in visits.items():
                # Check if this visit is associated with the employee
                visit_employee_name = visit_data.get('employee_name', '')
                purpose = visit_data.get('purpose', '')
                
                # Multiple ways to associate visitor with employee:
                # 1. Direct employee name match in visit
                # 2. Employee name mentioned in purpose
                # 3. Employee name in transaction data
                if (visit_employee_name == employee_name or
                    employee_name.lower() in purpose.lower() or
                    employee_name.lower() in visitor_name.lower()):
                    
                    visitor_count += 1
                    if visitor_name not in visitor_names:
                        visitor_names.append(visitor_name)
                    break  # Count visitor only once per employee
            
            # Also check transactions for employee association
            transactions = visitor_data.get('transactions', {})
            for tx_id, tx_data in transactions.items():
                tx_employee_name = tx_data.get('employee_name', '')
                if tx_employee_name == employee_name:
                    visitor_count += 1
                    if visitor_name not in visitor_names:
                        visitor_names.append(visitor_name)
                    break
        
        employee_analytics[emp_id] = {
            'visitor_count': visitor_count,
            'recent_visitors': visitor_names[:5]  # Last 5 unique visitors
        }
    
    # Calculate total visitors (unique visitors across all employees)
    all_visitor_names = set()
    for analytics in employee_analytics.values():
        all_visitor_names.update(analytics['recent_visitors'])
    total_visitors = len(all_visitor_names)
    
    # Calculate average visitors per employee
    avg_visitors_per_employee = round(total_visitors / len(all_employees), 1) if all_employees else 0
    
    # Find top employee
    top_employee_id = None
    top_employee_count = 0
    for emp_id, analytics in employee_analytics.items():
        if analytics['visitor_count'] > top_employee_count:
            top_employee_count = analytics['visitor_count']
            top_employee_id = emp_id
    
    top_employee_name = all_employees.get(top_employee_id, {}).get('name', 'None') if top_employee_id else 'None'
    
    # Get unique departments
    departments = list(set(emp.get('department', 'Not Specified') for emp in all_employees.values()))
    
    # Safe JSON for embedding in HTML (prevents </script> in data from breaking the page)
    def _script_safe_json(obj):
        return json.dumps(obj, default=str).replace('<', '\\u003c')
    employees_json_safe = _script_safe_json(all_employees)
    analytics_json_safe = _script_safe_json(employee_analytics)
    
    EMP_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Employee Analytics Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            .metric-card {
                transition: all 0.3s ease;
                border-left: 4px solid;
            }
            .metric-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
            }
            .status-badge {
                display: inline-flex;
                align-items: center;
                padding: 2px 8px;
                border-radius: 9999px;
                font-size: 0.75rem;
                font-weight: 600;
            }
        </style>
    </head>
    <body class="bg-gradient-to-br from-blue-50 to-gray-100 min-h-screen p-6">
        <div class="max-w-7xl mx-auto">
            <!-- Header -->
            <div class="flex justify-between items-center mb-8">
                <div>
                    <a href="{{ url_for('index') }}" class="text-gray-500 hover:text-gray-700 text-sm inline-flex items-center mb-2">
                        <i class="fas fa-arrow-left mr-1"></i>Back to Admin
                    </a>
                    <h1 class="text-4xl font-bold text-gray-900">Employee Analytics</h1>
                    <p class="text-gray-600 mt-2">Comprehensive employee and visitor management dashboard</p>
                </div>
                <div class="flex space-x-4">
                    <button onclick="exportToCSV()" 
                            class="bg-white hover:bg-gray-50 text-gray-700 font-medium px-4 py-2 rounded-lg border border-gray-300 shadow-sm transition flex items-center">
                        <i class="fas fa-file-export mr-2"></i>Export CSV
                    </button>
                    <button onclick="openAddModal()" 
                            class="bg-green-600 hover:bg-green-700 text-white font-medium px-4 py-2 rounded-lg shadow-sm transition flex items-center">
                        <i class="fas fa-user-plus mr-2"></i>Add Employee
                    </button>
                </div>
            </div>

            <!-- Statistics Cards -->
            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
                <div class="metric-card bg-white rounded-xl p-6 shadow-sm border-l-blue-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Total Employees</p>
                            <p class="text-3xl font-bold text-gray-900">{{ employees|length }}</p>
                        </div>
                        <div class="p-3 bg-blue-100 rounded-lg">
                            <i class="fas fa-users text-blue-600 text-2xl"></i>
                        </div>
                    </div>
                </div>

                <div class="metric-card bg-white rounded-xl p-6 shadow-sm border-l-green-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Total Visitors</p>
                            <p class="text-3xl font-bold text-gray-900">{{ total_visitors }}</p>
                        </div>
                        <div class="p-3 bg-green-100 rounded-lg">
                            <i class="fas fa-user-check text-green-600 text-2xl"></i>
                        </div>
                    </div>
                </div>

                <div class="metric-card bg-white rounded-xl p-6 shadow-sm border-l-purple-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Avg Visitors/Employee</p>
                            <p class="text-3xl font-bold text-gray-900">{{ avg_visitors_per_employee }}</p>
                        </div>
                        <div class="p-3 bg-purple-100 rounded-lg">
                            <i class="fas fa-chart-line text-purple-600 text-2xl"></i>
                        </div>
                    </div>
                </div>

                <div class="metric-card bg-white rounded-xl p-6 shadow-sm border-l-orange-500">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-sm font-medium text-gray-600">Top Employee</p>
                            <p class="text-lg font-bold text-gray-900 truncate">{{ top_employee_name }}</p>
                            <p class="text-sm text-gray-500">{{ top_employee_count }} visitors</p>
                        </div>
                        <div class="p-3 bg-orange-100 rounded-lg">
                            <i class="fas fa-trophy text-orange-600 text-2xl"></i>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Employee Table -->
            <div class="bg-white rounded-xl shadow-sm overflow-hidden">
                <div class="px-6 py-4 border-b border-gray-200">
                    <div class="flex justify-between items-center">
                        <h3 class="text-xl font-semibold text-gray-900">Employee Directory</h3>
                        <div class="flex space-x-3">
                            <input type="text" id="searchInput" 
                                   placeholder="Search employees..." 
                                   class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                                   onkeyup="filterEmployees()">
                            <select id="deptFilter" onchange="filterEmployees()" 
                                    class="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                                <option value="all">All Departments</option>
                                {% for dept in departments %}
                                <option value="{{ dept|lower }}">{{ dept }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                </div>
                
                <div class="overflow-x-auto">
                    <table class="w-full">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Employee</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Contact</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Department</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Role</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Visitor Count</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Recent Visitors</th>
                                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            {% for emp_id, emp in employees.items() %}
                            <tr class="hover:bg-gray-50 transition-colors employee-row" data-dept="{{ (emp.department|default('Not Specified'))|lower|e }}" data-search="{{ ((emp.name|default('')) ~ ' ' ~ (emp.email|default('')) ~ ' ' ~ (emp.department|default('')) ~ ' ' ~ (emp.role|default('')) ~ ' ' ~ (emp.position|default('')) ~ ' ' ~ (emp.contact|default('')) ~ ' ' ~ (emp.phone|default('')))|lower|e }}">
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="flex items-center">
                                        <div class="flex-shrink-0 h-10 w-10 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-white font-bold">
                                            {{ emp.name[0]|upper if emp.name else '?' }}
                                        </div>
                                        <div class="ml-4">
                                            <div class="text-sm font-medium text-gray-900">{{ emp.name if emp.name else 'N/A' }}</div>
                                            <div class="text-sm text-gray-500">{{ emp.email if emp.email else 'N/A' }}</div>
                                        </div>
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm text-gray-900">{{ emp.contact or emp.phone or 'N/A' }}</div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <span class="status-badge bg-blue-100 text-blue-800">
                                        {{ emp.department if emp.department else 'Not Specified' }}
                                    </span>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="text-sm text-gray-900">{{ emp.role or emp.position or 'N/A' }}</div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap">
                                    <div class="flex items-center">
                                        <span class="text-lg font-bold text-gray-900 mr-2">
                                            {{ employee_analytics[emp_id].visitor_count if emp_id in employee_analytics else 0 }}
                                        </span>
                                        {% if emp_id in employee_analytics and employee_analytics[emp_id].visitor_count > 0 %}
                                        <span class="text-green-600 text-sm">
                                            <i class="fas fa-trending-up"></i>
                                        </span>
                                        {% endif %}
                                    </div>
                                </td>
                                <td class="px-6 py-4">
                                    <div class="text-sm text-gray-600 max-w-xs">
                                        {% if emp_id in employee_analytics and employee_analytics[emp_id].recent_visitors %}
                                            {% for visitor in employee_analytics[emp_id].recent_visitors %}
                                            <span class="inline-block bg-gray-100 rounded-full px-2 py-1 text-xs font-semibold text-gray-700 mr-1 mb-1">
                                                {{ visitor }}
                                            </span>
                                            {% endfor %}
                                            {% if employee_analytics[emp_id].recent_visitors|length >= 5 %}
                                            <span class="text-xs text-gray-400">+more</span>
                                            {% endif %}
                                        {% else %}
                                            <span class="text-gray-400 italic">No visitors</span>
                                        {% endif %}
                                    </div>
                                </td>
                                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                    <div class="flex space-x-2">
                                        <button type="button" onclick="editEmployee(this.getAttribute('data-emp-id'))" data-emp-id="{{ emp_id|e }}" 
                                                class="text-blue-600 hover:text-blue-900 transition-colors" 
                                                title="Edit Employee">
                                            <i class="fas fa-edit"></i>
                                        </button>
                                        
                                        <button type="button" onclick="viewEmployeeVisitors(this.getAttribute('data-emp-id'))" data-emp-id="{{ emp_id|e }}" 
                                                class="text-green-600 hover:text-green-900 transition-colors" 
                                                title="View Visitor Details">
                                            <i class="fas fa-eye"></i>
                                        </button>
                                        
                                        <button type="button" onclick="deleteEmployee(this.getAttribute('data-emp-id'))" data-emp-id="{{ emp_id|e }}" 
                                                class="text-red-600 hover:text-red-900 transition-colors" 
                                                title="Delete Employee">
                                            <i class="fas fa-trash"></i>
                                        </button>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>

            {% if not employees %}
            <div class="text-center py-12">
                <i class="fas fa-users text-4xl text-gray-400 mb-4"></i>
                <h3 class="text-xl font-semibold text-gray-600">No Employees Found</h3>
                <p class="text-gray-500 mt-2">Add your first employee to get started</p>
                <button onclick="openAddModal()" class="mt-4 bg-green-600 hover:bg-green-700 text-white font-medium px-6 py-2 rounded-lg transition">
                    Add Employee
                </button>
            </div>
            {% endif %}
        </div>

        <!-- Filter and actions script: no template vars so it never breaks; defines all button handlers -->
        <script>
        (function() {
            function filterEmployees() {
                var searchEl = document.getElementById('searchInput');
                var deptEl = document.getElementById('deptFilter');
                if (!searchEl || !deptEl) return;
                var search = (searchEl.value || '').trim().toLowerCase();
                var dept = (deptEl.value || '').trim().toLowerCase();
                var rows = document.querySelectorAll('tbody tr.employee-row');
                for (var i = 0; i < rows.length; i++) {
                    var row = rows[i];
                    var searchableText = (row.getAttribute('data-search') || '').toLowerCase();
                    var rowDept = (row.getAttribute('data-dept') || '').toLowerCase();
                    var show = true;
                    if (search && searchableText.indexOf(search) === -1) show = false;
                    if (dept && dept !== 'all' && rowDept !== dept) show = false;
                    row.style.display = show ? 'table-row' : 'none';
                }
            }
            function openAddModal() {
                var m = document.getElementById('employeeModal');
                if (!m) return;
                var t = document.getElementById('modalTitle');
                if (t) t.innerText = 'Add Employee';
                var id = document.getElementById('empId');
                if (id) id.value = '';
                var name = document.getElementById('empName');
                if (name) name.value = '';
                var email = document.getElementById('empEmail');
                if (email) email.value = '';
                var dept = document.getElementById('empDept');
                if (dept) dept.value = '';
                var role = document.getElementById('empRole');
                if (role) role.value = '';
                var contact = document.getElementById('empContact');
                if (contact) contact.value = '';
                m.classList.remove('hidden');
            }
            function closeModal() {
                var m = document.getElementById('employeeModal');
                if (m) m.classList.add('hidden');
            }
            function editEmployee(empId) {
                if (!empId) return;
                fetch('/get_employee/' + encodeURIComponent(empId))
                    .then(function(res) { if (!res.ok) throw new Error('Failed to load'); return res.json(); })
                    .then(function(data) {
                        var t = document.getElementById('modalTitle');
                        if (t) t.innerText = 'Edit Employee';
                        var id = document.getElementById('empId');
                        if (id) id.value = empId;
                        var name = document.getElementById('empName');
                        if (name) name.value = data.name || '';
                        var email = document.getElementById('empEmail');
                        if (email) email.value = data.email || '';
                        var dept = document.getElementById('empDept');
                        if (dept) dept.value = data.department || '';
                        var role = document.getElementById('empRole');
                        if (role) role.value = data.role || data.position || '';
                        var contact = document.getElementById('empContact');
                        if (contact) contact.value = data.contact || data.phone || '';
                        var m = document.getElementById('employeeModal');
                        if (m) m.classList.remove('hidden');
                    })
                    .catch(function() { alert('Error loading employee details'); });
            }
            function viewEmployeeVisitors(empId) {
                if (!empId) return;
                window.open('/employee/visitors/' + encodeURIComponent(empId), '_blank');
            }
            function deleteEmployee(empId) {
                if (!empId) return;
                if (confirm('Are you sure you want to delete this employee?')) {
                    fetch('/delete_employee/' + encodeURIComponent(empId), { method: 'POST' })
                        .then(function(res) { res.ok ? location.reload() : alert('Error deleting employee'); })
                        .catch(function() { alert('Error deleting employee'); });
                }
            }
            window.filterEmployees = filterEmployees;
            window.openAddModal = openAddModal;
            window.closeModal = closeModal;
            window.editEmployee = editEmployee;
            window.viewEmployeeVisitors = viewEmployeeVisitors;
            window.deleteEmployee = deleteEmployee;
        })();
        </script>

        <!-- Add/Edit Modal -->
        <div id="employeeModal" class="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50 hidden z-50">
            <div class="bg-white p-6 rounded-xl w-full max-w-md mx-4">
                <h2 class="text-2xl font-bold mb-4 text-gray-900" id="modalTitle">Add Employee</h2>
                <form id="employeeForm">
                    <input type="hidden" id="empId">
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Full Name</label>
                            <input type="text" id="empName" placeholder="Enter full name" 
                                   class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" required>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Email</label>
                            <input type="email" id="empEmail" placeholder="Enter email address" 
                                   class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" required>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Department</label>
                            <input type="text" id="empDept" placeholder="Enter department" 
                                   class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" required>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Role</label>
                            <input type="text" id="empRole" placeholder="Enter role" 
                                   class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" required>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 mb-1">Contact</label>
                            <input type="text" id="empContact" placeholder="Enter contact number" 
                                   class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500">
                        </div>
                    </div>
                    <div class="flex justify-end space-x-3 mt-6">
                        <button type="button" onclick="closeModal()" 
                                class="px-4 py-2 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition">
                            Cancel
                        </button>
                        <button type="submit" 
                                class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition">
                            Save Employee
                        </button>
                    </div>
                </form>
            </div>
        </div>

        <script type="application/json" id="employees-json">{{ employees_json_safe|safe }}</script>
        <script type="application/json" id="analytics-json">{{ analytics_json_safe|safe }}</script>
        <script>
            function openAddModal() {
                document.getElementById('modalTitle').innerText = "Add Employee";
                document.getElementById('empId').value = "";
                document.getElementById('empName').value = "";
                document.getElementById('empEmail').value = "";
                document.getElementById('empDept').value = "";
                document.getElementById('empRole').value = "";
                document.getElementById('empContact').value = "";
                document.getElementById('employeeModal').classList.remove('hidden');
            }

            function closeModal() {
                document.getElementById('employeeModal').classList.add('hidden');
            }

            function editEmployee(empId) {
                if (!empId) return;
                fetch('/get_employee/' + encodeURIComponent(empId))
                    .then(res => { if (!res.ok) throw new Error('Failed to load'); return res.json(); })
                    .then(data => {
                        document.getElementById('modalTitle').innerText = "Edit Employee";
                        document.getElementById('empId').value = empId;
                        document.getElementById('empName').value = data.name || '';
                        document.getElementById('empEmail').value = data.email || '';
                        document.getElementById('empDept').value = data.department || '';
                        document.getElementById('empRole').value = data.role || '';
                        document.getElementById('empContact').value = data.contact || '';
                        document.getElementById('employeeModal').classList.remove('hidden');
                    })
                    .catch(() => alert('Error loading employee details'));
            }

            function viewEmployeeVisitors(empId) {
                if (!empId) return;
                window.open('/employee/visitors/' + encodeURIComponent(empId), '_blank');
            }

            var employeeForm = document.getElementById('employeeForm');
            if (employeeForm) {
                employeeForm.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    var empId = document.getElementById('empId').value;
                    var payload = {
                        name: document.getElementById('empName').value,
                        email: document.getElementById('empEmail').value,
                        department: document.getElementById('empDept').value,
                        role: document.getElementById('empRole').value,
                        contact: document.getElementById('empContact').value
                    };
                    var url = empId ? '/edit_employee/' + encodeURIComponent(empId) : '/add_employee';
                    try {
                        var res = await fetch(url, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(payload)
                        });
                        if (res.ok) location.reload();
                        else alert("Error saving employee");
                    } catch (err) { alert("Error saving employee"); }
                });
            }

            function deleteEmployee(empId) {
                if (!empId) return;
                if (confirm("Are you sure you want to delete this employee?")) {
                    fetch('/delete_employee/' + encodeURIComponent(empId), { method: 'POST' })
                        .then(res => res.ok ? location.reload() : alert("Error deleting employee"))
                        .catch(() => alert("Error deleting employee"));
                }
            }

            function exportToCSV() {
                var headers = ['Name', 'Email', 'Department', 'Role', 'Contact', 'Visitor Count'];
                var rowsEl = document.getElementById('employees-json');
                var analyticsEl = document.getElementById('analytics-json');
                var rows = rowsEl ? JSON.parse(rowsEl.textContent || '{}') : {};
                var analytics = analyticsEl ? JSON.parse(analyticsEl.textContent || '{}') : {};

                var csvContent = headers.join(',') + '\n';
                
                Object.entries(rows).forEach(([empId, emp]) => {
                    const visitorCount = analytics[empId] ? analytics[empId].visitor_count : 0;
                    const role = emp.role || emp.position || '';
                    const contact = emp.contact || emp.phone || '';
                    const row = [
                        `"${(emp.name || '').replace(/"/g, '""')}"`,
                        `"${(emp.email || '').replace(/"/g, '""')}"`,
                        `"${(emp.department || '').replace(/"/g, '""')}"`,
                        `"${role.replace(/"/g, '""')}"`,
                        `"${contact.replace(/"/g, '""')}"`,
                        visitorCount
                    ];
                    csvContent += row.join(',') + '\n';
                });
                
                const blob = new Blob([csvContent], { type: 'text/csv' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.setAttribute('hidden', '');
                a.setAttribute('href', url);
                a.setAttribute('download', `employees_report_${new Date().toISOString().split('T')[0]}.csv`);
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            }
        </script>
    </body>
    </html>
    """
    
    return render_template_string(EMP_HTML, 
                                employees=all_employees,
                                employee_analytics=employee_analytics,
                                employees_json_safe=employees_json_safe,
                                analytics_json_safe=analytics_json_safe,
                                total_visitors=total_visitors,
                                avg_visitors_per_employee=avg_visitors_per_employee,
                                top_employee_name=top_employee_name,
                                top_employee_count=top_employee_count,
                                departments=departments)


def _visitors_for_employee(emp_id, all_employees, all_visitors):
    """Return list of visitor dicts for visitors linked to this employee (by visit or transaction)."""
    emp_data = all_employees.get(emp_id) if all_employees else None
    if not emp_data:
        return [], None
    employee_name = emp_data.get('name', '')
    results = []
    seen = set()
    for visitor_id, visitor_data in (all_visitors or {}).items():
        if visitor_id in seen:
            continue
        basic_info = visitor_data.get('basic_info', {})
        visitor_name = basic_info.get('name', 'Unknown')
        status = visitor_data.get('status', 'N/A')
        purpose = '—'
        linked = False
        for visit_id, visit_data in visitor_data.get('visits', {}).items():
            visit_employee_name = visit_data.get('employee_name', '')
            p = visit_data.get('purpose', '')
            if (visit_employee_name == employee_name or
                (employee_name and employee_name.lower() in (p or '').lower()) or
                (employee_name and employee_name.lower() in (visitor_name or '').lower())):
                purpose = p or purpose
                linked = True
                break
        if not linked:
            for tx_id, tx_data in visitor_data.get('transactions', {}).items():
                if tx_data.get('employee_name') == employee_name:
                    linked = True
                    break
        if linked:
            seen.add(visitor_id)
            results.append({
                'visitor_id': visitor_id,
                'visitor_name': visitor_name,
                'purpose': purpose,
                'status': status,
                'contact': basic_info.get('contact', '—')
            })
    return results, employee_name


@app.route('/employee/visitors/<emp_id>')
def employee_visitors_view(emp_id):
    """Show visitors associated with this employee (eye icon from /employees)."""
    if USE_MOCK_DATA:
        all_employees = get_mock_employees()
        all_visitors = get_mock_visitors()
    else:
        all_employees = (db.reference('employees').get() or {})
        all_visitors = (db.reference('visitors').get() or {})
    visitors_list, employee_name = _visitors_for_employee(emp_id, all_employees, all_visitors)
    EMP_VISITORS_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Visitors for {{ employee_name }}</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    </head>
    <body class="min-h-screen bg-gray-50 p-6">
        <div class="max-w-4xl mx-auto">
            <a href="{{ url_for('employees_list') }}" class="text-gray-500 hover:text-gray-700 text-sm inline-flex items-center mb-4">
                <i class="fas fa-arrow-left mr-1"></i>Back to Employees
            </a>
            <h1 class="text-2xl font-bold text-gray-900 mb-2">Visitors for {{ employee_name }}</h1>
            <p class="text-gray-600 mb-6">Visitors linked to this employee (by visit or transaction).</p>
            {% if visitors_list %}
            <div class="bg-white rounded-xl shadow overflow-hidden">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Visitor</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Purpose</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Contact</th>
                            <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {% for v in visitors_list %}
                        <tr class="hover:bg-gray-50">
                            <td class="px-4 py-3 text-sm font-medium text-gray-900">{{ v.visitor_name }}</td>
                            <td class="px-4 py-3 text-sm text-gray-600">{{ v.purpose }}</td>
                            <td class="px-4 py-3"><span class="px-2 py-1 text-xs font-medium rounded bg-blue-100 text-blue-800">{{ v.status }}</span></td>
                            <td class="px-4 py-3 text-sm text-gray-600">{{ v.contact }}</td>
                            <td class="px-4 py-3"><a href="/visitor/{{ v.visitor_id }}" class="text-blue-600 hover:underline text-sm">View</a></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <div class="bg-white rounded-xl shadow p-8 text-center text-gray-500">
                <i class="fas fa-users text-4xl text-gray-300 mb-3"></i>
                <p>No visitors linked to this employee yet.</p>
            </div>
            {% endif %}
        </div>
    </body>
    </html>
    """
    return render_template_string(EMP_VISITORS_HTML, visitors_list=visitors_list, employee_name=employee_name or 'Unknown')


@app.route('/get_employee/<emp_id>')
def get_employee(emp_id):
    if USE_MOCK_DATA:
        all_employees = get_mock_employees()
        emp_data = all_employees.get(emp_id)
        if not emp_data:
            return jsonify({"error": "Employee not found"}), 404
        # Map mock fields to form fields (role <-> position, contact <-> phone)
        return jsonify({
            'name': emp_data.get('name', ''),
            'email': emp_data.get('email', ''),
            'department': emp_data.get('department', ''),
            'role': emp_data.get('position', emp_data.get('role', '')),
            'contact': emp_data.get('phone', emp_data.get('contact', ''))
        })
    emp_data = db.reference(f'employees/{emp_id}').get()
    if not emp_data:
        return jsonify({"error": "Employee not found"}), 404
    # Normalize to form fields (role/contact) so edit modal works like mock branch
    return jsonify({
        'name': emp_data.get('name', ''),
        'email': emp_data.get('email', ''),
        'department': emp_data.get('department', ''),
        'role': emp_data.get('role', emp_data.get('position', '')),
        'contact': emp_data.get('contact', emp_data.get('phone', ''))
    })

@app.route('/add_employee', methods=['POST'])
def add_employee():
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({"success": False, "message": "Invalid JSON body"}), 400
    if not (data.get('name') or '').strip():
        return jsonify({"success": False, "message": "Employee name is required"}), 400
    emp_id = str(uuid.uuid4())
    if not USE_MOCK_DATA and FIREBASE_AVAILABLE:
        db.reference(f'employees/{emp_id}').set(data)
    return jsonify({"success": True, "emp_id": emp_id})

@app.route('/edit_employee/<emp_id>', methods=['POST'])
def edit_employee(emp_id):
    emp_id = str(emp_id or '').strip()
    if not emp_id:
        return jsonify({"success": False, "message": "Invalid employee id"}), 400
    data = request.get_json()
    if not data or not isinstance(data, dict):
        return jsonify({"success": False, "message": "Invalid JSON body"}), 400
    if not USE_MOCK_DATA and FIREBASE_AVAILABLE:
        existing = db.reference(f'employees/{emp_id}').get()
        if not existing:
            return jsonify({"success": False, "message": "Employee not found"}), 404
        db.reference(f'employees/{emp_id}').update(data)
    return jsonify({"success": True})

@app.route('/delete_employee/<emp_id>', methods=['POST'])
def delete_employee(emp_id):
    emp_id = str(emp_id or '').strip()
    if not emp_id:
        return jsonify({"success": False, "message": "Invalid employee id"}), 400
    if not USE_MOCK_DATA and FIREBASE_AVAILABLE:
        db.reference(f'employees/{emp_id}').delete()
    return jsonify({"success": True})

# --------------------------
# Mock Data Toggle API
# --------------------------

@app.route('/api/mock_data', methods=['GET'])
def api_mock_data_status():
    """Return current mock-data state and whether Firebase is available."""
    return jsonify({
        'mock': USE_MOCK_DATA,
        'firebase_available': FIREBASE_AVAILABLE,
        'firebase_initialized': FIREBASE_INITIALIZED,
    })

@app.route('/api/mock_data', methods=['POST'])
def api_mock_data_toggle():
    """Toggle mock data on or off at runtime. Persists to .env so it survives reloader restarts."""
    global USE_MOCK_DATA, _MOCK_VISITORS_BASE, _MOCK_EMPLOYEES_CACHE, _mock_rooms_cache, _MOCK_BLACKLIST_STATE, _ADMIN_MOCK_SEED

    body = request.get_json() or {}
    enable = body.get('mock')
    if enable is None:
        enable = not USE_MOCK_DATA
    else:
        enable = bool(enable)

    if not enable and not FIREBASE_INITIALIZED:
        return jsonify({
            'success': False,
            'mock': USE_MOCK_DATA,
            'message': 'Cannot disable mock data — Firebase is not initialized on this server.',
        }), 400

    USE_MOCK_DATA = enable

    # Persist to .env so the setting survives Flask debug-reloader restarts.
    try:
        env_path = _admin_env_path
        lines = []
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
        found = False
        new_val = 'true' if enable else 'false'
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('USE_MOCK_DATA=') or stripped.startswith('USE_MOCK_DATA ='):
                lines[i] = f'USE_MOCK_DATA={new_val}\n'
                found = True
                break
        if not found:
            lines.append(f'USE_MOCK_DATA={new_val}\n')
        with open(env_path, 'w') as f:
            f.writelines(lines)
    except Exception as e:
        print(f"[!] Could not persist USE_MOCK_DATA to .env: {e}")

    if enable:
        _MOCK_VISITORS_BASE = None
        _MOCK_EMPLOYEES_CACHE = None
        _mock_rooms_cache = None
        _MOCK_BLACKLIST_STATE = {}
        _ADMIN_MOCK_SEED = None
        print("[*] Mock data ENABLED (caches reset — fresh data will be generated)")
    else:
        print("[*] Mock data DISABLED — now serving live Firebase data")

    return jsonify({
        'success': True,
        'mock': USE_MOCK_DATA,
        'message': f'Data source switched to {"MOCK" if USE_MOCK_DATA else "Firebase (live)"}',
    })


if __name__ == "__main__":
    print("\n" + "="*50)
    print("Starting Admin Dashboard...")
    print("="*50)
    print("Dashboard URL: http://localhost:5000")
    if USE_MOCK_DATA:
        print("Data source: MOCK (generated visitors — not Firebase)")
    else:
        print("Data source: Firebase (live)")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)