import os
import sys
import cv2
import base64
import hashlib
import numpy as np
import secrets
import json
import threading
from io import BytesIO
from collections import defaultdict, deque
from flask import Flask, render_template, request, jsonify, redirect, session, url_for
import firebase_admin
from firebase_admin import credentials, db
from firebase_admin.exceptions import NotFoundError
from datetime import datetime, timedelta
from time import time
try:
    import dlib
except ImportError:
    dlib = None  # Face recognition disabled if dlib not installed (e.g. need CMake on Windows)
from pathlib import Path
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from presentation_demo import DEFAULT_DEPARTMENT_OPTIONS, PRESENTATION_ROOM_OPTIONS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from flask import send_from_directory
import random
from werkzeug.utils import secure_filename
try:
    import requests
except ImportError:
    requests = None

try:
    import qrcode as qrcode_lib
except ImportError:
    qrcode_lib = None

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Load environment ---
load_dotenv()

# Face scan is always required for registration; no placeholder/QR-only option.

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key")
VERIFICATION_THRESHOLD = 0.6

# --- SMTP Config ---
SMTP_SERVER = os.environ.get("SMTP_SERVER")
SMTP_PORT = os.environ.get("SMTP_PORT")
EMAIL_ADDRESS = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASS")

# Debug email config
logger.info(f"Email Config Check - Server: {SMTP_SERVER}, Port: {SMTP_PORT}, User: {EMAIL_ADDRESS}")
if not all([SMTP_SERVER, SMTP_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
    logger.error("WARNING: One or more SMTP environment variables are missing. Email functionality will fail.")

# --- Upload folder ---
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads_reg")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Admin app URL (for meeting rooms list) ---
ADMIN_APP_URL = os.environ.get("ADMIN_APP_URL", "http://localhost:5000").rstrip("/")

# --- Firebase init with better error handling ---
db_app = None
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate("firebase_credentials.json")
        database_url = os.environ.get("FIREBASE_DATABASE_URL", "https://visitor-management-8f5b4-default-rtdb.firebaseio.com").rstrip("/") + "/"
        db_app = firebase_admin.initialize_app(cred, {"databaseURL": database_url})
        logger.info("Firebase initialized successfully")
    else:
        db_app = firebase_admin.get_app()
        logger.info("Firebase already initialized")
except FileNotFoundError:
    logger.critical("FATAL ERROR: firebase_credentials.json not found. Database connection will fail.")
except Exception as e:
    logger.critical(f"FATAL ERROR: Firebase initialization error: {e}")

# Global reference for the database
db_ref = db.reference() if db_app else None

# --- Visitor / visit policy helpers (registration + returning flow) ---

def _int_env(name, default):
    try:
        return int(str(os.environ.get(name, str(default))).strip())
    except (TypeError, ValueError):
        return int(default)


# Registration anti-bot safeguards (rolling windows). Set to 0 to disable a limit.
REG_LIMIT_IP_PER_MIN = _int_env("REG_LIMIT_IP_PER_MIN", 5)
REG_LIMIT_IP_PER_HOUR = _int_env("REG_LIMIT_IP_PER_HOUR", 25)
REG_LIMIT_EMAIL_PER_DAY = _int_env("REG_LIMIT_EMAIL_PER_DAY", 3)
REG_LIMIT_FACE_PER_DAY = _int_env("REG_LIMIT_FACE_PER_DAY", 3)

_RL_WINDOW_MIN = 60
_RL_WINDOW_HOUR = 3600
_RL_WINDOW_DAY = 86400
_REG_RL_LOCK = threading.Lock()
_REG_RL_EVENTS = defaultdict(deque)  # key -> deque[timestamp]


def _rl_now():
    return time()


def _rl_prune(events, now_ts, window_s):
    while events and (now_ts - events[0]) >= window_s:
        events.popleft()


def _rl_hit_limit(key, limit, window_s, now_ts=None):
    """
    Rolling-window limiter.
    Returns (allowed: bool, retry_after_seconds: int).
    """
    if limit <= 0:
        return True, 0
    if now_ts is None:
        now_ts = _rl_now()
    with _REG_RL_LOCK:
        events = _REG_RL_EVENTS[key]
        _rl_prune(events, now_ts, window_s)
        if len(events) >= limit:
            retry_after = max(1, int(window_s - (now_ts - events[0])) + 1)
            return False, retry_after
        events.append(now_ts)
        return True, 0


def _norm_email(email):
    return str(email or "").strip().lower()


def _client_ip(req):
    # Respect proxy headers when present; fall back to remote_addr.
    forwarded = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (req.remote_addr or "unknown")


def _face_fingerprint(embedding):
    # Quantize embedding to make tiny floating noise stable, then hash.
    vec = np.asarray(embedding, dtype=np.float64).flatten()
    if vec.size == 0:
        return ""
    q = np.round(vec, 3)
    return hashlib.sha256(q.tobytes()).hexdigest()


def _registration_pre_rate_limit(ip_addr, email_norm):
    checks = [
        (f"reg:ip:min:{ip_addr}", REG_LIMIT_IP_PER_MIN, _RL_WINDOW_MIN, "Too many registration attempts from this network. Please wait a minute and try again."),
        (f"reg:ip:hour:{ip_addr}", REG_LIMIT_IP_PER_HOUR, _RL_WINDOW_HOUR, "Too many registrations from this network in the last hour. Please try again later."),
    ]
    if email_norm:
        checks.append(
            (f"reg:email:day:{email_norm}", REG_LIMIT_EMAIL_PER_DAY, _RL_WINDOW_DAY, "Too many registrations for this email today. Please try again tomorrow or contact reception.")
        )
    retry_after = 0
    for key, limit, window_s, msg in checks:
        ok, ra = _rl_hit_limit(key, limit, window_s)
        if not ok:
            retry_after = max(retry_after, ra)
            return False, msg, retry_after
    return True, None, 0


def _registration_face_rate_limit(embedding):
    face_key = _face_fingerprint(embedding)
    if not face_key:
        return True, None, 0
    ok, retry_after = _rl_hit_limit(f"reg:face:day:{face_key}", REG_LIMIT_FACE_PER_DAY, _RL_WINDOW_DAY)
    if not ok:
        return (
            False,
            "Too many registration attempts with this face today. Please contact reception.",
            retry_after,
        )
    return True, None, 0


def _reset_registration_rate_limit_state_for_tests():
    with _REG_RL_LOCK:
        _REG_RL_EVENTS.clear()


def _is_blacklisted_flag(raw):
    if raw is True:
        return True
    if isinstance(raw, str) and raw.strip().lower() in ("yes", "true", "1"):
        return True
    return False


def _visitor_basic_is_blacklisted(basic_info, visitor_root=None):
    raw = (basic_info or {}).get("blacklisted")
    if raw is None and visitor_root is not None:
        raw = visitor_root.get("blacklisted", "no")
    return _is_blacklisted_flag(raw)


def _visitor_has_active_check_in(visitor_data):
    """True if any visit has check_in_time set and check_out_time still empty."""
    if not visitor_data or not isinstance(visitor_data, dict):
        return False
    visits = visitor_data.get("visits") or {}
    if not isinstance(visits, dict):
        return False
    for v in visits.values():
        if not isinstance(v, dict):
            continue
        cin = v.get("check_in_time")
        cout = v.get("check_out_time")
        if cin and str(cin).strip():
            if not cout or not str(cout).strip():
                return True
    return False


MSG_ACTIVE_CHECK_IN = (
    "You are already checked in for an active visit. Check out at the gate before registering again."
)
MSG_BLACKLISTED = (
    "You have been blacklisted and cannot schedule new visits. "
    "Please contact security or reception."
)
# Same neutral copy as verify_face when blacklisted vs non-blacklisted faces are ambiguous (twins).
MSG_REGISTRATION_FACE_AMBIGUOUS = (
    "We could not confidently verify your identity. "
    "Please contact reception or use your registered email."
)


def _registration_biometric_blacklist_block(live_embedding, db_ref):
    """Block registration if the captured face matches a blacklisted visitor (twin-aware).

    Mirrors verify_face's no-email path: VERIFICATION_THRESHOLD, fixed TWIN_GAP=0.08.

    Returns:
        (deny, user_message, blacklist_reason_or_none)
        If deny and user_message == MSG_BLACKLISTED, the third value is for notification email.
    """
    if db_ref is None:
        return False, None, None
    if live_embedding is None:
        return False, None, None
    le = np.asarray(live_embedding, dtype=np.float64).flatten()
    if le.size != 128:
        logger.warning(
            "registration biometric blacklist: skip (embedding size %s, expected 128)", le.size
        )
        return False, None, None

    try:
        threshold = float(os.environ.get("VERIFICATION_THRESHOLD", "0.65"))
    except ValueError:
        threshold = 0.65
    twin_gap = 0.08

    try:
        all_visitors = db_ref.child("visitors").get() or {}
    except Exception as e:
        logger.error("registration biometric blacklist: failed to load visitors: %s", e)
        return False, None, None

    candidates = []
    for vid, vdata in all_visitors.items():
        if not isinstance(vdata, dict):
            continue
        basic = vdata.get("basic_info") or {}
        if not isinstance(basic, dict):
            basic = {}
        emb_str = basic.get("embedding")
        if not emb_str:
            continue
        try:
            stored = np.array([float(x) for x in str(emb_str).strip().split()], dtype=np.float64)
            if stored.size != le.size:
                continue
            dist = float(np.linalg.norm(le - stored))
            is_bl = _visitor_basic_is_blacklisted(basic, vdata)
            candidates.append(
                {
                    "visitor_id": vid,
                    "distance": dist,
                    "is_blacklisted": is_bl,
                    "name": basic.get("name", "Unknown"),
                }
            )
        except Exception as ex:
            logger.error("registration biometric blacklist: embedding error for %s: %s", vid, ex)
            continue

    if not candidates:
        return False, None, None

    candidates.sort(key=lambda c: c["distance"])
    best = candidates[0]
    min_distance = best["distance"]
    if min_distance > threshold:
        return False, None, None

    second = candidates[1] if len(candidates) > 1 else None
    gap = abs(second["distance"] - best["distance"]) if second is not None else float("inf")

    # Ambiguous: blacklisted vs non-blacklisted within twin gap (same as verify_face Case B).
    if (
        second is not None
        and gap < twin_gap
        and (best["is_blacklisted"] != second["is_blacklisted"])
    ):
        logger.warning(
            "Registration blocked: ambiguous face between blacklisted and non-blacklisted (gap=%.4f).",
            gap,
        )
        return True, MSG_REGISTRATION_FACE_AMBIGUOUS, None

    # Unambiguous blacklisted match: best is blacklisted and clearly wins, or both top matches are blacklisted.
    if best["is_blacklisted"]:
        if second is None or gap >= twin_gap or second["is_blacklisted"]:
            vid_bl = best["visitor_id"]
            bi = (all_visitors.get(vid_bl) or {}).get("basic_info") or {}
            reason = bi.get("blacklist_reason", "Security restriction")
            logger.warning(
                "Registration blocked: face matches blacklisted visitor %s (dist=%.4f).",
                vid_bl,
                min_distance,
            )
            return True, MSG_BLACKLISTED, reason

    return False, None, None


def collect_department_choices():
    """Sorted unique departments: defaults plus any department strings on employee records."""
    depts = set(DEFAULT_DEPARTMENT_OPTIONS)
    if db_ref is not None:
        try:
            for ed in (db_ref.child("employees").get() or {}).values():
                d = (ed or {}).get("department")
                if d and str(d).strip():
                    depts.add(str(d).strip())
        except Exception as ex:
            logger.warning("Could not load departments from employees: %s", ex)
    return sorted(depts, key=lambda x: (x.lower(), x))


def allowed_department_set():
    return frozenset(collect_department_choices())


def _merge_rooms_for_registration(remote_dict):
    """Real rooms from Admin first; add presentation rooms if those ids are missing."""
    out = {}
    if isinstance(remote_dict, dict):
        out.update(remote_dict)
    for room_id, meta in PRESENTATION_ROOM_OPTIONS.items():
        if room_id not in out:
            out[room_id] = dict(meta)
    return out


# --- YuNet (primary) + Dlib + OpenCV Haar fallback; no placeholder/mock ---
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
        _yunet_model_path = os.path.abspath(os.path.join(_script_dir, "..", "gate", "face_detection_yunet_2023mar.onnx"))
        if hasattr(cv2, "FaceDetectorYN") and os.path.isfile(_yunet_model_path):
            try:
                _yunet_detector = cv2.FaceDetectorYN.create(_yunet_model_path, "", (320, 320))
                logger.info("YuNet + Dlib + Haar loaded (YuNet primary)")
            except Exception as e:
                logger.warning("YuNet init failed, using dlib+Haar only: %s", e)
                _yunet_detector = None
        else:
            if not hasattr(cv2, "FaceDetectorYN"):
                logger.info("OpenCV FaceDetectorYN not available; using Dlib + Haar only")
            elif not os.path.isfile(_yunet_model_path):
                logger.info("YuNet model not found at %s; using Dlib + Haar only", _yunet_model_path)
            logger.info("Dlib + OpenCV Haar loaded")
    except Exception as e:
        logger.error("WARNING: Dlib model files not found or initialized: %s", e)

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
    """Run full detection pipeline at one scale. min_side=0 means no resize."""
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

    # Try Haar first (often more forgiving for frontal faces in varied lighting)
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
    """Try multiple scales (downscale and upscale); YuNet + dlib + Haar. No placeholder."""
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
                    logger.info("Generated embedding (Register) - shape %s", out.shape)
                    return out
        return None
    except Exception as e:
        logger.error("Dlib embedding error: %s", e)
        return None

# --- Helper functions ---
def l2_distance(vec1, vec2):
    return np.linalg.norm(np.array(vec1) - np.array(vec2))

_SENTINEL_IDS = frozenset({"null", "none", "undefined", "nan", "true", "false", ""})

def _is_valid_visitor_id(vid):
    """Reject IDs that are JS/Python sentinel values or empty."""
    s = str(vid or "").strip()
    return bool(s) and s.lower() not in _SENTINEL_IDS

def _is_plausible_email(email):
    e = (email or "").strip().lower()
    if not e or e in ("n/a", "none", "unknown", "not provided", "no email"):
        return False
    return "@" in e


# --- Email Functions ---
def send_email(recipient_email, recipient_name, profile_link):
    """Send email to visitor with their profile link"""
    if not _is_plausible_email(recipient_email):
        return False, "Invalid or missing recipient email"
    logger.info(f"Attempting to send profile link email to: {recipient_email}")
    
    if not all([SMTP_SERVER, SMTP_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
        error_msg = "Email environment variables missing. Skipping email."
        logger.error(error_msg)
        return False, error_msg
    
    try:
        msg = MIMEMultipart("alternative")
        msg['Subject'] = "Visitor Registration Confirmed"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient_email
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h2 style="color: #3f37c9; text-align: center;">Visitor Registration Confirmed</h2>
                <p>Hello <strong>{recipient_name}</strong>,</p>
                <p>Your visitor registration has been successfully completed.</p>
                <p>You can access your profile using the link below:</p>
                <div style="text-align: center; margin: 25px 0;">
                    <a href="{profile_link}" 
                       style="background-color: #3f37c9; color: white; padding: 12px 24px; 
                              text-decoration: none; border-radius: 5px; display: inline-block;">
                        View Your Profile
                    </a>
                </div>
                <p><strong>Profile Link:</strong><br>
                <a href="{profile_link}">{profile_link}</a></p>
                <p>Please keep this link for future reference.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="font-size: 12px; color: #666;">
                    This is an automated message from the Workplace Intelligence Platform with Hybrid Face–QR Authentication.
                </p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_content, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, recipient_email, msg.as_string())
        server.quit()
        
        logger.info(f"Profile link email successfully sent to {recipient_email}")
        return True, "Email sent successfully"
        
    except smtplib.SMTPAuthenticationError:
        error_msg = "SMTP Authentication Error: Check EMAIL_USER and EMAIL_PASS."
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"General Email error during visitor profile send: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def send_employee_notification(employee_email, employee_name, visitor_data, profile_url):
    """Send notification email to employee with a single 'View Visitor Profile' button."""
    logger.info(f"Attempting to send employee notification to: {employee_email}")
    
    if not all([SMTP_SERVER, SMTP_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
        error_msg = "Email environment variables missing. Skipping employee notification."
        logger.error(error_msg)
        return False, error_msg

    try:
        msg = MIMEMultipart("alternative")
        msg['Subject'] = f"Visitor Request: {visitor_data['name']} wants to meet you"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = employee_email

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; background-color:#f8f9fa; padding: 20px;">
            <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 12px; padding: 25px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <h2 style="color: #3f37c9; text-align: center;">Visitor Meeting Request</h2>
                <p>Hello <strong>{employee_name}</strong>,</p>
                <p>A visitor has registered to meet you. Please review their profile and decide further action from the portal.</p>

                <div style="background-color: #f1f3f6; padding: 15px; border-radius: 10px; margin: 20px 0;">
                    <h3 style="color: #333; margin-top: 0;">Visitor Details:</h3>
                    <p><strong>Name:</strong> {visitor_data.get('name', 'N/A')}</p>
                    <p><strong>Email:</strong> {visitor_data.get('contact', 'N/A')}</p>
                    <p><strong>Purpose:</strong> {visitor_data.get('purpose', 'N/A')}</p>
                    <p><strong>Duration:</strong> {visitor_data.get('duration', 'N/A')}</p>
                    <p><strong>Visit Date:</strong> {visitor_data.get('visit_date', 'N/A')}</p>
                </div>

                <div style="text-align: center; margin: 25px 0;">
                    <a href="{profile_url}" 
                       style="background-color: #3f37c9; color: white; padding: 14px 30px; 
                              text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold;">
                        View Visitor Profile
                    </a>
                </div>

                <p style="font-size: 13px; color: #777; text-align: center;">
                    This is an automated message from the Workplace Intelligence Platform with Hybrid Face–QR Authentication.
                </p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, 'html'))

        server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, employee_email, msg.as_string())
        server.quit()

        logger.info(f"Employee notification successfully sent to {employee_email}")
        return True, "Employee notification sent successfully"

    except smtplib.SMTPAuthenticationError:
        error_msg = "SMTP Authentication Error: Check EMAIL_USER and EMAIL_PASS."
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"General Email error during employee notification send: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def send_custom_email(recipient_email, subject, body):
    """Send custom email for notifications"""
    if not _is_plausible_email(recipient_email):
        logger.warning(f"Skipping custom email — invalid recipient: {recipient_email}")
        return False
    logger.info(f"Attempting to send custom email to: {recipient_email}")
    
    if not all([SMTP_SERVER, SMTP_PORT, EMAIL_ADDRESS, EMAIL_PASSWORD]):
        logger.error("Email environment variables missing. Skipping custom email.")
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg['Subject'] = subject
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = recipient_email
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h3 style="color: #3f37c9;">Workplace Intelligence Platform Notification</h3>
                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px;">
                    {body.replace('\n', '<br>')}
                </div>
                <br>
                <p style="font-size: 12px; color: #666;">
                    This is an automated message from the Workplace Intelligence Platform with Hybrid Face–QR Authentication
                </p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html_content, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, recipient_email, msg.as_string())
        server.quit()
        
        logger.info(f"Custom email sent successfully to {recipient_email}")
        return True
        
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP Authentication Error during custom email. Check credentials.")
        return False
    except Exception as e:
        logger.error(f"General Email error during custom send: {e}")
        return False


def send_blacklist_registration_denial_email(recipient_email, visitor_name, blacklist_reason):
    """Email the visitor when registration is denied for blacklist (email account or biometric match)."""
    if not recipient_email:
        return
    reason = (blacklist_reason or "Security restriction").strip() or "Security restriction"
    subject = "Your visit has been rejected – you are blacklisted"
    body_lines = [
        f"Hello {visitor_name},",
        "",
        "Our records show that you have been placed on the visitor blacklist,",
        "so new visit registrations cannot be created for you.",
        f"Reason: {reason}",
        "",
        "If you believe this is a mistake, please contact security or reception.",
    ]
    body = "\n".join(body_lines)
    try:
        send_custom_email(recipient_email, subject, body)
    except Exception as mail_err:
        logger.error(f"Error sending blacklist registration denial email: {mail_err}")


# ──────────────────────────────────────────────
# QR Code Generation Helpers
# ──────────────────────────────────────────────
QR_EXPIRY_HOURS = 36  # QR valid for visit_date + 36 h

def _generate_qr_token():
    """Generate a cryptographically-secure QR token."""
    return secrets.token_urlsafe(32)

def _generate_qr_payload(visitor_id, visit_id, visit_date, token):
    """Create the compact JSON payload for the QR code."""
    try:
        date_obj = datetime.strptime(str(visit_date), "%Y-%m-%d")
        expiry = date_obj + timedelta(hours=QR_EXPIRY_HOURS)
    except (ValueError, TypeError):
        expiry = datetime.now() + timedelta(hours=QR_EXPIRY_HOURS)

    return json.dumps({
        "v": str(visitor_id),
        "i": str(visit_id),
        "k": str(token),
        "e": expiry.strftime("%Y-%m-%d %H:%M:%S"),
    }, separators=(",", ":"))

def _generate_qr_image_base64(payload_string):
    """Generate QR code image and return as data-URI base64 string."""
    if qrcode_lib is None:
        logger.error("qrcode library not installed – cannot generate QR image")
        return None
    try:
        qr = qrcode_lib.QRCode(
            version=None,
            error_correction=qrcode_lib.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(payload_string)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except Exception as exc:
        logger.error(f"Error generating QR image: {exc}")
        return None

def _create_qr_for_visit(visitor_id, visit_id, visit_date):
    """
    Generate QR token, payload, image, and Firebase data for a visit.
    Returns (token, payload_string, image_base64, firebase_data_dict).
    """
    token = _generate_qr_token()
    payload_string = _generate_qr_payload(visitor_id, visit_id, visit_date, token)
    image_base64 = _generate_qr_image_base64(payload_string)

    try:
        date_obj = datetime.strptime(str(visit_date), "%Y-%m-%d")
        expiry = date_obj + timedelta(hours=QR_EXPIRY_HOURS)
    except (ValueError, TypeError):
        expiry = datetime.now() + timedelta(hours=QR_EXPIRY_HOURS)

    firebase_data = {
        "qr_token": token,
        "qr_payload": payload_string,
        "qr_expires_at": expiry.strftime("%Y-%m-%d %H:%M:%S"),
        "qr_max_scans": 2,
        "qr_created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "qr_state": {
            "status": "UNUSED",
            "scan_count": 0,
            "checkin_scan_time": None,
            "checkout_scan_time": None,
            "auth_method": None,
            "invalidated_at": None,
            "invalidated_reason": None,
        },
    }
    return token, payload_string, image_base64, firebase_data


# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/rooms')
def api_rooms():
    """Return meeting rooms from Admin app plus presentation demo rooms (for registration dropdown)."""
    remote = {}
    if requests:
        try:
            r = requests.get(f"{ADMIN_APP_URL}/api/rooms/list", timeout=5)
            if r.ok:
                j = r.json()
                if isinstance(j, dict):
                    remote = j
        except Exception as e:
            logger.warning(f"Could not fetch rooms from Admin: {e}")
    return jsonify(_merge_rooms_for_registration(remote))

@app.route('/register')
def register_page():
    return render_template('register.html', departments=collect_department_choices())


@app.route('/departments', methods=['GET'])
def get_departments():
    """Departments visitors may select (defaults + unique employee departments)."""
    return jsonify(collect_department_choices())


@app.route('/employees', methods=['GET'])
def get_employees():
    """Deprecated: registration uses /departments. Returns empty list for old clients."""
    return jsonify([])

@app.route('/api/debug_detect')
def api_debug_detect():
    """Run detection on last_no_face.jpg and report which detector finds a face. Helps diagnose why face isn't detected."""
    debug_path = os.path.join(_script_dir, "debug_frames", "last_no_face.jpg")
    if not os.path.isfile(debug_path):
        return jsonify({"error": "No debug frame. Trigger 'No face detected' on registration page first."}), 404

    cv2_img = cv2.imread(debug_path)
    if cv2_img is None:
        return jsonify({"error": "Could not load image"}), 500

    h, w = cv2_img.shape[:2]
    gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
    rgb = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)

    results = {"image_size": f"{w}x{h}", "haar": [], "yunet": [], "dlib": []}

    # Test Haar
    if _cv_face_cascade is not None:
        for (sf, mn, ms) in [(1.2, 2, (15, 15)), (1.15, 3, (20, 20)), (1.1, 2, (25, 25))]:
            rects = _cv_face_cascade.detectMultiScale(gray, scaleFactor=sf, minNeighbors=mn, minSize=ms)
            if len(rects) > 0:
                results["haar"].append({"params": f"sf={sf} mn={mn} ms={ms}", "count": len(rects), "rects": rects.tolist()[:3]})
        # Also try flipped
        gray_f = cv2.flip(gray, 1)
        rects = _cv_face_cascade.detectMultiScale(gray_f, scaleFactor=1.2, minNeighbors=2, minSize=(15, 15))
        if len(rects) > 0 and not results["haar"]:
            results["haar"].append({"params": "flipped", "count": len(rects)})

    # Test YuNet
    if _yunet_detector is not None:
        _yunet_detector.setInputSize((w, h))
        _, dets = _yunet_detector.detect(cv2_img)
        if dets is not None and dets.shape[0] >= 1:
            results["yunet"].append({"count": dets.shape[0], "first": dets[0].tolist()})
        else:
            cv2_f = cv2.flip(cv2_img, 1)
            _, dets = _yunet_detector.detect(cv2_f)
            if dets is not None and dets.shape[0] >= 1:
                results["yunet"].append({"count": dets.shape[0], "flipped": True})

    # Test dlib
    if detector is not None:
        for upsample in (0, 1, 2):
            faces = detector(rgb, upsample)
            if len(faces) > 0:
                results["dlib"].append({"upsample": upsample, "count": len(faces)})
                break
        if not results["dlib"]:
            rgb_f = cv2.flip(rgb, 1)
            for upsample in (0, 1, 2):
                faces = detector(rgb_f, upsample)
                if len(faces) > 0:
                    results["dlib"].append({"upsample": upsample, "count": len(faces), "flipped": True})
                    break

    emb = get_face_embedding(cv2_img)
    results["final_embedding"] = emb is not None
    return jsonify(results)


@app.route('/debug_last_face')
def debug_last_face():
    """Serve the last frame that had no face detected (for debugging)."""
    debug_path = os.path.join(_script_dir, "debug_frames", "last_no_face.jpg")
    if not os.path.isfile(debug_path):
        return "<p>No debug frame yet. Use the registration page and trigger 'No face detected' once.</p>", 404
    return send_from_directory(os.path.dirname(debug_path), "last_no_face.jpg", mimetype="image/jpeg")


@app.route('/debug_detect')
def debug_detect_page():
    """Page showing detection diagnostic + image. Visit after 'No face detected'."""
    debug_path = os.path.join(_script_dir, "debug_frames", "last_no_face.jpg")
    if not os.path.isfile(debug_path):
        return "<p>No debug frame. Trigger 'No face detected' on registration page first.</p><p><a href='/register'>Go to Register</a></p>", 404
    try:
        cv2_img = cv2.imread(debug_path)
        if cv2_img is None:
            diag = {"error": "Could not load image"}
        else:
            cv2_img = np.ascontiguousarray(cv2_img.astype(np.uint8))
            h, w = cv2_img.shape[:2]
            gray = np.ascontiguousarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY).astype(np.uint8))
            rgb = _to_dlib_format(cv2_img, rgb=True)
            diag = {"image_size": f"{w}x{h}"}
            if _cv_face_cascade is not None:
                r = _cv_face_cascade.detectMultiScale(gray, 1.2, 2, minSize=(15, 15))
                diag["haar_default"] = len(r)
            if _cv_face_alt2 is not None:
                r = _cv_face_alt2.detectMultiScale(gray, 1.2, 2, minSize=(15, 15))
                diag["haar_alt2"] = len(r)
            if _yunet_detector is not None:
                _yunet_detector.setInputSize((w, h))
                _, d = _yunet_detector.detect(cv2_img)
                diag["yunet"] = int(d.shape[0]) if d is not None else 0
            if detector is not None and rgb is not None:
                f = detector(rgb, 1)
                diag["dlib"] = len(f)
            try:
                diag["embedding"] = get_face_embedding(cv2_img) is not None
            except Exception as emb_err:
                diag["embedding"] = False
                diag["embedding_error"] = str(emb_err)
    except Exception as e:
        diag = {"error": str(e)}
    return f"""
    <html><head><title>Face Detection Debug</title></head><body style="font-family:sans-serif;padding:20px">
    <h1>Face Detection Diagnostic</h1>
    <p><img src="/debug_last_face" style="max-width:400px;border:2px solid #333"/></p>
    <pre>{json.dumps(diag, indent=2)}</pre>
    <p>haar_default/haar_alt2: faces found by Haar cascades. yunet: by YuNet. dlib: by dlib. embedding: final result.</p>
    <p><a href="/register">Back to Register</a></p>
    </body></html>
    """


@app.route('/api/face_required')
def api_face_required():
    """Returns whether face detection is required for registration (always True)."""
    return jsonify({"face_required": True})


@app.route('/api/face_debug')
def api_face_debug():
    """Diagnostic: face detection system status. Visit /api/face_debug to see if dlib/models are loaded."""
    return jsonify({
        "dlib_loaded": dlib is not None,
        "predictor_loaded": predictor is not None,
        "face_recognizer_loaded": face_recognizer is not None,
        "haar_loaded": _cv_face_cascade is not None,
        "yunet_loaded": _yunet_detector is not None,
        "yunet_path": str(_yunet_model_path) if _yunet_model_path else None,
        "yunet_exists": os.path.isfile(_yunet_model_path) if _yunet_model_path and isinstance(_yunet_model_path, str) else False,
        "shape_path": os.path.join(_script_dir, "shape_predictor_68_face_landmarks.dat"),
        "shape_exists": os.path.isfile(os.path.join(_script_dir, "shape_predictor_68_face_landmarks.dat")),
        "face_model_exists": os.path.isfile(os.path.join(_script_dir, "dlib_face_recognition_resnet_model_v1.dat")),
    })


@app.route('/api/check_face', methods=['POST'])
def api_check_face():
    """Check if a face is detectable in the image. Used for live feedback during registration."""
    try:
        data = request.get_json() or {}
        img_b64 = data.get("image")
        if not img_b64 or "," not in str(img_b64):
            return jsonify({"face_detected": False, "error": "No image"}), 400

        photo_base64 = str(img_b64).split(",")[1]
        np_img = np.frombuffer(base64.b64decode(photo_base64), np.uint8)
        cv2_img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        if cv2_img is None:
            return jsonify({"face_detected": False, "error": "Invalid image"}), 400

        if not predictor or not face_recognizer:
            return jsonify({"face_detected": False, "error": "Face recognition not loaded"}), 500

        emb = get_face_embedding(cv2_img)
        if emb is None:
            try:
                debug_dir = os.path.join(_script_dir, "debug_frames")
                os.makedirs(debug_dir, exist_ok=True)
                cv2.imwrite(os.path.join(debug_dir, "last_no_face.jpg"), cv2_img)
            except Exception:
                pass
        return jsonify({
            "face_detected": emb is not None and len(emb) == 128,
            "hint": "Face the camera directly, ensure good lighting, move slightly closer." if emb is None else None,
        })
    except Exception as e:
        logger.exception("check_face error: %s", e)
        return jsonify({"face_detected": False, "error": str(e)}), 500


@app.route('/register', methods=['POST'])
def finalize_registration():
    try:
        # Clear any existing session data first
        session.clear()
        
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data received"}), 400

        logger.info(f"--- STARTING NEW REGISTRATION FOR: {data.get('name')} ---")
        
        if db_ref is None:
            return jsonify({"success": False, "message": "Internal Server Error: Database not connected."}), 500

        name = data.get("name")
        email = data.get("email")
        duration = data.get("duration", "Not sure")
        photo_base64_full = data.get("photo_base64")
        visit_date = data.get("visit_date")

        if not all([name, email, photo_base64_full]):
            return jsonify({"success": False, "message": "Missing required fields"}), 400

        ip_addr = _client_ip(request)
        email_norm = _norm_email(email)
        pre_ok, pre_msg, pre_retry = _registration_pre_rate_limit(ip_addr, email_norm)
        if not pre_ok:
            resp = jsonify({"success": False, "message": pre_msg})
            resp.status_code = 429
            resp.headers["Retry-After"] = str(pre_retry)
            return resp

        if not photo_base64_full or "," not in photo_base64_full:
            return jsonify({"success": False, "message": "Invalid photo data"}), 400

        photo_base64 = photo_base64_full.split(",")[1]

        # Handle purpose: department visit vs free-text "other"
        purpose_type = data.get("purposeType")
        department_choice = (data.get("departmentSelect") or "").strip()
        custom_purpose = data.get("purpose", "Other")

        employee_name = None
        employee_id = None
        employee_data = None
        department = ""
        requires_employee_approval = False

        if purpose_type == "meetDepartment":
            if not department_choice:
                return jsonify({
                    "success": False,
                    "message": "Please select a department from the list.",
                }), 400
            allowed = allowed_department_set()
            if department_choice not in allowed:
                return jsonify({
                    "success": False,
                    "message": "Please select a valid department from the list.",
                }), 400
            department = department_choice
            purpose = f"Visit to {department} department"
        else:
            purpose = custom_purpose

        # Save photo to uploads_reg folder
        try:
            image_data = base64.b64decode(photo_base64)
            
            uploads_reg_folder = "uploads_reg"
            if not os.path.exists(uploads_reg_folder):
                os.makedirs(uploads_reg_folder)
            
            filename = f"{name.replace(' ', '_')}_{int(time())}.jpg"
            filepath = os.path.join(uploads_reg_folder, filename)
            
            with open(filepath, "wb") as f:
                f.write(image_data)
            
            photo_url = f"/uploads_reg/{filename}"
            logger.info(f"Photo saved successfully: {filename}")
            
        except Exception as e:
            logger.error(f"Error saving photo: {e}")
            return jsonify({"success": False, "message": "Failed to save photo"}), 500

        # Generate face embedding (required for face recognition at gate)
        try:
            if not predictor or not face_recognizer:
                return jsonify({
                    "success": False,
                    "message": "Face recognition is not available. Please ensure dlib and model files (shape_predictor_68_face_landmarks.dat, dlib_face_recognition_resnet_model_v1.dat) are installed in registration/."
                }), 500
            np_img = np.frombuffer(base64.b64decode(photo_base64), np.uint8)
            cv2_img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
            if cv2_img is None:
                return jsonify({
                    "success": False,
                    "message": "Invalid image. Please capture your photo again using the camera."
                }), 400
            h, w = cv2_img.shape[:2]
            if w * h < 10000:
                return jsonify({
                    "success": False,
                    "message": "Image too small. Please ensure your face is clearly visible in the camera frame."
                }), 400
            embedding_array = get_face_embedding(cv2_img)
            if embedding_array is not None:
                embedding_str = " ".join(map(str, embedding_array.flatten().tolist()))
            else:
                logger.warning("No face detected in registration photo")
                return jsonify({
                    "success": False,
                    "message": "No face detected in the photo. Please ensure your face is clearly visible, well-lit, and facing the camera directly. Try again in good lighting."
                }), 400
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return jsonify({"success": False, "message": "Face analysis failed"}), 500

        face_ok, face_msg, face_retry = _registration_face_rate_limit(embedding_array)
        if not face_ok:
            resp = jsonify({"success": False, "message": face_msg})
            resp.status_code = 429
            resp.headers["Retry-After"] = str(face_retry)
            return resp

        # CREATE OR REUSE VISITOR (email-based)
        visitor_id = None
        existing_basic = None
        existing_vdata = None
        is_blacklisted = False

        if db_ref is not None and email:
            try:
                all_visitors = db_ref.child("visitors").get() or {}
                for vid, vdata in all_visitors.items():
                    bi = (vdata or {}).get("basic_info", {})
                    if str(bi.get("contact", "")).strip().lower() == str(email).strip().lower():
                        visitor_id = vid
                        existing_basic = bi
                        existing_vdata = vdata
                        break
            except Exception as lookup_err:
                logger.warning(f"Error looking up existing visitor by email: {lookup_err}")

        if visitor_id is None:
            # No existing visitor with this email – create a new one
            visitor_id = str(int(time() * 1000))
            profile_link = request.url_root.rstrip("/") + url_for('profile_page', visitor_id=visitor_id)
            base_data = {
                "name": name,
                "contact": email,
                "photo_filename": filename,
                "photo_url": photo_url,
                "photo_path": filepath,
                "embedding": embedding_str,
                "blacklisted": "no",
                "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "profile_link": profile_link
            }
        else:
            # Reuse existing visitor record for this email, updating embedding and photo
            is_blacklisted = str(existing_basic.get("blacklisted", "no")).lower() in ("yes", "true", "1")
            profile_link = existing_basic.get("profile_link") or (
                request.url_root.rstrip("/") + url_for('profile_page', visitor_id=visitor_id)
            )
            base_data = {
                "name": name,
                "contact": email,
                "photo_filename": filename,
                "photo_url": photo_url,
                "photo_path": filepath,
                "embedding": embedding_str,
                "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "profile_link": profile_link,
            }

        if visitor_id is not None and existing_vdata is not None and _visitor_has_active_check_in(existing_vdata):
            logger.warning(f"Blocked registration: visitor {visitor_id} already has an active check-in.")
            return jsonify({"success": False, "message": MSG_ACTIVE_CHECK_IN}), 403

        # If this email belongs to an already blacklisted visitor, block new registrations
        if is_blacklisted:
            logger.warning(f"Blocked registration attempt for blacklisted visitor {visitor_id} ({email}).")
            blacklist_reason = (existing_basic or {}).get("blacklist_reason", "Security restriction")
            send_blacklist_registration_denial_email(email, name, blacklist_reason)

            return jsonify({
                "success": False,
                "message": MSG_BLACKLISTED,
            }), 403

        # Biometric blacklist: same person cannot bypass blacklist by registering with a new email.
        bio_deny, bio_msg, bio_reason = _registration_biometric_blacklist_block(embedding_array, db_ref)
        if bio_deny:
            if bio_msg == MSG_BLACKLISTED:
                send_blacklist_registration_denial_email(email, name, bio_reason)
            return jsonify({"success": False, "message": bio_msg}), 403

        # Create or update visitor and create visit in Firebase (may raise NotFoundError if Realtime Database not created)
        try:
            # Create or update visitor basic_info
            db_ref.child(f"visitors/{visitor_id}/basic_info").update(base_data)
            logger.info(f"VISITOR RECORD SAVED: {name} with ID: {visitor_id}")

            # Create new visit record with employee approval logic
            visit_id = str(int(time() * 1000))
            
            # Determine initial status and approval based on whether employee approval is needed
            if is_blacklisted:
                initial_status = "Blacklisted"
                is_approved = False
            else:
                initial_status = "Pending Approval" if requires_employee_approval else "Registered"
                is_approved = not requires_employee_approval
            
            visit_data = {
                "visit_id": visit_id,
                "purpose": purpose,
                "employee_id": employee_id,
                "employee_name": employee_name if employee_name else "N/A",
                "department": department,
                "duration": duration,
                "visit_date": visit_date if visit_date else datetime.now().strftime('%Y-%m-%d'),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "check_in_time": None,
                "check_out_time": None,
                "time_spent": None,
                "status": initial_status,  # "Pending Approval" for employee meetings, "Registered" for others
                "visit_approved": is_approved,  # False for employee meetings, True for others
                "has_visited": False,
                "requires_employee_approval": requires_employee_approval,  # CRITICAL: Only True for employee meetings
                "employee_notified": False,  # Will be updated after email sent
                "employee_actions": [],  # Initialize empty actions array for tracking decisions
                "room_id": data.get("room_id") or ""  # Meeting room (from Admin meeting_rooms)
            }

            # Save the visit under visitor
            db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}").set(visit_data)
            logger.info(f"NEW VISIT CREATED under visitor {visitor_id} - Status: {initial_status}")

            # GENERATE QR CODE for this visit (skip if visitor is blacklisted)
            qr_image = None
            if not is_blacklisted:
                effective_visit_date = visit_date if visit_date else datetime.now().strftime('%Y-%m-%d')
                try:
                    qr_token, qr_payload, qr_image, qr_firebase = _create_qr_for_visit(
                        visitor_id, visit_id, effective_visit_date
                    )
                    # Merge QR data into the visit record
                    db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}").update(qr_firebase)
                    logger.info(f"QR code generated for visit {visit_id}")
                except Exception as qr_exc:
                    logger.error(f"QR generation failed (non-fatal): {qr_exc}")
                    qr_image = None
            else:
                logger.warning(f"Visitor {visitor_id} is blacklisted; QR generation skipped for visit {visit_id}")

            # Update root visitor status based on whether approval is needed or blacklisted
            if is_blacklisted:
                root_status = "Blacklisted"
            else:
                root_status = "Pending Approval" if requires_employee_approval else "Registered"
            db_ref.child(f"visitors/{visitor_id}").update({
                "status": root_status,
                "last_visit_id": visit_id
            })
        except NotFoundError:
            logger.error("Firebase 404 when saving visitor. Realtime Database may not exist — create it in Firebase Console (Build → Realtime Database → Create Database) and set FIREBASE_DATABASE_URL in .env.")
            return jsonify({
                "success": False,
                "message": "Database unavailable. Create the Realtime Database in Firebase Console (Build → Realtime Database → Create Database), then set FIREBASE_DATABASE_URL in registration/.env. See FIREBASE_CREDENTIALS_SETUP.txt."
            }), 503

        # STORE IN SESSION
        session['current_visitor'] = {
            'visitor_id': visitor_id,
            'visit_id': visit_id,
            'name': name,
            'email': email,
            'purpose': purpose,
            'status': initial_status,
            'photo_url': photo_url,
            'employee_name': employee_name,
            'department': department,
            'visit_date': visit_date if visit_date else datetime.now().strftime('%Y-%m-%d'),
            'requires_employee_approval': requires_employee_approval
        }
        
        # Also set visitor_id in session for check-in page
        session['visitor_id'] = visitor_id
        session['last_registration_time'] = datetime.now().isoformat()

        # Send email to visitor
        email_success, email_message = send_email(email, name, profile_link)
        employee_notification_sent = False

        # ONLY send email notification if it's an employee meeting requiring approval
        if requires_employee_approval and employee_data and employee_data.get('email'):
            employee_email = employee_data.get('email')
            profile_url = request.url_root.rstrip("/") + url_for("employee_action", visitor_id=visitor_id)
            
            visitor_data_for_employee = {
                "name": name,
                "contact": email,
                "purpose": purpose,
                "duration": duration,
                "visit_date": visit_date if visit_date else datetime.now().strftime("%Y-%m-%d"),
                "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            emp_success, emp_message = send_employee_notification(
                employee_email, 
                employee_name, 
                visitor_data_for_employee, 
                profile_url
            )
            employee_notification_sent = emp_success
            
            # Update visit with notification status
            if emp_success:
                db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}").update({
                    "employee_notified": True,
                    "notification_sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                logger.info(f"Employee notification sent to {employee_email}")
            else:
                logger.error(f"Failed to send employee notification: {emp_message}")
        else:
            employee_notification_sent = False
            logger.info(
                f"No host notification sent (purpose: {purpose_type}, requires_approval: {requires_employee_approval})"
            )

        response_data = {
            "success": True,
            "message": "Registration complete." + (" Waiting for employee approval." if requires_employee_approval else ""),
            "redirect_url": "/check_in",
            "visitor_id": visitor_id,
            "visit_id": visit_id,
            "email_status": "success" if email_success else "failure",
            "employee_notified": employee_notification_sent,
            "photo_url": photo_url,
            "requires_employee_approval": requires_employee_approval,
            "current_status": initial_status
        }

        logger.info(f"--- NEW REGISTRATION COMPLETED SUCCESSFULLY FOR {name} ---")
        logger.info(
            f"Registration details: purpose={purpose}, employee_approval={requires_employee_approval}, status={initial_status}"
        )
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Unexpected error in finalize_registration: {e}")
        return jsonify({"success": False, "message": "Internal server error"}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
@app.route('/check_in')
def check_in():
    # Try multiple ways to get visitor_id
    visitor_id = session.get("visitor_id") or request.args.get("visitor_id")
    logger.info(f"Check-in page accessed for visitor: {visitor_id}")

    if not visitor_id:
        logger.warning("No visitor_id found in session or URL parameters")
        return redirect("/")

    if db_ref is None:
        logger.error("Database connection not available")
        return render_template("check_in.html", visitor=None, recent_visit=None)

    try:
        # Fetch visitor info
        visitor_data = db_ref.child(f"visitors/{visitor_id}").get()
        if not visitor_data:
            logger.error(f"Visitor {visitor_id} not found in database")
            return redirect("/verify")

        basic_info = visitor_data.get("basic_info", {})
        visits = visitor_data.get("visits", {})
        
        logger.info(f"Found {len(visits)} visits for visitor {visitor_id}")

        recent_visit = None
        latest_status = None
        latest_requires_approval = False
        latest_visit_approved = False
        latest_qr_email_sent = False

        if visits:
            # Get the most recent visit (works for both new and returning visitors)
            sorted_visits = sorted(visits.items(), key=lambda x: x[0], reverse=True)
            
            if sorted_visits:
                latest_visit_id, latest_visit_data = sorted_visits[0]
                logger.info(f"Latest visit ID: {latest_visit_id}, Purpose: {latest_visit_data.get('purpose')}")
                
                latest_status = latest_visit_data.get("status", "Registered")
                latest_requires_approval = latest_visit_data.get("requires_employee_approval", False)
                latest_visit_approved = latest_visit_data.get("visit_approved", False)
                latest_qr_email_sent = latest_visit_data.get("qr_email_sent", False)

                recent_visit = {
                    "purpose": latest_visit_data.get("purpose", "Not specified"),
                    "duration": latest_visit_data.get("duration", "Not specified"),
                    "visit_date": latest_visit_data.get("visit_date", "Unknown"),
                    "employee_name": latest_visit_data.get("employee_name", "N/A"),
                    "status": latest_status,
                    "employee_id": latest_visit_data.get("employee_id", None),
                    "visit_approved": latest_visit_approved,
                    "has_visited": latest_visit_data.get("has_visited", False),
                    "requires_employee_approval": latest_requires_approval,
                    "qr_email_sent": latest_qr_email_sent,
                }

        # Store visitor_id in session for future use
        session["visitor_id"] = visitor_id
        
        # Get email status from session or set default
        email_status = session.get("email_status", "unknown")
        email_message = session.get("email_message", "")

        # Never show QR on the web page; QR is delivered only via email from Admin.
        show_qr_on_page = False

        # Derive high-level visit state for template messaging
        status_lower = (latest_status or "").strip().lower() if latest_status else ""
        is_pending = status_lower in ("pending approval", "pending_approval") or (
            latest_requires_approval and not latest_visit_approved
        )
        is_rejected = status_lower == "rejected"
        has_qr_email = bool(latest_qr_email_sent)
        visitor_for_template = {"basic_info": basic_info} if basic_info else None

        logger.info(f"Rendering check-in page for {basic_info.get('name', 'Unknown')}")

        return render_template(
            "check_in.html",
            visitor=visitor_for_template if show_qr_on_page else None,
            basic_info=basic_info,
            email_status=email_status,
            email_message=email_message,
            recent_visit=recent_visit if show_qr_on_page else None,
            visitor_id=visitor_id,
            qr_image=None,
            details_sent_by_email=True,
            visit_status=latest_status,
            is_pending=is_pending,
            is_rejected=is_rejected,
            has_qr_email=has_qr_email,
            requires_employee_approval=latest_requires_approval,
        )

    except Exception as e:
        logger.error(f"Error retrieving visitor data: {e}")
        return render_template(
            "check_in.html",
            visitor=None,
            basic_info=None,
            recent_visit=None,
            visitor_id=None,
            qr_image=None,
            details_sent_by_email=True,
            email_status="error",
            email_message="Error loading visitor data",
            visit_status=None,
            is_pending=False,
            is_rejected=False,
            has_qr_email=False,
            requires_employee_approval=False,
        )

@app.route("/resend_qr_email", methods=["POST"])
def resend_qr_email():
    """Let returning user enter email to receive QR + visit details (e.g. when email was skipped)."""
    try:
        data = request.get_json() or request.form
        visitor_id = (data.get("visitor_id") or session.get("visitor_id") or "").strip()
        email = (data.get("email") or "").strip()
        if not visitor_id or not email:
            return jsonify({"success": False, "message": "Visitor ID and email are required."}), 400
        visitor_data = db_ref.child(f"visitors/{visitor_id}").get() if db_ref else None
        if not visitor_data:
            return jsonify({"success": False, "message": "Visitor not found."}), 404
        basic_info = visitor_data.get("basic_info", {})
        stored_email = (basic_info.get("contact") or basic_info.get("email") or "").strip().lower()
        if stored_email and email.lower() != stored_email:
            return jsonify({"success": False, "message": "Email does not match the registered visitor."}), 403
        profile_link = basic_info.get("profile_link") or (request.url_root.rstrip("/") + url_for("profile_page", visitor_id=visitor_id))
        visitor_name = basic_info.get("name", "Visitor")
        email_success, email_message = send_email(email, visitor_name, profile_link)
        if email_success:
            return jsonify({"success": True, "message": "QR and visit details sent to your email."})
        if "Email environment variables missing" in (email_message or ""):
            return jsonify({"success": False, "message": "Email service not configured. Your QR code is shown on this page—save or screenshot it."})
        return jsonify({"success": False, "message": email_message or "Email could not be sent."}), 400
    except Exception as e:
        logger.exception("resend_qr_email error")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/profile/<visitor_id>")
def profile_page(visitor_id):
    logger.info(f"Accessing profile page for: {visitor_id}")
    
    if db_ref is None:
        return "Internal Server Error: Database not connected.", 500
        
    visitor_data = db_ref.child(f"visitors/{visitor_id}").get()
    if not visitor_data:
        return "Profile not found", 404

    # Get basic info
    basic_info = visitor_data.get('basic_info', {})
    
    # Get visits history
    visits = visitor_data.get('visits', {})
    visits_list = []
    for visit_id, visit_data in visits.items():
        visits_list.append({
            'id': visit_id,
            'purpose': visit_data.get('purpose', 'N/A'),
            'employee_name': visit_data.get('employee_name', 'N/A'),
            'duration': visit_data.get('duration', 'N/A'),
            'visit_date': visit_data.get('visit_date', 'N/A'),
            'status': visit_data.get('status', 'N/A'),
            'visit_approved': visit_data.get('visit_approved', False),
            'check_in_time': visit_data.get('check_in_time', 'N/A'),
            'check_out_time': visit_data.get('check_out_time', 'N/A')
        })
    visits_list.sort(key=lambda v: v['id'], reverse=True)

    # Get transactions (if any)
    transactions = visitor_data.get('transactions', {})
    transactions_list = []
    for txn_id, txn_data in transactions.items():
        transactions_list.append({
            'id': txn_id,
            'check_in': txn_data.get('check_in_time', 'N/A'),
            'check_out': txn_data.get('check_out_time', 'N/A'),
            'duration': txn_data.get('duration_total', 'N/A')
        })

    logger.info(f"Profile page rendered for: {basic_info.get('name')}")
    
    return render_template(
        "profile_view.html",
        visitor=visitor_data,
        basic_info=basic_info,
        visitor_id=visitor_id,
        transactions=transactions_list,
        visits=visits_list,
        visit_count=len(visits_list),
        chatbot_url="https://chatbot-by3vbcpseur9ldw9ylnzpo.streamlit.app/"
    )
@app.route("/employee_action/<visitor_id>", methods=["GET"])
def employee_action(visitor_id):
    if not visitor_id:
        return render_template("error.html", message="Invalid visitor ID")

    if db_ref is None:
        return render_template("error.html", message="Database connection failed")

    try:
        visitor_data = db_ref.child(f"visitors/{visitor_id}").get()
        if not visitor_data:
            return render_template("error.html", message="Visitor not found")

        # Get basic info
        basic_info = visitor_data.get("basic_info", {})
        
        # Get the latest visit
        visits = visitor_data.get("visits", {})
        latest_visit_id, latest_visit = None, None
        if visits:
            sorted_visits = sorted(visits.items(), key=lambda x: x[0], reverse=True)
            latest_visit_id, latest_visit = sorted_visits[0]

        # Get photo
        photo_filename = basic_info.get("photo_filename")
        photo_url = None
        
        if photo_filename:
            clean_filename = os.path.basename(photo_filename)
            uploads_folder = "uploads_reg"
            photo_path = os.path.join(uploads_folder, clean_filename)
            
            if os.path.exists(photo_path):
                photo_url = f"/uploads_reg/{clean_filename}"

        # Extract details
        email = basic_info.get('contact', 'Not provided')
        purpose = latest_visit.get('purpose', 'Not specified') if latest_visit else 'Not specified'
        status = latest_visit.get('status', 'Unknown') if latest_visit else 'Unknown'
        visit_date = latest_visit.get('visit_date', 'Not scheduled') if latest_visit else 'Not scheduled'
        
        # Get employee actions history (renamed from previous_actions for clarity)
        employee_actions = latest_visit.get('employee_actions', []) if latest_visit else []
        
        # Get rejection reason if previously rejected
        rejection_reason = latest_visit.get('rejection_reason', '') if latest_visit else ''
        
        # Get reschedule details if previously rescheduled
        reschedule_date = latest_visit.get('new_visit_date', '') if latest_visit else ''
        reschedule_reason = latest_visit.get('reschedule_reason', '') if latest_visit else ''
        
        # Get last action details for display
        last_action = None
        last_action_by = None
        last_action_at = None
        if employee_actions:
            last_action_data = employee_actions[-1]  # Get most recent action
            last_action = last_action_data.get('action')
            last_action_by = last_action_data.get('by')
            last_action_at = last_action_data.get('timestamp')

        # Check if visit requires employee approval
        requires_approval = latest_visit.get('requires_employee_approval', False) if latest_visit else False

        return render_template("employee_action.html", 
                             visitor_id=visitor_id,
                             latest_visit_id=latest_visit_id,
                             photo_url=photo_url,
                             email=email,
                             purpose=purpose,
                             status=status,
                             visit_date=visit_date,
                             employee_actions=employee_actions,  # Changed from previous_actions
                             rejection_reason=rejection_reason,
                             reschedule_date=reschedule_date,
                             reschedule_reason=reschedule_reason,
                             last_action=last_action,
                             last_action_by=last_action_by,
                             last_action_at=last_action_at,
                             requires_employee_approval=requires_approval)

    except Exception as e:
        logger.error(f"Error in employee_action: {e}")
        return render_template("error.html", message="Something went wrong while fetching visitor data")

@app.route('/employee_action_approve/<visitor_id>', methods=['POST'])
def employee_action_approve(visitor_id):
    try:
        visitor_id = str(visitor_id or '').strip()
        if not _is_valid_visitor_id(visitor_id):
            return jsonify({'status': 'error', 'message': 'Invalid visitor ID'}), 400

        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No JSON data received'
            }), 400
            
        visit_id = str(data.get('visit_id') or '').strip()
        
        if not visit_id:
            return jsonify({
                'status': 'error',
                'message': 'Visit ID is required'
            }), 400
        
        visitor_ref = db.reference(f'visitors/{visitor_id}')
        visitor_snapshot = visitor_ref.get()
        if not visitor_snapshot:
            return jsonify({'status': 'error', 'message': 'Visitor not found'}), 404

        visit_ref = visitor_ref.child(f'visits/{visit_id}')
        visit_data = visit_ref.get()
        if not visit_data:
            return jsonify({'status': 'error', 'message': 'Visit not found'}), 404
        
        updates = {
            'status': 'approved',
            'visit_approved': True,
            'approved_at': datetime.utcnow().isoformat(),
            'last_updated': datetime.utcnow().isoformat()
        }
        
        visit_ref.update(updates)
        
        visitor_ref.update({
            'last_visit_status': 'approved',
            'last_updated': datetime.utcnow().isoformat()
        })
        
        return jsonify({
            'status': 'success',
            'message': 'Visit approved successfully'
        })
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error approving visit: {str(e)}'
        }), 500

@app.route('/employee_action_reject/<visitor_id>', methods=['POST'])
def employee_action_reject(visitor_id):
    try:
        visitor_id = str(visitor_id or '').strip()
        if not _is_valid_visitor_id(visitor_id):
            return jsonify({'status': 'error', 'message': 'Invalid visitor ID'}), 400

        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No JSON data received'
            }), 400
            
        visit_id = str(data.get('visit_id') or '').strip()
        rejection_reason = data.get('rejection_reason')
        
        if not visit_id:
            return jsonify({
                'status': 'error',
                'message': 'Visit ID is required'
            }), 400
        
        visitor_ref = db.reference(f'visitors/{visitor_id}')
        visitor_snapshot = visitor_ref.get()
        if not visitor_snapshot:
            return jsonify({'status': 'error', 'message': 'Visitor not found'}), 404

        visit_ref = visitor_ref.child(f'visits/{visit_id}')
        visit_data = visit_ref.get()
        if not visit_data:
            return jsonify({'status': 'error', 'message': 'Visit not found'}), 404

        updates = {
            'status': 'rejected',
            'rejection_reason': rejection_reason,
            'visit_approved': False,
            'rejected_at': datetime.utcnow().isoformat(),
            'last_updated': datetime.utcnow().isoformat()
        }

        visit_ref.update(updates)

        visitor_ref.update({
            'last_visit_status': 'rejected',
            'last_updated': datetime.utcnow().isoformat()
        })

        try:
            visitor_snapshot = visitor_snapshot or {}
            basic_info = visitor_snapshot.get("basic_info", {}) or {}
            visitor_email = basic_info.get("contact") or basic_info.get("email")
            visitor_name = basic_info.get("name", "Visitor")
            if visitor_email:
                subject = "Your visit request has been rejected"
                body_lines = [
                    f"Hello {visitor_name},",
                    "",
                    "Your visit request has been rejected by your host.",
                ]
                if rejection_reason:
                    body_lines.append(f"Reason: {rejection_reason}")
                body_lines.extend(
                    [
                        "",
                        "If you believe this is a mistake, please contact your host or reception.",
                    ]
                )
                body = "\n".join(body_lines)
                send_custom_email(visitor_email, subject, body)
        except Exception as mail_err:
            logger.error(f"Error sending visit rejection email: {mail_err}")

        return jsonify({
            'status': 'success',
            'message': 'Visit rejected successfully'
        })
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error rejecting visit: {str(e)}'
        }), 500

@app.route('/employee_action_reschedule/<visitor_id>', methods=['POST'])
def employee_action_reschedule(visitor_id):
    try:
        visitor_id = str(visitor_id or '').strip()
        if not _is_valid_visitor_id(visitor_id):
            return jsonify({'status': 'error', 'message': 'Invalid visitor ID'}), 400

        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'message': 'No JSON data received'
            }), 400
            
        visit_id = str(data.get('visit_id') or '').strip()
        new_visit_date = (data.get('new_visit_date') or '').strip()
        reschedule_reason = data.get('reschedule_reason')
        
        if not visit_id or not new_visit_date:
            return jsonify({
                'status': 'error',
                'message': 'Visit ID and new visit date are required'
            }), 400
        
        visitor_ref = db.reference(f'visitors/{visitor_id}')
        visitor_snapshot = visitor_ref.get()
        if not visitor_snapshot:
            return jsonify({'status': 'error', 'message': 'Visitor not found'}), 404

        visit_ref = visitor_ref.child(f'visits/{visit_id}')
        visit_data = visit_ref.get()
        if not visit_data:
            return jsonify({'status': 'error', 'message': 'Visit not found'}), 404
        
        updates = {
            'status': 'rescheduled',
            'visit_date': new_visit_date,
            'reschedule_reason': reschedule_reason,
            'rescheduled_at': datetime.utcnow().isoformat(),
            'last_updated': datetime.utcnow().isoformat()
        }
        
        visit_ref.update(updates)
        
        visitor_ref.update({
            'last_visit': datetime.utcnow().isoformat(),
            'last_updated': datetime.utcnow().isoformat()
        })
        
        return jsonify({
            'status': 'success',
            'message': 'Visit rescheduled successfully'
        })
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Error rescheduling visit: {str(e)}'
        }), 500


@app.route("/verify")
def verify_page():
    logger.info("Verify page accessed")
    # Returning flow: email step set expected_visitor_id; never reuse a stale visitor_id here.
    if session.get("expected_visitor_id"):
        session.pop("visitor_id", None)
    return render_template('verify.html')


@app.route("/verify_email", methods=["GET", "POST"])
def verify_email_page():
    """
    Email-first entry point for returning visitors.
    Step 1: Ask for email, look up matching visitor, store candidate visitor_id in session.
    Step 2: Redirect to standard face verification flow (/verify) which will be restricted to this visitor.
    """
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        if not email:
            return render_template("verify_email.html", error="Please enter your email address.")
        if db_ref is None:
            logger.error("Database not connected during verify_email_page")
            return render_template("verify_email.html", error="System error. Please try again later.")
        try:
            all_visitors = db_ref.child("visitors").get() or {}
        except Exception as e:
            logger.error(f"Error reading visitors in verify_email_page: {e}")
            return render_template("verify_email.html", error="Could not look up your email. Please try again.")

        matches = []
        for vid, vdata in all_visitors.items():
            bi = (vdata or {}).get("basic_info", {})
            if str(bi.get("contact", "")).strip().lower() == email.lower():
                matches.append((vid, bi))

        if not matches:
            logger.info(f"No visitor found for email {email} in verify_email_page")
            return render_template("verify_email.html", error="No visitor found with this email. Please register as a new visitor.", email=email)

        # If multiple matches, pick the most recently registered one by registered_at
        def _parse_registered_at(basic_info):
            ts = basic_info.get("registered_at")
            if not ts:
                return datetime.min
            try:
                return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return datetime.min

        chosen_id, chosen_basic = sorted(
            matches,
            key=lambda tup: _parse_registered_at(tup[1]),
            reverse=True,
        )[0]

        full_chosen = all_visitors.get(chosen_id) or {}
        if _visitor_basic_is_blacklisted(chosen_basic, full_chosen):
            logger.warning(f"verify_email_page: blacklisted visitor {chosen_id} attempted returning flow.")
            return render_template("verify_email.html", error=MSG_BLACKLISTED, email=email)
        if _visitor_has_active_check_in(full_chosen):
            logger.warning(f"verify_email_page: visitor {chosen_id} already checked in; blocked returning registration.")
            return render_template("verify_email.html", error=MSG_ACTIVE_CHECK_IN, email=email)

        # Drop any prior visitor_id so a failed face verify cannot still open /returning_visitor
        # with someone else's (or an outdated) session binding.
        session.pop("visitor_id", None)
        session["expected_visitor_id"] = chosen_id
        session["returning_email"] = email
        logger.info(f"verify_email_page matched email {email} to visitor {chosen_id}")
        # Proceed to standard face verification which will now be restricted to this visitor
        return redirect("/verify")

    return render_template("verify_email.html")


@app.route("/debug_session")
def debug_session():
    """Diagnostic: check if session has visitor_id (for returning visitor flow)."""
    return jsonify({
        "visitor_id": session.get("visitor_id"),
        "has_visitor_id": bool(session.get("visitor_id")),
        "hint": "If has_visitor_id is false after verify-face, session may not be persisting.",
    })
@app.route("/verify-face", methods=['POST'])
def verify_face():
    data = request.get_json()
    if not data or not isinstance(data, dict) or "image" not in data:
        return jsonify({"match": False, "message": "Missing or invalid request body (image required)"}), 400
    logger.info("Face verification request received")
    
    try:
        captured_base64 = data["image"].split(",")[1]
        np_img = np.frombuffer(base64.b64decode(captured_base64), np.uint8)
        cv2_img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        
        if cv2_img is None:
            logger.warning("Unable to decode image during verification")
            return jsonify({"match": False, "message": "Unable to process image"})
        
        # Get live embedding
        live_embedding = get_face_embedding(cv2_img)
        
        if live_embedding is None:
            logger.warning("No face detected during verification")
            return jsonify({"match": False, "message": "No face detected"})
        
        # Check embedding dimensions
        if len(live_embedding) != 128:
            logger.error(f"Invalid embedding dimension: {len(live_embedding)} (expected 128)")
            return jsonify({"match": False, "message": "Face detection failed"})
        
        # ---- Compare with either a specific expected visitor or all visitors ----
        expected_id = session.get("expected_visitor_id")
        matched_id, min_distance = None, float('inf')

        # Open verify (no email): lenient. Returning visitor (email matched): stricter to reduce false accepts.
        base_threshold = float(os.environ.get("VERIFICATION_THRESHOLD", "0.65"))
        if expected_id:
            THRESHOLD = float(
                os.environ.get("VERIFICATION_THRESHOLD_RETURNING", "0.52")
            )
        else:
            THRESHOLD = base_threshold
        TWIN_GAP = 0.08  # if two matches are within this, treat as ambiguous

        if expected_id:
            logger.info(f"Restricted verification to expected visitor_id={expected_id}")
            visitor_data = db_ref.child(f"visitors/{expected_id}").get() or {}
            basic_info = visitor_data.get("basic_info", {})
            if _visitor_has_active_check_in(visitor_data):
                return jsonify({
                    "match": False,
                    "redirect": None,
                    "message": MSG_ACTIVE_CHECK_IN,
                })
            expected_visitor_blacklisted = _visitor_basic_is_blacklisted(basic_info, visitor_data)
            emb_str = basic_info.get("embedding")
            if emb_str:
                try:
                    stored_emb = np.array([float(x) for x in emb_str.strip().split()])
                    if len(stored_emb) == len(live_embedding):
                        expected_dist = np.linalg.norm(live_embedding - stored_emb)
                        min_distance = expected_dist
                    else:
                        logger.warning(
                            f"Embedding dimension mismatch for expected visitor {expected_id}: "
                            f"stored={len(stored_emb)}, live={len(live_embedding)}"
                        )
                        expected_dist = float("inf")
                except Exception as e:
                    logger.error(f"Error processing embedding for expected visitor {expected_id}: {e}")
                    expected_dist = float("inf")
            else:
                logger.warning(f"No embedding stored for expected visitor {expected_id}")
                expected_dist = float("inf")

            # Twin-aware blacklist check: compare live face against all blacklisted visitors too.
            all_visitors = db_ref.child("visitors").get() or {}
            min_blacklisted_dist = float("inf")
            closest_blacklisted_id = None
            for vid, vdata in all_visitors.items():
                basic = (vdata or {}).get("basic_info", {}) or {}
                raw_bl = basic.get("blacklisted", vdata.get("blacklisted", "no"))
                is_bl = raw_bl is True or (
                    isinstance(raw_bl, str) and raw_bl.strip().lower() in ("yes", "true", "1")
                )
                if not is_bl:
                    continue
                emb_str_bl = basic.get("embedding")
                if not emb_str_bl:
                    continue
                try:
                    stored_bl = np.array([float(x) for x in emb_str_bl.strip().split()])
                    if len(stored_bl) != len(live_embedding):
                        continue
                    dist_bl = np.linalg.norm(live_embedding - stored_bl)
                    if dist_bl < min_blacklisted_dist:
                        min_blacklisted_dist = dist_bl
                        closest_blacklisted_id = vid
                except Exception as e:
                    logger.error(f"Error processing embedding for blacklisted visitor {vid}: {e}")
                    continue

            logger.info(
                f"Expected visitor distance={expected_dist:.4f}, "
                f"closest blacklisted distance={min_blacklisted_dist:.4f} (id={closest_blacklisted_id})"
            )

            if expected_dist <= THRESHOLD:
                if expected_visitor_blacklisted:
                    logger.warning(
                        f"Blacklisted visitor {expected_id} matched face in returning flow; denying."
                    )
                    return jsonify(
                        {
                            "match": False,
                            "redirect": None,
                            "message": MSG_BLACKLISTED,
                            "distance": round(float(expected_dist), 4),
                        }
                    )
                # If a blacklisted face is as close or closer than the expected visitor within a small margin,
                # treat the situation as ambiguous/unsafe and deny without revealing blacklist status.
                if (
                    closest_blacklisted_id is not None
                    and min_blacklisted_dist <= expected_dist + TWIN_GAP
                ):
                    logger.warning(
                        "Ambiguous match between expected visitor and a blacklisted visitor. "
                        "Denying returning registration for safety."
                    )
                    return jsonify(
                        {
                            "match": False,
                            "redirect": None,
                            "message": (
                                "We could not confidently verify your identity. "
                                "Please contact reception or register as a new visitor."
                            ),
                            "distance": round(float(expected_dist), 4),
                        }
                    )

                # Safe to treat as the expected (non-ambiguous) visitor
                matched_id = expected_id
                min_distance = expected_dist
            else:
                matched_id = None
                min_distance = expected_dist

        else:
            # No expected visitor from email: search all visitors and keep top matches for twin/blacklist handling.
            all_visitors = db_ref.child("visitors").get() or {}
            visitor_count = 0
            valid_embeddings = 0
            candidates = []  # list of dicts: {id, dist, is_blacklisted, name}

            logger.info(f"Total visitors in DB for verification: {len(all_visitors)}")

            for vid, vdata in all_visitors.items():
                visitor_count += 1
                basic_info = (vdata or {}).get("basic_info", {}) or {}
                emb_str = basic_info.get("embedding")
                if not emb_str:
                    continue

                try:
                    stored_emb = np.array([float(x) for x in emb_str.strip().split()])
                    if len(stored_emb) != len(live_embedding):
                        logger.warning(
                            f"Embedding dimension mismatch for visitor {vid}: "
                            f"stored={len(stored_emb)}, live={len(live_embedding)}"
                        )
                        continue

                    dist = np.linalg.norm(live_embedding - stored_emb)
                    valid_embeddings += 1

                    raw_bl = basic_info.get("blacklisted", vdata.get("blacklisted", "no"))
                    is_bl = raw_bl is True or (
                        isinstance(raw_bl, str) and raw_bl.strip().lower() in ("yes", "true", "1")
                    )
                    candidates.append(
                        {
                            "visitor_id": vid,
                            "distance": float(dist),
                            "is_blacklisted": is_bl,
                            "name": basic_info.get("name", "Unknown"),
                        }
                    )
                except Exception as e:
                    logger.error(f"Error processing embedding for visitor {vid}: {e}")
                    continue

            candidates.sort(key=lambda c: c["distance"])

            if candidates:
                best = candidates[0]
                min_distance = best["distance"]
                matched_id = best["visitor_id"]
                logger.info(
                    f"Verification summary: {visitor_count} visitors checked, "
                    f"{valid_embeddings} valid embeddings, best distance: {min_distance:.4f}"
                )
            else:
                logger.info(
                    f"Verification summary: {visitor_count} visitors checked, "
                    f"{valid_embeddings} valid embeddings, no candidates."
                )

            # Twin-aware blacklist behavior for the no-email path.
            if candidates and min_distance <= THRESHOLD:
                best = candidates[0]
                second = candidates[1] if len(candidates) > 1 else None

                if second is not None:
                    gap = abs(second["distance"] - best["distance"])
                else:
                    gap = float("inf")

                # Case A: best is blacklisted and clearly separated from second → treat as blacklisted.
                if best["is_blacklisted"] and (second is None or gap >= TWIN_GAP):
                    visitor_name = best["name"]
                    logger.warning(
                        f"Blacklisted visitor matched in verify_face (no-email): "
                        f"{visitor_name} (ID: {best['visitor_id']}), dist={best['distance']:.4f}"
                    )
                    return jsonify(
                        {
                            "match": False,
                            "redirect": None,
                            "message": MSG_BLACKLISTED,
                            "distance": round(float(best["distance"]), 4),
                            "visitor_name": visitor_name,
                        }
                    )

                # Case B: ambiguity between a blacklisted and non-blacklisted visitor (possible twins)
                if (
                    second is not None
                    and gap < TWIN_GAP
                    and (best["is_blacklisted"] != second["is_blacklisted"])
                ):
                    logger.warning(
                        "Ambiguous face match between blacklisted and non-blacklisted visitor "
                        f"(gap={gap:.4f}). Denying access and asking user to contact reception."
                    )
                    return jsonify(
                        {
                            "match": False,
                            "redirect": None,
                            "message": (
                                "We could not uniquely verify your identity. "
                                "Please contact reception or register as a new visitor."
                            ),
                            "distance": round(float(min_distance), 4),
                        }
                    )

        if min_distance <= THRESHOLD and matched_id:
            # Fetch visitor data for logging and final blacklist check (non-ambiguous cases).
            visitor_data = db_ref.child(f"visitors/{matched_id}").get() or {}
            basic_info = visitor_data.get("basic_info", {})
            visitor_name = basic_info.get("name", "Unknown")
            raw_bl = basic_info.get("blacklisted", visitor_data.get("blacklisted", "no"))
            is_blacklisted = _is_blacklisted_flag(raw_bl)

            if is_blacklisted:
                logger.warning(f"Blacklisted visitor matched in verify_face: {visitor_name} (ID: {matched_id})")
                return jsonify(
                    {
                        "match": False,
                        "redirect": None,
                        "message": MSG_BLACKLISTED,
                        "distance": round(float(min_distance), 4),
                        "visitor_name": visitor_name,
                    }
                )

            session["visitor_id"] = matched_id
            # Clear expected_visitor_id once we have a successful match
            if expected_id:
                session.pop("expected_visitor_id", None)
                session.pop("returning_email", None)
            logger.info(
                f"Face verified successfully for visitor: {visitor_name} (ID: {matched_id}), "
                f"distance: {min_distance:.4f}"
            )

            return jsonify(
                {
                    "match": True,
                    "redirect": "/returning_visitor",
                    "message": f"Welcome back {visitor_name}! Verification successful.",
                    "distance": round(float(min_distance), 4),
                    "visitor_name": visitor_name,
                }
            )
        else:
            logger.info(f"Face not verified, closest distance: {min_distance:.4f}")
            return jsonify({
                "match": False, 
                "redirect": "/register", 
                "message": f"Not recognized. Please register as a new visitor.",
                "distance": round(float(min_distance), 4)
            })
            
    except Exception as e:
        logger.exception(f"Error during face verification: {e}")
        return jsonify({
            "match": False, 
            "message": f"Verification error: {str(e)}"
        })



@app.route("/returning_visitor", methods=["GET", "POST"])
def returning_visitor():
    # Must complete face verify after verify_email; block stale visitor_id-only sessions.
    if session.get("expected_visitor_id"):
        return redirect("/verify")
    visitor_id = session.get("visitor_id")
    if not visitor_id:
        logger.warning("No visitor_id in session for returning_visitor, redirecting to verify")
        return redirect("/verify")

    if db_ref is None:
        logger.critical("DB_REF IS NONE. DATABASE IS NOT AVAILABLE.")
        return "Internal Server Error: Database not connected.", 500

    # --- Get visitor data ---
    visitor_data = db_ref.child(f"visitors/{visitor_id}").get()
    if not visitor_data:
        logger.error(f"Visitor data not found for ID: {visitor_id}")
        return redirect("/verify")

    # Block returning registration for blacklisted visitors
    basic = visitor_data.get("basic_info", {}) or {}
    if _visitor_basic_is_blacklisted(basic, visitor_data):
        logger.warning(f"Blacklisted visitor {visitor_id} attempted returning registration.")
        return render_template("error.html", message=MSG_BLACKLISTED)

    if _visitor_has_active_check_in(visitor_data):
        logger.warning(f"Visitor {visitor_id} already checked in; blocked returning registration form.")
        return render_template("error.html", message=MSG_ACTIVE_CHECK_IN)

    departments = collect_department_choices()
    allowed_depts = frozenset(departments)

    if request.method == "POST":
        purpose_type = request.form.get("purpose_type")  # 'department' or 'other'
        department_choice = (request.form.get("department") or "").strip()
        other_purpose = request.form.get("other_purpose")
        visit_date = request.form.get("visit_date")
        duration = request.form.get("duration", "Not sure")

        employee_name = None
        employee_email = None
        purpose = "Not specified"
        employee_id = None
        department = ""
        requires_employee_approval = False

        if purpose_type == "department" and department_choice:
            if department_choice not in allowed_depts:
                return render_template(
                    "returning_visitor.html",
                    visitor=visitor_data,
                    departments=departments,
                    error="Please select a valid department.",
                ), 400
            department = department_choice
            purpose = f"Visit to {department} department"
        elif purpose_type == "other":
            purpose = (other_purpose or "").strip() or "Other"

        initial_status = "Registered"
        is_approved = not requires_employee_approval

        # Update basic visitor info
        visitor_ref = db_ref.child(f"visitors/{visitor_id}")
        visitor_ref.child("basic_info").update({
            "last_visit": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        # --- Create a new visit record (aligned with new registration structure) ---
        visit_id = str(int(time() * 1000))
        visit_record = {
            "visit_id": visit_id,
            "purpose": purpose,
            "employee_id": employee_id,
            "employee_name": employee_name if employee_name else "N/A",
            "department": department,
            "duration": duration,
            "visit_date": visit_date if visit_date else datetime.now().strftime("%Y-%m-%d"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "check_in_time": None,
            "check_out_time": None,
            "time_spent": None,
            "status": initial_status,
            "visit_approved": is_approved,
            "has_visited": False,
            "requires_employee_approval": requires_employee_approval,
            "employee_notified": False,
            "employee_actions": [],
        }

        # Store new visit under "visits" node
        visitor_ref.child(f"visits/{visit_id}").set(visit_record)
        visitor_ref.update({"status": initial_status, "last_visit_id": visit_id})
        logger.info(f"New visit added under returning visitor {visitor_id}")

        # GENERATE QR CODE for returning visitor's new visit
        rv_visit_date = visit_date if visit_date else datetime.now().strftime('%Y-%m-%d')
        try:
            qr_token, qr_payload, qr_img, qr_fb = _create_qr_for_visit(
                visitor_id, visit_id, rv_visit_date
            )
            visitor_ref.child(f"visits/{visit_id}").update(qr_fb)
            logger.info(f"QR code generated for returning visitor visit {visit_id}")
        except Exception as qr_exc:
            logger.error(f"QR generation failed for returning visitor (non-fatal): {qr_exc}")

        session["current_visit_id"] = visit_id

        # --- Profile link handling ---
        profile_link = visitor_data.get("basic_info", {}).get("profile_link") or (
            request.url_root.rstrip("/") + url_for('profile_page', visitor_id=visitor_id)
        )
        visitor_ref.child("basic_info").update({"profile_link": profile_link})
        session["profile_link"] = profile_link

        # --- Send email to visitor ---
        visitor_email = visitor_data.get("basic_info", {}).get("contact")
        visitor_name = visitor_data.get("basic_info", {}).get("name")
        email_success, email_message = send_email(visitor_email, visitor_name, profile_link)
        # For returning users: do not show "Email Not Sent" when env vars are missing (silent skip)
        if not email_success and "Email environment variables missing" in (email_message or ""):
            session["email_status"] = "skipped"
            session["email_message"] = ""
        else:
            session["email_status"] = "success" if email_success else "failure"
            session["email_message"] = email_message
        logger.info(f"Returning visitor email: {'Success' if email_success else 'Failed'}")

        # --- Notify specific host (only when a named employee flow is used) ---
        employee_notification_sent = False
        if requires_employee_approval and employee_email and employee_name:
            profile_url = request.url_root.rstrip("/") + url_for("employee_action", visitor_id=visitor_id)
            
            # Prepare visitor data for employee notification email
            visitor_info_for_email = {
                "name": visitor_name,
                "contact": visitor_email,
                "purpose": purpose,
                "duration": duration,
                "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "visit_date": visit_date if visit_date else datetime.now().strftime("%Y-%m-%d")
            }
            
            emp_success, emp_message = send_employee_notification(
                employee_email,
                employee_name,
                visitor_info_for_email,
                profile_url
            )
            employee_notification_sent = emp_success
            if emp_success:
                visitor_ref.child(f"visits/{visit_id}").update({
                    "employee_notified": True,
                    "notification_sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            logger.info(f"Employee notification: {'Success' if emp_success else 'Failed'} - {emp_message}")

        logger.info(
            "Returning visitor registration completed for %s",
            visitor_data.get("basic_info", {}).get("name"),
        )
        return redirect("/check_in")  # Redirect to check-in page

    # --- Render form page for returning visitor ---
    logger.info(f"Returning visitor page rendered for: {visitor_data.get('basic_info', {}).get('name')}")
    return render_template("returning_visitor.html", visitor=visitor_data, departments=departments)



# File serving routes
@app.route('/uploads_reg/<filename>')
def serve_uploaded_photo(filename):
    return send_from_directory('uploads_reg', filename)

@app.route('/static/uploads_reg/<filename>')
def serve_static_uploaded_photo(filename):
    return send_from_directory('uploads_reg', filename)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return render_template('500.html'), 500

if __name__ == "__main__":
    logger.info("Starting Flask application...")
    app.run(host="0.0.0.0", port=5001, debug=True)
