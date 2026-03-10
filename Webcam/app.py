import os
import cv2
import base64
import numpy as np
import joblib 
from flask import Flask, render_template, request, jsonify, url_for
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime, timedelta
from time import time
import onnxruntime as ort
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, url_for, session, redirect
import logging
import smtplib
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- Dlib and Environment Setup ---
try:
    import dlib
except ImportError:
    dlib = None
    print("[!] CRITICAL: Dlib not installed. Face recognition disabled.")

# QR Module
from qr_module import (
    create_qr_for_visit,
    generate_qr_payload,
    parse_qr_payload, validate_qr_token, update_qr_state, invalidate_qr,
    log_qr_scan, log_security_alert, find_all_face_matches, detect_twin,
    get_qr_state,
    QR_UNUSED, QR_CHECKIN_USED, QR_CHECKOUT_USED, QR_ASSUMED_SCANNED, QR_INVALIDATED,
)

# Load environment variables (from Webcam dir and project root)
_script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_script_dir, ".env"))
load_dotenv()  # Also load from cwd

# --- Configuration ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "gate_app_secret_key_123") 
VERIFICATION_THRESHOLD = float(os.environ.get("VERIFICATION_THRESHOLD", "0.82"))  # 0.82 lenient; 0.78 stricter. Lower distance = better match.
CHECKIN_COOLDOWN_SECONDS = int(os.environ.get("CHECKIN_COOLDOWN_SECONDS", "90"))  # Min seconds between check-in and checkout (prevents accidental double-scan)
COMPANY_IP = os.environ.get("COMPANY_IP")

# Protocol mode: hybrid (default), face_only, qr_only (for research comparison)
_AUTH_MODE_RAW = os.environ.get("AUTH_MODE", "hybrid").strip().lower()
if _AUTH_MODE_RAW not in ("hybrid", "face_only", "qr_only"):
    _AUTH_MODE_RAW = "hybrid"
AUTH_MODE = _AUTH_MODE_RAW

# --- SMTP Config ---
SMTP_SERVER = os.environ.get("SMTP_SERVER")
SMTP_PORT = os.environ.get("SMTP_PORT")
EMAIL_ADDRESS = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASS")

# --- Data source mode ---
USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "False").lower() == "true"

# --- Firebase client config (for frontend templates, e.g. dashboard) ---
FIREBASE_CLIENT_CONFIG = {
    "apiKey": os.environ.get("FIREBASE_API_KEY", "AIzaSyDQ1xKacawkZKz9n12PPJCwhUPIKuHmGqU"),
    "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", "visitor-management-8f5b4.firebaseapp.com"),
    "databaseURL": os.environ.get("FIREBASE_DATABASE_URL", "https://visitor-management-8f5b4-default-rtdb.firebaseio.com").rstrip("/"),
    "projectId": os.environ.get("FIREBASE_PROJECT_ID", "visitor-management-8f5b4"),
    "storageBucket": os.environ.get("FIREBASE_STORAGE_BUCKET", "visitor-management-8f5b4.firebasestorage.app"),
    "messagingSenderId": os.environ.get("FIREBASE_MESSAGING_SENDER_ID", "160208135498"),
    "appId": os.environ.get("FIREBASE_APP_ID", "1:160208135498:web:e4e780440fce692b948db3"),
    "measurementId": os.environ.get("FIREBASE_MEASUREMENT_ID", "G-FDL9LX0BDG"),
}

# Logger and db reference
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class InMemoryDBRef:
    """Small Firebase-like reference wrapper for local no-cloud demos."""
    def __init__(self, root_data, path=()):
        self._root = root_data
        self._path = tuple(path)

    def child(self, path):
        parts = [p for p in str(path).split("/") if p]
        return InMemoryDBRef(self._root, self._path + tuple(parts))

    def _resolve(self, create=False):
        node = self._root
        for key in self._path:
            if key not in node:
                if not create:
                    return None
                node[key] = {}
            if not isinstance(node[key], dict):
                if create:
                    node[key] = {}
                else:
                    return None
            node = node[key]
        return node

    def get(self):
        if not self._path:
            return self._root
        node = self._root
        for key in self._path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    def set(self, value):
        if not self._path:
            if isinstance(value, dict):
                self._root.clear()
                self._root.update(value)
            return
        parent = self._root
        for key in self._path[:-1]:
            parent = parent.setdefault(key, {})
        parent[self._path[-1]] = value

    def update(self, updates):
        node = self._resolve(create=True)
        if not isinstance(node, dict):
            self.set(dict(updates))
            return
        node.update(updates)

    def push(self):
        key = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f") + "_" + uuid.uuid4().hex[:6]
        node = self._resolve(create=True)
        if not isinstance(node, dict):
            self.set({})
            node = self._resolve(create=True)
        node[key] = {}
        return self.child(key)


def _mock_embedding(seed):
    rng = np.random.default_rng(seed)
    vec = rng.normal(0, 1, 128)
    vec = vec / np.linalg.norm(vec)
    return " ".join(f"{v:.6f}" for v in vec.tolist())


# Fixed token for demo QR so the same QR works every run (show at /demo-qr).
DEMO_QR_VISITOR_ID = "visitor_demo_1"
DEMO_QR_VISIT_ID = "visit_demo_1"
DEMO_QR_FIXED_TOKEN = "demo_fixed_qr_token_32bytes_url_safe_xxxx"


def build_mock_gate_data():
    today = datetime.now().strftime("%Y-%m-%d")
    mock_visitors = {}
    demo_people = [
        ("visitor_demo_1", "Aarav Sharma", "aarav.demo@example.com"),
        ("visitor_demo_2", "Diya Mehta", "diya.demo@example.com"),
    ]
    for idx, (visitor_id, name, email) in enumerate(demo_people, start=1):
        visit_id = f"visit_demo_{idx}"
        token = DEMO_QR_FIXED_TOKEN if (visitor_id == DEMO_QR_VISITOR_ID) else None
        token, payload, _image_b64, qr_firebase = create_qr_for_visit(visitor_id, visit_id, today, token=token)
        mock_visitors[visitor_id] = {
            "basic_info": {
                "name": name,
                "contact": email,
                "blacklisted": "no",
                "embedding": _mock_embedding(idx),
            },
            "status": "Registered",
            "visits": {
                visit_id: {
                    "visit_id": visit_id,
                    "purpose": "Demo visit",
                    "employee_name": "Demo Host",
                    "duration": "1 hour",
                    "visit_date": today,
                    "status": "registered",
                    "visit_approved": True,
                    "has_visited": False,
                    "check_in_time": None,
                    "check_out_time": None,
                    **qr_firebase,
                }
            },
            "demo_qr_payload": payload,
            "demo_qr_token": token,
        }
    return {
        "visitors": mock_visitors,
        "research_protocol_events": {},
        "security_alerts": {},
    }


if USE_MOCK_DATA:
    print("[*] Webcam running in USE_MOCK_DATA=True mode (in-memory demo data).")
    db_ref = InMemoryDBRef(build_mock_gate_data())
else:
    if not firebase_admin._apps:
        try:
            # Look for firebase_credentials.json in Webcam, parent, or Admin folder
            _cred_paths = [
                os.path.join(_script_dir, "firebase_credentials.json"),
                os.path.join(os.path.dirname(_script_dir), "firebase_credentials.json"),
                os.path.join(os.path.dirname(_script_dir), "Admin", "firebase_credentials.json"),
                os.path.join(os.path.dirname(_script_dir), "Register_App", "firebase_credentials.json"),
                "firebase_credentials.json",
            ]
            _cred_path = None
            for p in _cred_paths:
                if p and os.path.isfile(p):
                    _cred_path = p
                    break
            if not _cred_path:
                raise FileNotFoundError("firebase_credentials.json not found in Webcam, parent, Admin, or Register_App")
            cred = credentials.Certificate(_cred_path)
            database_url = os.environ.get("FIREBASE_DATABASE_URL", "https://visitor-management-8f5b4-default-rtdb.firebaseio.com").rstrip("/") + "/"
            firebase_admin.initialize_app(cred, {"databaseURL": database_url})
            print("[OK] Firebase initialized successfully.")
            db_ref = db.reference()
        except Exception as e:
            print(f"[!] Firebase unavailable ({e}). Using mock data.")
            USE_MOCK_DATA = True
            db_ref = InMemoryDBRef(build_mock_gate_data())
    else:
        db_ref = db.reference()


def db_reference(path=None):
    if USE_MOCK_DATA:
        return db_ref.child(path) if path else db_ref
    return db.reference(path) if path else db.reference()


def log_protocol_event(event_type, auth_mode, visitor_id=None, visit_id=None, **extra):
    """Log protocol events for research/metrics export (arrival, departure, invalidation)."""
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        key = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        entry = {
            "event": event_type,
            "auth_mode": auth_mode,
            "protocol_config": AUTH_MODE,
            "timestamp": now_str,
        }
        if visitor_id is not None:
            entry["visitor_id"] = str(visitor_id)
        if visit_id is not None:
            entry["visit_id"] = str(visit_id)
        entry.update(extra)
        db_ref.child("research_protocol_events").child(key).set(entry)
        return True
    except Exception as exc:
        logger.error(f"Error logging protocol event: {exc}")
        return False


# --- Helper Functions ---

def l2_distance(vec1, vec2):
    """Calculates the Euclidean distance between two face embeddings."""
    if vec1.shape != vec2.shape:
        if vec1.ndim > vec2.ndim:
            vec2 = vec2.reshape(vec1.shape)
        elif vec2.ndim > vec1.ndim:
            vec1 = vec1.reshape(vec2.shape)
    return np.linalg.norm(vec1 - vec2)

# --- YuNet + Dlib + OpenCV Haar (aligned with Register_App pipeline) ---
_script_dir = os.path.dirname(os.path.abspath(__file__))
detector = predictor = face_recognizer = _cv_face_cascade = _cv_face_alt2 = _yunet_detector = None
_yunet_model_path = None
if dlib:
    try:
        _shape_path = os.path.join(_script_dir, "shape_predictor_68_face_landmarks.dat")
        _face_model_path = os.path.join(_script_dir, "dlib_face_recognition_resnet_model_v1.dat")
        detector = dlib.get_frontal_face_detector()
        predictor = dlib.shape_predictor(_shape_path)
        face_recognizer = dlib.face_recognition_model_v1(_face_model_path)
        _cv_face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        try:
            _cv_face_alt2 = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
        except Exception:
            _cv_face_alt2 = None
        _yunet_model_path = os.path.join(_script_dir, "face_detection_yunet_2023mar.onnx")
        if hasattr(cv2, "FaceDetectorYN") and os.path.isfile(_yunet_model_path):
            try:
                _yunet_detector = cv2.FaceDetectorYN.create(_yunet_model_path, "", (320, 320))
                print("[OK] YuNet + Dlib + Haar loaded (same pipeline as Register_App)")
            except Exception as e:
                print(f"[!] YuNet init failed, using dlib+Haar only: {e}")
                _yunet_detector = None
        else:
            if not hasattr(cv2, "FaceDetectorYN"):
                print("[OK] Dlib + Haar loaded (FaceDetectorYN not available)")
            elif not os.path.isfile(_yunet_model_path):
                print(f"[OK] Dlib + Haar loaded (YuNet model not found at {_yunet_model_path})")
            else:
                print("[OK] Dlib + Haar loaded")
    except Exception as e:
        print(f"[!] WARNING: Could not load Dlib models: {e}. Check file paths.")

def _embed_from_bbox(rgb_img, x, y, w, h):
    """Compute dlib 128D embedding from a face bounding box (e.g. from YuNet)."""
    if not predictor or not face_recognizer:
        return None
    try:
        dlib_rect = dlib.rectangle(int(x), int(y), int(x + w), int(y + h))
        shape = predictor(rgb_img, dlib_rect)
        emb = face_recognizer.compute_face_descriptor(rgb_img, shape)
        return np.array(emb)
    except Exception:
        return None

def _to_dlib_format(img, rgb=True):
    """Ensure image is uint8 contiguous for dlib (8-bit gray or RGB). Fixes NumPy 2.0 / dlib compatibility."""
    if img is None:
        return None
    try:
        out = np.ascontiguousarray(img.astype(np.uint8))
        if out.ndim == 3 and rgb and out.shape[2] >= 3:
            out = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
            out = np.ascontiguousarray(out)
        return out
    except Exception:
        return None

def _get_face_embedding_at_scale(cv2_img, min_side):
    """Run full detection pipeline at one scale. min_side=0 means no resize. Aligned with Register_App."""
    if cv2_img is None or cv2_img.size == 0:
        return None
    cv2_img = np.ascontiguousarray(cv2_img.astype(np.uint8))
    bgr_img = cv2_img
    rgb_img = _to_dlib_format(cv2_img, rgb=True)
    gray_img = np.ascontiguousarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY).astype(np.uint8))
    h, w = rgb_img.shape[:2]
    if min_side > 0 and min(h, w) < min_side:
        scale = min_side / min(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        bgr_img = cv2.resize(bgr_img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        rgb_img = cv2.resize(rgb_img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        gray_img = cv2.resize(gray_img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    bgr_img = np.ascontiguousarray(bgr_img)
    rgb_img = np.ascontiguousarray(rgb_img)
    gray_img = np.ascontiguousarray(gray_img)
    h, w = rgb_img.shape[:2]

    # Try Haar first (often more forgiving for frontal faces in varied lighting) - same as Register_App
    for cascade in (_cv_face_cascade, _cv_face_alt2):
        if cascade is None:
            continue
        for (sf, mn, ms) in [(1.25, 2, (15, 15)), (1.2, 2, (20, 20)), (1.15, 3, (15, 15)), (1.1, 2, (25, 25))]:
            rects = cascade.detectMultiScale(gray_img, scaleFactor=sf, minNeighbors=mn, minSize=ms)
            if len(rects) > 0:
                x, y, rw, rh = max(rects, key=lambda r: r[2] * r[3])
                out = _embed_from_bbox(rgb_img, x, y, rw, rh)
                if out is not None:
                    return out

    if _yunet_detector is not None:
        _yunet_detector.setInputSize((w, h))
        _, dets = _yunet_detector.detect(bgr_img)
        if dets is not None and dets.shape[0] >= 1:
            x, y, rw, rh = dets[0, 0], dets[0, 1], dets[0, 2], dets[0, 3]
            if rw > 0 and rh > 0:
                out = _embed_from_bbox(rgb_img, x, y, rw, rh)
                if out is not None:
                    return out
        bgr_f = cv2.flip(bgr_img, 1)
        rgb_f = cv2.flip(rgb_img, 1)
        _yunet_detector.setInputSize((w, h))
        _, dets = _yunet_detector.detect(bgr_f)
        if dets is not None and dets.shape[0] >= 1:
            x, y, rw, rh = dets[0, 0], dets[0, 1], dets[0, 2], dets[0, 3]
            if rw > 0 and rh > 0:
                out = _embed_from_bbox(rgb_f, x, y, rw, rh)
                if out is not None:
                    return out

    def try_detect(rgb, gray):
        for img in (gray, rgb):
            for upsample in (0, 1, 2, 3, 4):
                faces = detector(img, upsample)
                if len(faces) > 0:
                    face = faces[0]
                    shape = predictor(rgb, face)
                    emb = face_recognizer.compute_face_descriptor(rgb, shape)
                    return np.array(emb)
        for cascade in (_cv_face_cascade, _cv_face_alt2):
            if cascade is None:
                continue
            for (sf, mn, ms) in [
                (1.3, 2, (10, 10)), (1.2, 3, (15, 15)), (1.15, 4, (20, 20)),
                (1.1, 5, (30, 30)), (1.05, 3, (20, 20)), (1.1, 2, (25, 25)),
            ]:
                rects = cascade.detectMultiScale(gray, scaleFactor=sf, minNeighbors=mn, minSize=ms)
                if len(rects) > 0:
                    x, y, rw, rh = max(rects, key=lambda r: r[2] * r[3])
                    dlib_rect = dlib.rectangle(int(x), int(y), int(x + rw), int(y + rh))
                    shape = predictor(rgb, dlib_rect)
                    emb = face_recognizer.compute_face_descriptor(rgb, shape)
                    return np.array(emb)
        return None

    out = try_detect(rgb_img, gray_img)
    if out is not None:
        return out
    rgb_f = cv2.flip(rgb_img, 1)
    gray_f = cv2.flip(gray_img, 1)
    return try_detect(rgb_f, gray_f)

def get_face_embedding(cv2_img):
    """Same pipeline as Register_App: multi-scale, YuNet + dlib + Haar, histogram eq, mirrored."""
    if not predictor or not face_recognizer or cv2_img is None or cv2_img.size == 0:
        return None
    try:
        h, w = cv2_img.shape[:2]
        max_side = max(h, w)
        images_to_try = [cv2_img]
        # Downscale for large images (detectors often work better at 480–640px)
        if max_side > 640:
            scale = 640.0 / max_side
            small = cv2.resize(cv2_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
            images_to_try.append(small)
        if max_side > 480:
            scale = 480.0 / max_side
            small = cv2.resize(cv2_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
            images_to_try.append(small)
        # Upscale for small images (face may be too small to detect)
        if max_side < 400:
            scale = 480.0 / max_side
            large = cv2.resize(cv2_img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)
            images_to_try.append(large)
        # Histogram equalization can help in poor lighting
        gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
        gray_eq = cv2.equalizeHist(gray)
        gray_eq_bgr = cv2.cvtColor(gray_eq, cv2.COLOR_GRAY2BGR)
        images_to_try.append(gray_eq_bgr)
        # Mirrored image (webcam often shows mirrored view; capture might differ)
        images_to_try.append(cv2.flip(cv2_img, 1))

        for img in images_to_try:
            for min_side in (0, 256, 320, 400, 512, 200):
                out = _get_face_embedding_at_scale(img, min_side)
                if out is not None:
                    return out
        return None
    except Exception as e:
        logger.error("Dlib embedding error: %s", e)
        return None

def verify_by_distance(live_embedding):
    """
    Compares a live embedding against ALL stored embeddings in Firebase.
    """
    visitors_ref = db_reference("visitors")
    all_visitors = visitors_ref.get()
    if not all_visitors:
        return None, 999.0

    min_distance = float('inf')
    matched_id = None

    for visitor_id, data in all_visitors.items():
        # Get embedding from basic_info section
        basic_info = data.get("basic_info", {})
        emb_raw = basic_info.get('embedding')
        if not emb_raw:
            continue

        try:
            # Convert space-separated string to numpy array (np.fromstring is deprecated)
            stored_embedding = np.array([float(x) for x in str(emb_raw).strip().split()])
            if stored_embedding.size != 128:
                continue

            # Compute Euclidean distance (both as 1D vectors)
            distance = l2_distance(np.asarray(live_embedding).flatten(), stored_embedding)

            # Keep track of the closest match
            if distance < min_distance:
                min_distance = distance
                matched_id = visitor_id

        except Exception as e:
            print(f"[!] Warning: skipping embedding for {visitor_id} due to error: {e}")
            continue

    # Return matched visitor ID only if distance is below threshold
    if matched_id is not None and min_distance <= VERIFICATION_THRESHOLD:
        return matched_id, min_distance
    return None, min_distance

# --- Email Functions ---

def send_feedback_email(visitor_email, visitor_name, feedback_link):
    """Send feedback request email to visitor after check-out"""
    logger.info(f"Attempting to send feedback email to: {visitor_email}")
    
    if not all([SMTP_SERVER, SMTP_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
        error_msg = "Email environment variables missing. Skipping feedback email."
        logger.error(error_msg)
        return False, error_msg

    try:
        msg = MIMEMultipart("alternative")
        msg['Subject'] = "Share Your Feedback - Visitor Experience"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = visitor_email

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; background-color:#f8f9fa; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 12px; padding: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <h2 style="color: #3f37c9; text-align: center;">Share Your Feedback</h2>
                <p>Hello <strong>{visitor_name}</strong>,</p>
                <p>Thank you for visiting us! We hope you had a great experience.</p>
                <p>Your feedback is valuable to us and helps us improve our services. Please take a moment to share your experience:</p>

                <div style="text-align: center; margin: 25px 0;">
                    <a href="{feedback_link}" 
                       style="background-color: #3f37c9; color: white; padding: 14px 30px; 
                              text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold;">
                        📝 Share Feedback
                    </a>
                </div>

                <p style="font-size: 13px; color: #777; text-align: center;">
                    This feedback will help us enhance our workplace intelligence platform and services.
                </p>
                
                <p style="font-size: 13px; color: #777; text-align: center;">
                    Thank you for your time!
                </p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, visitor_email, msg.as_string())
        server.quit()

        logger.info(f"✅ Feedback email successfully sent to {visitor_email}")
        return True, "Feedback email sent successfully"

    except smtplib.SMTPAuthenticationError:
        error_msg = "SMTP Authentication Error: Check EMAIL_USER and EMAIL_PASS."
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"General Email error during feedback email send: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def send_exceeded_email(visitor_email, visitor_name):
    """Send notification email when visitor exceeds duration limit"""
    if not visitor_email or visitor_email == 'N/A':
        return False, "No email address provided"
        
    try:
        msg = MIMEMultipart("alternative")
        msg['Subject'] = "Visit Duration Exceeded - Action Required"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = visitor_email

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; background-color:#f8f9fa; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 12px; padding: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <h2 style="color: #dc3545; text-align: center;">Visit Duration Exceeded</h2>
                <p>Hello <strong>{visitor_name}</strong>,</p>
                <p>Your scheduled visit duration has been exceeded. Please proceed to check-out immediately at the kiosk.</p>
                
                <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; padding: 15px; margin: 20px 0;">
                    <p style="color: #856404; margin: 0;">
                        <strong>Important:</strong> Please check out as soon as possible to avoid any issues.
                    </p>
                </div>

                <p style="font-size: 13px; color: #777; text-align: center;">
                    If you need to extend your visit, please contact security personnel.
                </p>
                
                <p style="font-size: 13px; color: #777; text-align: center;">
                    Thank you for your cooperation!
                </p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, visitor_email, msg.as_string())
        server.quit()

        logger.info(f"✅ Exceeded duration email sent to {visitor_email}")
        return True, "Exceeded duration email sent successfully"

    except Exception as e:
        error_msg = f"Error sending exceeded duration email: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def simulate_send_email(recipient_email, subject, body):
    """Simulates sending an email and prints the email content to the console."""
    if recipient_email == 'N/A' or not recipient_email:
        print(f"📧 SKIPPED EMAIL: No email address provided for notification.")
        return
        
    print("--------------------------------------------------")
    print(f"📧 SIMULATED EMAIL SENT TO: {recipient_email}")
    print(f"SUBJECT: {subject}")
    print(f"BODY:\n{body}")
    print("--------------------------------------------------")

def check_for_expiring_visits():
    """Checks for visitors about to expire (30 minutes remaining) and simulates sending email."""
    visitors_ref = db_reference("visitors")
    all_visitors = visitors_ref.get()
    if not all_visitors: return "No visitors found."

    now = datetime.now()
    notification_count = 0
    
    for visitor_id, data in all_visitors.items():
        if data.get('status') == 'Checked-In' and 'expected_checkout_time' in data:
            try:
                expected_checkout = datetime.strptime(data['expected_checkout_time'], "%Y-%m-%d %H:%M:%S")
                time_remaining = expected_checkout - now
                
                # Notification window: between 0 and 30 minutes remaining
                if timedelta(minutes=0) < time_remaining <= timedelta(minutes=30):
                    if data.get('notified') != True:
                        remaining_minutes = int(time_remaining.total_seconds() / 60)
                        
                        # Get email from basic_info
                        basic_info = data.get("basic_info", {})
                        visitor_email = basic_info.get("contact")
                        
                        email_body = (
                            f"Dear {basic_info.get('name', 'Visitor')},\n\nYour scheduled visit "
                            f"is due to expire in approximately {remaining_minutes} minutes. Please check out at the Kiosk."
                        )
                        simulate_send_email(visitor_email, "Visit Duration Expiring Soon", email_body)
                        
                        visitors_ref.child(visitor_id).update({'notified': True})
                        notification_count += 1

            except Exception as e:
                print(f"Error processing notification for {data.get('name')}: {e}")

    return f"Processed notifications. {notification_count} emails simulated."

# --- Routes ---

@app.route("/")
@app.route("/checkin_gate")
def checkin_gate():
    """Step 1: Choose action and scan QR code."""
    return render_template("gate_qr.html")


@app.route("/checkin_gate/face")
def checkin_gate_face():
    """Step 2: Face verification (QR must be scanned first)."""
    return render_template("gate_face.html")


@app.route("/debug_last_frame")
def debug_last_frame():
    """Serve the last frame that had no face detected (for debugging)."""
    debug_path = os.path.join(os.path.dirname(__file__), "debug_frames", "last_no_face.jpg")
    if not os.path.isfile(debug_path):
        return "<p>No debug frame saved yet. Use the gate and trigger 'No face detected' once.</p>", 404
    from flask import send_file
    return send_file(debug_path, mimetype="image/jpeg")


@app.route("/api/check_face", methods=["POST"])
def api_check_face():
    """Lightweight face detection for live UI feedback (like Register_App). Returns {face_detected: bool}."""
    try:
        data = request.get_json()
        if not data or "image" not in data:
            return jsonify({"face_detected": False, "error": "No image"}), 400
        try:
            captured_base64 = data["image"].split(",")[1]
        except Exception:
            return jsonify({"face_detected": False, "error": "Invalid image"}), 400
        np_img = np.frombuffer(base64.b64decode(captured_base64), np.uint8)
        cv2_img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        if cv2_img is None:
            return jsonify({"face_detected": False, "error": "Unable to decode image"}), 400
        emb = get_face_embedding(cv2_img)
        return jsonify({
            "face_detected": emb is not None and len(emb) == 128,
            "hint": "Position your face inside the oval, ensure good lighting." if emb is None else None,
        })
    except Exception as e:
        logger.exception("check_face error")
        return jsonify({"face_detected": False, "error": str(e)}), 500


@app.route("/debug_gate")
def debug_gate():
    """Diagnostic endpoint: shows gate config, visitor count, and embedding status."""
    try:
        all_visitors = db_reference("visitors").get() or {}
        total = len(all_visitors)
        with_embedding = 0
        sample_names = []
        for vid, data in all_visitors.items():
            basic = data.get("basic_info", {})
            emb = basic.get("embedding")
            if emb and len(str(emb).strip().split()) == 128:
                with_embedding += 1
            if len(sample_names) < 5:
                sample_names.append(basic.get("name", "?"))

        return jsonify({
            "status": "ok",
            "use_mock_data": USE_MOCK_DATA,
            "auth_mode": AUTH_MODE,
            "verification_threshold": VERIFICATION_THRESHOLD,
            "dlib_loaded": dlib is not None,
            "visitor_count": total,
            "visitors_with_embedding": with_embedding,
            "sample_names": sample_names,
            "hint": "If visitors_with_embedding is 0, face recognition cannot work. Register with camera to capture face." if with_embedding == 0 and total > 0 else None,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/dashboard")
def dashboard():
    """Visitor dashboard using Firebase Realtime Database (config from env)."""
    return render_template("dashboard.html", firebase_config=FIREBASE_CLIENT_CONFIG)


@app.route("/demo-qr")
def demo_qr():
    """Show a mock QR code that works with the webcam gate (same payload as visitor_demo_1)."""
    today = datetime.now().strftime("%Y-%m-%d")
    qr_payload = generate_qr_payload(DEMO_QR_VISITOR_ID, DEMO_QR_VISIT_ID, today, DEMO_QR_FIXED_TOKEN)
    return render_template("demo_qr.html", qr_payload=qr_payload)


@app.route("/mock_demo_data")
def mock_demo_data():
    """Return mock visitor+QR payloads for no-camera local testing."""
    if not USE_MOCK_DATA:
        return jsonify({"status": "error", "message": "Enable USE_MOCK_DATA=True to access demo data."}), 400

    visitors = db_ref.child("visitors").get() or {}
    demo_records = []
    for visitor_id, visitor_data in visitors.items():
        basic = visitor_data.get("basic_info", {})
        visits = visitor_data.get("visits", {})
        if not visits:
            continue
        latest_visit_id = max(visits.keys())
        latest_visit = visits.get(latest_visit_id, {})
        demo_records.append({
            "visitor_id": visitor_id,
            "mock_face_id": visitor_id,
            "name": basic.get("name", "Visitor"),
            "visit_id": latest_visit_id,
            "visit_status": latest_visit.get("status", "registered"),
            "qr_payload": latest_visit.get("qr_payload"),
            "qr_state": (latest_visit.get("qr_state") or {}).get("status", "UNUSED"),
        })

    return jsonify({
        "status": "success",
        "auth_mode": AUTH_MODE,
        "use_mock_data": USE_MOCK_DATA,
        "records": demo_records,
        "usage": {
            "endpoint": "/mock_auth",
            "payload_example": {
                "mock_face_id": "visitor_demo_1",
                "qr_data": "{...optional qr payload...}"
            }
        }
    })


@app.route("/mock_auth", methods=["POST"])
def mock_auth():
    """No-camera auth endpoint for demoing QR + face logic with mock identities."""
    if not USE_MOCK_DATA:
        return jsonify({"status": "error", "message": "Enable USE_MOCK_DATA=True to use mock_auth."}), 400

    data = request.get_json() or {}
    mock_face_id = str(data.get("mock_face_id", "")).strip()
    raw_qr = data.get("qr_data")

    if not mock_face_id:
        return jsonify({"status": "denied", "message": "mock_face_id is required.", "distance": 999.0}), 400

    client_ip = request.remote_addr
    if COMPANY_IP and client_ip not in [COMPANY_IP, "127.0.0.1", "::1"]:
        return jsonify({"status": "denied", "message": "Access denied: Unauthorized IP.", "distance": 999.0}), 403

    all_visitors = db_ref.child("visitors").get() or {}
    visitor_data = all_visitors.get(mock_face_id)
    if not visitor_data:
        return jsonify({"status": "denied", "message": f"Unknown mock_face_id: {mock_face_id}", "distance": 999.0}), 404

    qr_valid = False
    qr_visitor_id = None
    qr_visit_id = None
    qr_error_msg = None
    if raw_qr:
        qr_parsed, parse_err = parse_qr_payload(raw_qr)
        if qr_parsed:
            qr_valid, qr_visitor_id, qr_visit_id, _visit_data, qr_error_msg = validate_qr_token(qr_parsed, db_ref)
        else:
            qr_error_msg = parse_err
        if not qr_valid:
            return jsonify({
                "status": "denied",
                "message": f"QR invalid: {qr_error_msg or 'unknown error'}",
                "distance": 999.0
            })

    if AUTH_MODE == "qr_only" and not qr_valid:
        return jsonify({"status": "denied", "message": "qr_only mode requires a valid qr_data payload.", "distance": 999.0})

    if qr_valid and qr_visitor_id != mock_face_id and AUTH_MODE != "qr_only":
        log_security_alert("QR_FACE_MISMATCH", db_ref,
                           qr_visitor_id=qr_visitor_id,
                           face_visitor_id=mock_face_id,
                           qr_visit_id=qr_visit_id,
                           face_distance=0.21,
                           ip=client_ip,
                           message="Mock auth detected mismatch between mock_face_id and QR.")
        log_qr_scan(qr_visitor_id, qr_visit_id, "rejected", db_ref,
                    reason="mock_face_mismatch", face_visitor_id=mock_face_id, ip=client_ip)
        invalidate_qr(qr_visitor_id, qr_visit_id, "Mock mismatch detected", db_ref)
        return jsonify({"status": "denied", "message": "Security alert: mock face does not match QR owner.", "distance": 0.21})

    basic_info = visitor_data.get("basic_info", {})
    visitor_name = basic_info.get("name", "Visitor")
    visitor_email = basic_info.get("contact")
    blacklisted = str(basic_info.get("blacklisted", "no")).lower()
    if blacklisted in ["yes", "true", "1"]:
        return jsonify({"status": "denied", "message": f"Access denied. {visitor_name} is blacklisted.", "distance": 0.21})

    visits = visitor_data.get("visits", {})
    if not visits:
        return jsonify({"status": "denied", "message": "No visits found for this visitor.", "distance": 0.21})

    if qr_valid:
        visit_id = qr_visit_id
        target_visit = visits.get(visit_id) or {}
    else:
        visit_id = max(visits.keys())
        target_visit = visits.get(visit_id) or {}

    visit_status = str(target_visit.get("status", "registered")).lower()
    purpose = target_visit.get("purpose", "")
    employee_name = target_visit.get("employee_name")
    duration = target_visit.get("duration", "1 hour")
    check_in_time = target_visit.get("check_in_time")
    has_visited = target_visit.get("has_visited", False)

    has_qr = bool(qr_valid) if AUTH_MODE != "face_only" else False
    auth_mode = "DUAL_MOCK" if has_qr else "FACE_ONLY_MOCK"

    if visit_status in ["registered", "approved"]:
        return process_checkin(mock_face_id, visit_id, visitor_name, visitor_email,
                               employee_name, purpose, duration, 0.21, client_ip,
                               auth_mode=auth_mode, has_qr=has_qr, auth_mode_config=AUTH_MODE)
    if visit_status == "checked_in":
        if has_visited:
            return jsonify({"status": "denied", "message": "Visit already completed. Register a new visit.", "distance": 0.21})
        if check_in_time:
            try:
                checkin_dt = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S")
                elapsed = (datetime.now() - checkin_dt).total_seconds()
                if elapsed < CHECKIN_COOLDOWN_SECONDS:
                    wait_sec = int(CHECKIN_COOLDOWN_SECONDS - elapsed)
                    return jsonify({"status": "denied", "message": f"You just checked in. Please wait {wait_sec} seconds before checking out.", "distance": 0.21})
            except (ValueError, TypeError):
                pass
        return process_checkout(mock_face_id, visit_id, visitor_name, visitor_email,
                                check_in_time, duration, 0.21, client_ip,
                                purpose, employee_name, auth_mode=auth_mode,
                                has_qr=has_qr, auth_mode_config=AUTH_MODE)
    if visit_status == "checked_out":
        return jsonify({"status": "denied", "message": f"No pending visits for {visitor_name}.", "distance": 0.21})
    if visit_status == "rejected":
        return jsonify({"status": "denied", "message": "This visit has been rejected.", "distance": 0.21})
    if visit_status == "rescheduled":
        return jsonify({"status": "denied", "message": "This visit has been rescheduled.", "distance": 0.21})
    if visit_status in ["pending approval", "pending_approval"]:
        return jsonify({"status": "denied", "message": "This visit is still pending approval. Please wait for your host or reception to approve it.", "distance": 0.21})

    return jsonify({"status": "denied", "message": f"Unsupported visit status: {visit_status}", "distance": 0.21})

@app.route("/checkin_verify_and_log", methods=["POST"])
def checkin_verify_and_log():
    """
    Dual-authentication gate endpoint (QR + Face Recognition).

    Accepts JSON body:
        image    : base64 webcam frame  (required)
        qr_data  : raw QR string        (optional)

    Auth Modes:
        DUAL      – QR + Face match same visitor  (primary)
        FACE_ONLY – face recognition without QR   (fallback — QR assumed scanned)
    """
    try:
        data = request.get_json()
        if not data or "image" not in data:
            return jsonify({"status": "waiting", "message": "No image received.", "distance": 999.0})

        # IP check
        client_ip = request.remote_addr
        if COMPANY_IP and client_ip not in [COMPANY_IP, "127.0.0.1"]:
            return jsonify({"status": "denied", "message": "Access denied: Unauthorized IP.", "distance": 999.0})

        # ──────────────────────────────────────
        # Decode image
        # ──────────────────────────────────────
        try:
            captured_base64 = data["image"].split(",")[1]
        except Exception:
            return jsonify({"status": "waiting", "message": "Invalid image payload.", "distance": 999.0})

        np_img = np.frombuffer(base64.b64decode(captured_base64), np.uint8)
        cv2_img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        if cv2_img is None:
            return jsonify({"status": "waiting", "message": "Unable to decode image.", "distance": 999.0})

        # ──────────────────────────────────────
        # Requested action: checkin | checkout (enforces which flow to allow)
        # ──────────────────────────────────────
        requested_action = (data.get("action") or "").strip().lower() or "auto"

        # ──────────────────────────────────────
        # STEP B: Parse & validate QR (if provided) — before face for qr_only mode
        # ──────────────────────────────────────
        raw_qr = data.get("qr_data")
        qr_valid = False
        qr_visitor_id = None
        qr_visit_id = None
        qr_visit_data = None
        qr_error_msg = None

        if raw_qr:
            qr_parsed, parse_err = parse_qr_payload(raw_qr)
            if qr_parsed:
                qr_valid, qr_visitor_id, qr_visit_id, qr_visit_data, qr_error_msg = \
                    validate_qr_token(qr_parsed, db_ref)
            else:
                qr_error_msg = parse_err

            if not qr_valid and qr_error_msg:
                logger.warning(f"QR validation failed: {qr_error_msg}")

        # ──────────────────────────────────────
        # AUTH_MODE qr_only: authenticate by QR only (no face required)
        # ──────────────────────────────────────
        if AUTH_MODE == "qr_only":
            if not qr_valid:
                return jsonify({
                    "status": "denied",
                    "message": "Please scan your QR code to proceed.",
                    "distance": 999.0
                })
            all_visitors = db_ref.child("visitors").get() or {}
            visitor_data = all_visitors.get(qr_visitor_id)
            if not visitor_data:
                return jsonify({"status": "denied", "message": "Visitor not found.", "distance": 999.0})
            basic_info = visitor_data.get("basic_info", {})
            visitor_name = basic_info.get("name", "Visitor")
            visitor_email = basic_info.get("contact")
            blacklisted = str(basic_info.get("blacklisted", "no")).lower()
            if blacklisted in ["yes", "true", "1"]:
                reason = basic_info.get("blacklist_reason", "Security restriction")
                invalidate_qr(qr_visitor_id, qr_visit_id, "Visitor is blacklisted", db_ref)
                log_protocol_event("invalidation", "QR_ONLY", visitor_id=qr_visitor_id, visit_id=qr_visit_id, reason="blacklisted")
                return jsonify({"status": "denied", "message": f"Access denied. {visitor_name} is blacklisted. Reason: {reason}", "distance": 999.0})
            visits = visitor_data.get("visits", {})
            if not visits:
                return jsonify({"status": "denied", "message": f"No visits found for {visitor_name}. Please register first.", "distance": 999.0})
            target_visit = visits.get(qr_visit_id)
            if not target_visit:
                return jsonify({"status": "denied", "message": "Visit not found.", "distance": 999.0})
            current_date = datetime.now().strftime("%Y-%m-%d")
            visit_date = target_visit.get("visit_date")
            if visit_date and visit_date != current_date:
                return jsonify({"status": "denied", "message": f"Your visit is scheduled for {visit_date}, not today.", "distance": 999.0})
            visit_status = target_visit.get("status", "registered")
            employee_name = target_visit.get("employee_name")
            has_visited = target_visit.get("has_visited", False)
            purpose = target_visit.get("purpose", "")
            check_in_time = target_visit.get("check_in_time")
            duration = target_visit.get("duration", "1 hour")
            rejection_reason = target_visit.get("rejection_reason", "")
            new_visit_date = target_visit.get("new_visit_date", "")

            # Enforce requested action (checkin vs checkout)
            if requested_action == "checkin" and visit_status.lower() in ("checked_in", "checked_out"):
                if visit_status.lower() == "checked_in":
                    return jsonify({"status": "denied", "message": "You are already checked in. Use Check Out instead.", "distance": 999.0})
                return jsonify({"status": "denied", "message": "No visit to check in. Use Check Out instead.", "distance": 999.0})
            if requested_action == "checkout" and visit_status.lower() not in ("checked_in",):
                if visit_status.lower() in ("registered", "approved", "pending approval"):
                    return jsonify({"status": "denied", "message": "Please use Check In first.", "distance": 999.0})
                if visit_status.lower() == "checked_out":
                    return jsonify({"status": "denied", "message": "You are already checked out.", "distance": 999.0})
                if visit_status.lower() in ("rejected", "rescheduled"):
                    return jsonify({"status": "denied", "message": f"Your visit has been {visit_status}.", "distance": 999.0})
                if visit_status.lower() == "exceeded":
                    return jsonify({"status": "denied", "message": "Duration exceeded. Please contact security.", "distance": 999.0})

            if visit_status.lower() == "registered":
                if employee_name and employee_name not in ["N/A", ""]:
                    return jsonify({"status": "denied", "message": f"Meeting pending approval from {employee_name}. Please wait.", "distance": 999.0})
                return process_checkin(qr_visitor_id, qr_visit_id, visitor_name, visitor_email,
                                      employee_name, purpose, duration, 0.0, client_ip,
                                      auth_mode="QR_ONLY", has_qr=True, auth_mode_config=AUTH_MODE)
            elif visit_status.lower() == "approved":
                result = process_checkin(qr_visitor_id, qr_visit_id, visitor_name, visitor_email,
                                        employee_name, purpose, duration, 0.0, client_ip,
                                        auth_mode="QR_ONLY", has_qr=True, auth_mode_config=AUTH_MODE)
                resp = result.get_json()
                if resp and resp.get("status") == "granted" and employee_name and employee_name not in ["N/A", ""]:
                    return jsonify({"status": "granted", "name": visitor_name, "message": f"{employee_name} approved {visitor_name}'s visit. Arrival successful.",
                                    "distance": 0.0, "redirect_url": url_for("checkin_success", name=visitor_name, action="checked in")})
                return result
            elif visit_status.lower() == "rejected":
                msg = "Your visit has been rejected."
                if employee_name and employee_name not in ["N/A", ""]:
                    msg = f"{employee_name} has rejected your visit."
                if rejection_reason:
                    msg += f" Reason: {rejection_reason}"
                return jsonify({"status": "denied", "message": msg, "distance": 999.0})
            elif visit_status.lower() == "rescheduled":
                reschedule_date = new_visit_date or visit_date
                msg = f"Your visit has been rescheduled to {reschedule_date}."
                if employee_name and employee_name not in ["N/A", ""]:
                    msg = f"{employee_name} rescheduled your visit to {reschedule_date}."
                return jsonify({"status": "denied", "message": msg, "distance": 999.0})
            elif visit_status.lower() == "checked_in":
                if has_visited:
                    return jsonify({"status": "denied", "message": "Visit already completed. Please register a new visit.", "distance": 999.0})
                # Enforce minimum time between check-in and checkout
                if check_in_time:
                    try:
                        checkin_dt = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S")
                        elapsed = (datetime.now() - checkin_dt).total_seconds()
                        if elapsed < CHECKIN_COOLDOWN_SECONDS:
                            wait_sec = int(CHECKIN_COOLDOWN_SECONDS - elapsed)
                            return jsonify({"status": "denied", "message": f"You just checked in. Please wait {wait_sec} seconds before checking out.", "distance": 999.0})
                    except (ValueError, TypeError):
                        pass
                return process_checkout(qr_visitor_id, qr_visit_id, visitor_name, visitor_email,
                                       check_in_time, duration, 0.0, client_ip,
                                       purpose, employee_name, auth_mode="QR_ONLY", has_qr=True, auth_mode_config=AUTH_MODE)
            elif visit_status.lower() == "checked_out":
                return jsonify({"status": "denied", "message": f"No pending visits for today, {visitor_name}.", "distance": 999.0})
            elif visit_status.lower() == "exceeded":
                if visitor_email:
                    send_exceeded_email(visitor_email, visitor_name)
                return jsonify({"status": "denied", "message": "Duration exceeded. Please check out immediately.", "distance": 999.0})
            elif visit_status.lower() == "pending approval":
                return jsonify({"status": "denied", "message": "Visit pending employee approval. Please wait.", "distance": 999.0})
            else:
                return jsonify({"status": "denied", "message": f"Unknown visit status: {visit_status}", "distance": 999.0})

        # ──────────────────────────────────────
        # STEP A: Face embedding (hybrid or face_only)
        # ──────────────────────────────────────
        live_embedding = get_face_embedding(cv2_img)
        if live_embedding is None:
            # Debug: save what we received so you can see why no face was found
            try:
                debug_dir = os.path.join(os.path.dirname(__file__), "debug_frames")
                os.makedirs(debug_dir, exist_ok=True)
                debug_path = os.path.join(debug_dir, "last_no_face.jpg")
                cv2.imwrite(debug_path, cv2_img)
                logger.info("No face detected. Frame saved to %s (shape %s)", debug_path, getattr(cv2_img, "shape", None))
            except Exception as deb:
                logger.warning("Could not save debug frame: %s", deb)
            return jsonify({"status": "waiting", "message": "No face detected. Face the camera directly, move a bit closer, and ensure good lighting.", "distance": 999.0})

        if len(live_embedding) != 128:
            return jsonify({"status": "waiting", "message": "Face detection failed. Please try again.", "distance": 999.0})

        has_qr = qr_valid
        if AUTH_MODE == "face_only":
            has_qr = False
        auth_mode = "DUAL" if has_qr else "FACE_ONLY"

        # ──────────────────────────────────────
        # STEP C: Face matching + twin detection
        # ──────────────────────────────────────
        all_visitors = db_reference("visitors").get() or {}

        THRESHOLD = float(os.environ.get("VERIFICATION_THRESHOLD", str(VERIFICATION_THRESHOLD)))
        TWIN_STRONG = 0.45  # Below this → definitive match, no twin ambiguity

        face_matches = find_all_face_matches(live_embedding, all_visitors, threshold=THRESHOLD)

        if not face_matches:
            _, best_distance = verify_by_distance(live_embedding)
            if has_qr:
                log_security_alert("QR_NO_FACE_MATCH", db_ref,
                                   visitor_id=qr_visitor_id, visit_id=qr_visit_id,
                                   message="QR scanned but face matched no registered visitor")
                log_qr_scan(qr_visitor_id, qr_visit_id, "rejected", db_ref,
                            reason="face_no_match", ip=client_ip)
            deny_msg = "No match found. You are not registered in the system."
            if not has_qr:
                deny_msg += " If you registered without using the camera, re-register with your face or use your QR code."
            # If best distance is very high (>2), stored embedding was likely fake (registration had no face)
            if best_distance < 999.0 and best_distance > 2.0:
                deny_msg = "Face not recognized. Your face may not have been saved correctly when you registered—please re-register with your face clearly visible in the photo, then try again."
            # Always include distance when available (helps diagnose: threshold is 0.78, lower = better match)
            if best_distance < 999.0:
                deny_msg += f" (Distance: {best_distance:.2f} — threshold is {THRESHOLD:.2f}. Try: same lighting as registration, face camera directly, remove glasses if you wore them during registration, or re-register.)"
            return jsonify({
                "status": "denied",
                "message": deny_msg,
                "distance": best_distance if best_distance < 999.0 else 999.0
            })

        best_match = face_matches[0]
        face_visitor_id = best_match["visitor_id"]
        min_distance = best_match["distance"]

        # Twin / ambiguous-match detection
        is_twin, twin_matches = detect_twin(face_matches, strong_threshold=TWIN_STRONG)

        if is_twin and not has_qr:
            twin_names = ", ".join(m["name"] for m in twin_matches)
            logger.warning(f"🔀 Twin/ambiguous face detected: {twin_names}")
            log_security_alert("TWIN_DETECTED", db_ref,
                               candidates=[m["visitor_id"] for m in twin_matches],
                               distances=[round(m["distance"], 4) for m in twin_matches])
            return jsonify({
                "status": "denied",
                "message": "Ambiguous face match detected (possible twin). Please scan your QR code for verification.",
                "distance": round(min_distance, 4)
            })

        if is_twin and has_qr:
            # QR resolves the twin — use QR's visitor_id as ground truth
            face_visitor_id = qr_visitor_id
            logger.info(f"Twin resolved via QR — using visitor {qr_visitor_id}")

        # ──────────────────────────────────────
        # STEP D: Cross-verify QR ↔ Face
        # ──────────────────────────────────────
        if has_qr and face_visitor_id != qr_visitor_id:
            # Face and QR belong to different people → stolen QR
            log_security_alert("QR_FACE_MISMATCH", db_ref,
                               qr_visitor_id=qr_visitor_id,
                               face_visitor_id=face_visitor_id,
                               qr_visit_id=qr_visit_id,
                               face_distance=round(min_distance, 4),
                               ip=client_ip,
                               message="Face and QR belong to different visitors — possible stolen QR")
            log_qr_scan(qr_visitor_id, qr_visit_id, "rejected", db_ref,
                        reason="face_mismatch", face_visitor_id=face_visitor_id, ip=client_ip)

            # Invalidate the stolen QR
            invalidate_qr(qr_visitor_id, qr_visit_id,
                          "Presented by wrong person (face mismatch)", db_ref)
            log_protocol_event("invalidation", auth_mode, visitor_id=qr_visitor_id, visit_id=qr_visit_id,
                               reason="face_mismatch", face_visitor_id=face_visitor_id, ip=client_ip)

            return jsonify({
                "status": "denied",
                "message": "Security alert: QR code does not belong to you. Security has been notified.",
                "distance": round(min_distance, 4)
            })

        # ──────────────────────────────────────
        # STEP E: Load visitor data & blacklist check
        # ──────────────────────────────────────
        visitor_id = face_visitor_id
        visitor_data = all_visitors.get(visitor_id)
        if not visitor_data:
            return jsonify({"status": "denied", "message": "Visitor record not found.", "distance": min_distance})

        basic_info = visitor_data.get("basic_info", {})
        visitor_name = basic_info.get("name", "Visitor")
        visitor_email = basic_info.get("contact")
        blacklisted = str(basic_info.get("blacklisted", "no")).lower()

        if blacklisted in ["yes", "true", "1"]:
            reason = basic_info.get("blacklist_reason", "Security restriction")
            if has_qr:
                invalidate_qr(qr_visitor_id, qr_visit_id, "Visitor is blacklisted", db_ref)
                log_protocol_event("invalidation", auth_mode, visitor_id=qr_visitor_id, visit_id=qr_visit_id, reason="blacklisted")
            return jsonify({
                "status": "denied",
                "message": f"Access denied. {visitor_name} is blacklisted. Reason: {reason}",
                "distance": min_distance
            })

        # ──────────────────────────────────────
        # STEP F: Determine the target visit
        # ──────────────────────────────────────
        visits = visitor_data.get("visits", {})
        if not visits:
            return jsonify({
                "status": "denied",
                "message": f"No visits found for {visitor_name}. Please register first.",
                "distance": min_distance
            })

        if has_qr:
            visit_id = qr_visit_id
            target_visit = visits.get(visit_id)
            if not target_visit:
                return jsonify({
                    "status": "denied",
                    "message": "Visit referenced by QR code not found.",
                    "distance": min_distance
                })
        else:
            sorted_visit_ids = sorted(visits.keys(), reverse=True)
            visit_id = sorted_visit_ids[0]
            target_visit = visits[visit_id]

        # Date check
        current_date = datetime.now().strftime("%Y-%m-%d")
        visit_date = target_visit.get("visit_date")
        if visit_date and visit_date != current_date:
            return jsonify({
                "status": "denied",
                "message": f"Your visit is scheduled for {visit_date}, not today.",
                "distance": min_distance
            })

        # Extract visit fields
        visit_status = target_visit.get("status", "registered")
        employee_name = target_visit.get("employee_name")
        has_visited = target_visit.get("has_visited", False)
        purpose = target_visit.get("purpose", "")
        check_in_time = target_visit.get("check_in_time")
        duration = target_visit.get("duration", "1 hour")
        rejection_reason = target_visit.get("rejection_reason", "")
        new_visit_date = target_visit.get("new_visit_date", "")

        logger.info(f"🔍 Gate: visitor={visitor_name}, visit={visit_id}, "
                     f"status={visit_status}, auth={auth_mode}, dist={min_distance:.4f}")

        # ──────────────────────────────────────
        # Require QR + face when explicit action is requested
        if requested_action in ("checkin", "checkout") and AUTH_MODE == "hybrid" and not has_qr:
            msg = "Please scan your QR code and show your face to check in." if requested_action == "checkin" else "Please scan your QR code and show your face to check out."
            return jsonify({"status": "denied", "message": msg, "distance": min_distance})

        # Enforce requested action (checkin vs checkout)
        # ──────────────────────────────────────
        if requested_action == "checkin" and visit_status.lower() in ("checked_in", "checked_out"):
            if visit_status.lower() == "checked_in":
                return jsonify({"status": "denied", "message": "You are already checked in. Use Check Out instead.", "distance": min_distance})
            return jsonify({"status": "denied", "message": "No visit to check in. Use Check Out instead.", "distance": min_distance})
        if requested_action == "checkout" and visit_status.lower() not in ("checked_in",):
            if visit_status.lower() in ("registered", "approved", "pending approval"):
                return jsonify({"status": "denied", "message": "Please use Check In first.", "distance": min_distance})
            if visit_status.lower() == "checked_out":
                return jsonify({"status": "denied", "message": "You are already checked out.", "distance": min_distance})
            if visit_status.lower() in ("rejected", "rescheduled"):
                return jsonify({"status": "denied", "message": f"Your visit has been {visit_status}.", "distance": min_distance})
            if visit_status.lower() == "exceeded":
                return jsonify({"status": "denied", "message": "Duration exceeded. Please contact security.", "distance": min_distance})

        # ──────────────────────────────────────
        # STEP G: Handle visit status (7 states + Pending Approval)
        # ──────────────────────────────────────

        # 1. REGISTERED
        if visit_status.lower() == "registered":
            if employee_name and employee_name not in ["N/A", ""]:
                return jsonify({
                    "status": "denied",
                    "message": f"Meeting pending approval from {employee_name}. Please wait.",
                    "distance": min_distance
                })
            return process_checkin(visitor_id, visit_id, visitor_name, visitor_email,
                                  employee_name, purpose, duration, min_distance,
                                  client_ip, auth_mode, has_qr, auth_mode_config=AUTH_MODE)

        # 2. APPROVED
        elif visit_status.lower() == "approved":
            result = process_checkin(visitor_id, visit_id, visitor_name, visitor_email,
                                    employee_name, purpose, duration, min_distance,
                                    client_ip, auth_mode, has_qr, auth_mode_config=AUTH_MODE)
            resp = result.get_json()
            if resp and resp.get("status") == "granted" and employee_name and employee_name not in ["N/A", ""]:
                return jsonify({
                    "status": "granted",
                    "name": visitor_name,
                    "message": f"{employee_name} approved {visitor_name}'s visit. Check-in successful.",
                    "distance": min_distance,
                    "redirect_url": url_for("checkin_success", name=visitor_name, action="checked in")
                })
            return result

        # 3. REJECTED
        elif visit_status.lower() == "rejected":
            msg = "Your visit has been rejected."
            if employee_name and employee_name not in ["N/A", ""]:
                msg = f"{employee_name} has rejected your visit."
            if rejection_reason:
                msg += f" Reason: {rejection_reason}"
            return jsonify({"status": "denied", "message": msg, "distance": min_distance})

        # 4. RESCHEDULED
        elif visit_status.lower() == "rescheduled":
            reschedule_date = new_visit_date or visit_date
            msg = f"Your visit has been rescheduled to {reschedule_date}."
            if employee_name and employee_name not in ["N/A", ""]:
                msg = f"{employee_name} rescheduled your visit to {reschedule_date}."
            return jsonify({"status": "denied", "message": msg, "distance": min_distance})

        # 5. CHECKED-IN → process checkout (with cooldown to prevent accidental double-scan)
        elif visit_status.lower() == "checked_in":
            if has_visited:
                return jsonify({
                    "status": "denied",
                    "message": "Visit already completed. Please register a new visit.",
                    "distance": min_distance
                })
            # Enforce minimum time between check-in and checkout
            if check_in_time:
                try:
                    checkin_dt = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S")
                    elapsed = (datetime.now() - checkin_dt).total_seconds()
                    if elapsed < CHECKIN_COOLDOWN_SECONDS:
                        wait_sec = int(CHECKIN_COOLDOWN_SECONDS - elapsed)
                        return jsonify({
                            "status": "denied",
                            "message": f"You just checked in. Please wait {wait_sec} seconds before checking out.",
                            "distance": min_distance
                        })
                except (ValueError, TypeError):
                    pass
            return process_checkout(visitor_id, visit_id, visitor_name, visitor_email,
                                   check_in_time, duration, min_distance, client_ip,
                                   purpose, employee_name, auth_mode, has_qr, auth_mode_config=AUTH_MODE)

        # 6. CHECKED-OUT
        elif visit_status.lower() == "checked_out":
            return jsonify({
                "status": "denied",
                "message": f"No pending visits for today, {visitor_name}.",
                "distance": min_distance
            })

        # 7. EXCEEDED
        elif visit_status.lower() == "exceeded":
            if visitor_email:
                send_exceeded_email(visitor_email, visitor_name)
            return jsonify({
                "status": "denied",
                "message": "Duration exceeded. Please check out immediately.",
                "distance": min_distance
            })

        # 8. PENDING APPROVAL
        elif visit_status.lower() == "pending approval":
            return jsonify({
                "status": "denied",
                "message": "Visit pending employee approval. Please wait.",
                "distance": min_distance
            })

        else:
            return jsonify({
                "status": "denied",
                "message": f"Unknown visit status: {visit_status}",
                "distance": min_distance
            })

    except Exception as e:
        logger.exception("Unhandled exception in checkin_verify_and_log")
        return jsonify({"status": "error", "message": f"Server error: {e}", "distance": 999.0}), 500


# ──────────────────────────────────────────────────────────────
# Process Check-In  (with QR state management)
# ──────────────────────────────────────────────────────────────

def process_checkin(visitor_id, visit_id, visitor_name, visitor_email,
                    employee_name, purpose, duration, min_distance, client_ip,
                    auth_mode="FACE_ONLY", has_qr=False, auth_mode_config=None):
    """Process check-in and transition QR state accordingly (skipped when auth_mode_config is face_only)."""
    try:
        now = datetime.now()

        # Parse duration
        try:
            duration_hours = float(str(duration).replace("hr", "").replace("hours", "").strip())
        except Exception:
            duration_hours = 1.0

        expected_checkout = now + timedelta(hours=duration_hours)

        # ── Update QR state (skip when protocol mode is face_only) ──
        if auth_mode_config != "face_only":
            if has_qr:
                ok, err = update_qr_state(visitor_id, visit_id, QR_CHECKIN_USED, db_ref,
                                          auth_method="qr_and_face")
                if not ok:
                    logger.warning(f"QR check-in state update failed: {err}")
                log_qr_scan(visitor_id, visit_id, "checkin", db_ref,
                            auth_mode="DUAL", ip=client_ip,
                            face_distance=round(min_distance, 4))
            else:
                # Face-only → assume QR was scanned
                ok, err = update_qr_state(visitor_id, visit_id, QR_ASSUMED_SCANNED, db_ref,
                                          auth_method="face_only")
                if not ok:
                    logger.warning(f"QR assumed-scanned update failed: {err}")
                log_qr_scan(visitor_id, visit_id, "face_only", db_ref,
                            auth_mode="FACE_ONLY", ip=client_ip,
                            face_distance=round(min_distance, 4))

        # ── Update visit record ──
        db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}").update({
            "check_in_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "has_visited": False,
            "status": "checked_in",
            "expected_checkout_time": expected_checkout.strftime("%Y-%m-%d %H:%M:%S"),
            "auth_method_checkin": auth_mode,
        })

        # ── Log transaction ──
        log_key = now.strftime("%Y-%m-%d_%H:%M:%S")
        db_ref.child(f"visitors/{visitor_id}/transactions").child(log_key).set({
            "action": "check_in",
            "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
            "ip_address": client_ip,
            "purpose": purpose,
            "visit_id": visit_id,
            "employee_name": employee_name,
            "duration": duration,
            "expected_checkout": expected_checkout.strftime("%Y-%m-%d %H:%M:%S"),
            "visitor_name": visitor_name,
            "auth_mode": auth_mode,
            "face_distance": round(float(min_distance), 4),
        })

        # ── Build message ──
        if employee_name and employee_name not in ["N/A", ""]:
            message = f"Successful check-in of {visitor_name}. Meeting with {employee_name}."
        else:
            message = f"Successful check-in of {visitor_name}."
        if auth_mode == "FACE_ONLY":
            message += " (Face-only mode)"

        log_protocol_event("arrival", auth_mode, visitor_id=visitor_id, visit_id=visit_id, ip=client_ip)
        logger.info(f"✅ Check-in: {visitor_name}, visit={visit_id}, auth={auth_mode}")
        return jsonify({
            "status": "granted",
            "name": visitor_name,
            "message": message,
            "distance": round(float(min_distance), 4),
            "redirect_url": url_for("checkin_success", name=visitor_name, action="checked in"),
        })

    except Exception as e:
        logger.error(f"Error during check-in: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error during check-in: {e}",
            "distance": min_distance,
        })


# ──────────────────────────────────────────────────────────────
# Process Check-Out  (with stolen-QR detection)
# ──────────────────────────────────────────────────────────────

def process_checkout(visitor_id, visit_id, visitor_name, visitor_email,
                     check_in_time, duration, min_distance, client_ip,
                     purpose, employee_name,
                     auth_mode="FACE_ONLY", has_qr=False, auth_mode_config=None):
    """Process check-out, handle QR state transitions, detect stolen QR (skipped when auth_mode_config is face_only)."""
    try:
        now = datetime.now()

        if not check_in_time:
            return jsonify({
                "status": "error",
                "message": "System error: No check-in time recorded.",
                "distance": min_distance,
            })

        # ── Calculate visit duration ──
        start_time = datetime.strptime(check_in_time, "%Y-%m-%d %H:%M:%S")
        visit_duration = now - start_time
        d_hours = visit_duration.seconds // 3600
        d_minutes = (visit_duration.seconds % 3600) // 60
        d_seconds = visit_duration.seconds % 60
        time_spent = f"{d_hours}h {d_minutes}m {d_seconds}s" if d_hours > 0 else f"{d_minutes}m {d_seconds}s"

        # Check if time exceeded
        time_exceeded = False
        try:
            dur_h = float(str(duration).replace("hr", "").replace("hours", "").strip())
            if now > start_time + timedelta(hours=dur_h):
                time_exceeded = True
        except Exception:
            pass

        final_status = "exceeded" if time_exceeded else "checked_out"

        qr_was_invalidated = False

        # ── QR state management for checkout (skip when protocol mode is face_only) ──
        if auth_mode_config != "face_only":
            qr_state = get_qr_state(visitor_id, visit_id, db_ref)
            qr_current = qr_state.get("status", QR_UNUSED)

            if has_qr:
                # Normal checkout with QR
                ok, err = update_qr_state(visitor_id, visit_id, QR_CHECKOUT_USED, db_ref,
                                          auth_method="qr_and_face")
                if not ok:
                    logger.warning(f"QR checkout state update failed: {err}")
                log_qr_scan(visitor_id, visit_id, "checkout", db_ref,
                            auth_mode="DUAL", ip=client_ip,
                            face_distance=round(min_distance, 4))
            else:
                # Face-only checkout — stolen-QR detection
                if qr_current == QR_CHECKIN_USED:
                    # QR was used at check-in but NOT at checkout → might be lost/stolen
                    invalidate_qr(visitor_id, visit_id,
                                  "Face-only checkout after QR check-in — possible lost/stolen QR", db_ref)
                    log_protocol_event("invalidation", auth_mode, visitor_id=visitor_id, visit_id=visit_id,
                                       reason="face_only_checkout_after_qr_checkin", ip=client_ip)
                    log_security_alert("QR_POSSIBLY_STOLEN", db_ref,
                                       visitor_id=visitor_id, visit_id=visit_id,
                                       message="Visitor checked out via face only; QR was used at check-in but not at checkout",
                                       ip=client_ip)
                    qr_was_invalidated = True
                    logger.warning(f"⚠️ QR invalidated for {visitor_name} — face-only checkout after QR check-in")

                elif qr_current == QR_ASSUMED_SCANNED:
                    # Was already face-only at check-in too — no suspicion, just close it
                    invalidate_qr(visitor_id, visit_id,
                                  "Face-only checkout (QR never physically used)", db_ref)

                log_qr_scan(visitor_id, visit_id, "checkout_face_only", db_ref,
                            auth_mode="FACE_ONLY", ip=client_ip,
                            face_distance=round(min_distance, 4),
                            qr_invalidated=qr_was_invalidated)

        # ── Update visit record ──
        db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}").update({
            "has_visited": True,
            "check_out_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "status": final_status,
            "time_exceeded": time_exceeded,
            "time_spent": time_spent,
            "auth_method_checkout": auth_mode,
        })

        # ── Log transaction ──
        log_key = now.strftime("%Y-%m-%d_%H:%M:%S")
        db_ref.child(f"visitors/{visitor_id}/transactions").child(log_key).set({
            "action": "check_out",
            "check_in": check_in_time,
            "check_out": now.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_total": str(visit_duration),
            "time_spent": time_spent,
            "distance": f"{min_distance:.4f}",
            "ip_address": client_ip,
            "purpose": purpose,
            "visit_id": visit_id,
            "status": final_status,
            "visitor_name": visitor_name,
            "employee_name": employee_name,
            "auth_mode": auth_mode,
        })

        # ── Emails ──
        if final_status == "checked_out" and visitor_email:
            try:
                feedback_link = f"https://verdie-fictive-margret.ngrok-free.dev/feedback_form?visitor_id={visitor_id}"
                email_sent, _ = send_feedback_email(visitor_email, visitor_name, feedback_link)
                if email_sent:
                    logger.info(f"✅ Feedback email sent to {visitor_email}")
            except Exception as e:
                logger.error(f"❌ Error sending feedback email: {e}")

        if final_status == "exceeded" and visitor_email:
            send_exceeded_email(visitor_email, visitor_name)

        # ── Build message ──
        message = f"Successful checkout of {visitor_name}. Time spent: {time_spent}"
        if time_exceeded:
            message += " (Duration exceeded)"
        if qr_was_invalidated:
            message += " | QR invalidated for security."

        log_protocol_event("departure", auth_mode, visitor_id=visitor_id, visit_id=visit_id,
                           status=final_status, ip=client_ip)
        logger.info(f"✅ Checkout: {visitor_name}, visit={visit_id}, "
                     f"status={final_status}, auth={auth_mode}")

        return jsonify({
            "status": "checked_out",
            "name": visitor_name,
            "message": message,
            "distance": round(float(min_distance), 4),
            "redirect_url": url_for("checkin_success", name=visitor_name,
                                    action="checked out", duration=time_spent,
                                    visitor_id=visitor_id),
        })

    except Exception as e:
        logger.error(f"Error during checkout: {e}")
        return jsonify({
            "status": "error",
            "message": f"Error during checkout: {e}",
            "distance": min_distance,
        })


@app.route("/checkin_success")
def checkin_success():
    name = request.args.get('name', 'Visitor')
    action = request.args.get('action', 'processed')
    duration = request.args.get('duration')
    visitor_id = request.args.get('visitor_id', '')
    
    return render_template("checkin_success.html", 
                           visitor_name=name, 
                           action=action, 
                           duration=duration,
                           visitor_id=visitor_id)
@app.route("/trigger_notifications")
def trigger_notifications():
    """Route to manually trigger the notification check for demonstration."""
    notification_result = check_for_expiring_visits()
    return jsonify({"message": "Notification check executed successfully.", "result": notification_result})

@app.route("/feedback_form")
def feedback_form():
    visitor_id = request.args.get("visitor_id")
    return render_template("feedback_form.html", visitor_id=visitor_id)

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    visitor_id = request.form.get('visitor_id')
    feedback_text = request.form.get('feedback_text')

    if not feedback_text or feedback_text.strip() == "":
        return render_template('feedback_form.html', visitor_id=visitor_id, error="Feedback cannot be empty!")

    try:
        # Store feedback under the visitor's ID in Realtime Database with proper structure
        feedback_ref = db_reference(f'visitors/{visitor_id}/feedbacks')
        new_feedback_ref = feedback_ref.push()
        new_feedback_ref.set({
            'text': feedback_text,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'visitor_id': visitor_id
        })
        print(f"[OK] Feedback stored successfully for visitor {visitor_id}")
        
        # Verify storage
        stored_feedbacks = feedback_ref.get()
        print(f"📝 Total feedbacks stored: {len(stored_feedbacks) if stored_feedbacks else 0}")
        
    except Exception as e:
        print(f"[!] Error storing feedback: {e}")
        return render_template('feedback_form.html', visitor_id=visitor_id, error="Failed to store feedback. Please try again.")

    return render_template('thankyou.html', visitor_id=visitor_id)

# Employee Action Routes
@app.route('/employee_action/<visitor_id>')
def employee_action(visitor_id):
    try:
        visitor_ref = db_reference(f"visitors/{visitor_id}")
        visitor_data = visitor_ref.get()
        
        if not visitor_data:
            return "Visitor not found", 404
        
        # Get the latest visit
        visits = visitor_data.get("visits", {})
        latest_visit_id = None
        latest_visit = None
        
        if visits:
            latest_visit_id = max(visits.keys())
            latest_visit = visits[latest_visit_id]
        
        return render_template('employee_action.html',
                             visitor_id=visitor_id,
                             latest_visit_id=latest_visit_id,
                             purpose=latest_visit.get('purpose', 'Not specified') if latest_visit else 'Not specified',
                             status=latest_visit.get('status', 'registered') if latest_visit else 'registered',
                             visit_date=latest_visit.get('visit_date', 'Not specified') if latest_visit else 'Not specified',
                             photo_url=visitor_data.get('basic_info', {}).get('photo_url'))
    except Exception as e:
        return f"Error loading page: {str(e)}", 500

@app.route('/employee_action_approve/<visitor_id>', methods=['POST'])
def employee_action_approve(visitor_id):
    try:
        data = request.get_json()
        employee_name = data.get('employee_name', 'Employee')
        
        visitor_ref = db_reference(f"visitors/{visitor_id}")
        visitor_data = visitor_ref.get()
        
        if not visitor_data:
            return jsonify({'status': 'error', 'message': 'Visitor not found'}), 404
        
        # Get latest visit
        visits = visitor_data.get("visits", {})
        if not visits:
            return jsonify({'status': 'error', 'message': 'No visits found'}), 404
            
        latest_visit_id = max(visits.keys())
        
        # Update visit status
        db_ref.child(f"visitors/{visitor_id}/visits/{latest_visit_id}").update({
            'status': 'approved',
            'employee_name': employee_name,
            'approved_at': datetime.now().isoformat()
        })
        
        # Send notification email
        visitor_name = visitor_data.get('basic_info', {}).get('name', 'Visitor')
        visitor_email = visitor_data.get('basic_info', {}).get('contact')
        if visitor_email:
            email_body = f"""
            <p>Hi {visitor_name},</p>
            <p>Your visit has been approved by {employee_name}. You can now check-in on your scheduled date.</p>
            <p>Best regards,<br>Security Team</p>
            """
            # You can implement email sending here
        
        return jsonify({
            'status': 'success',
            'message': f'{employee_name} approved {visitor_name}\'s visit successfully'
        })
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error approving visit: {str(e)}'
        }), 500

if __name__ == "__main__":
    print("--- GATE APP STARTUP ---")
    print(f"VERIFICATION THRESHOLD: {VERIFICATION_THRESHOLD}")
    print(f"CHECKIN_COOLDOWN: {CHECKIN_COOLDOWN_SECONDS}s (min time before checkout after check-in)")
    print(f"AUTH_MODE (protocol): {AUTH_MODE} (hybrid | face_only | qr_only)")
    print(f"USE_MOCK_DATA: {USE_MOCK_DATA}")
    if COMPANY_IP:
        print(f"[OK] CHECK-IN IP ENFORCEMENT: {COMPANY_IP}")
    else:
        print("[!] WARNING: COMPANY_IP is not set in .env. IP check disabled.")
        
    app.run(host="0.0.0.0", port=5002, debug=True)