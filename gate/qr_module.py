"""
QR Code Module for Workplace Intelligence Platform with Hybrid Face–QR Authentication
=============================================
Handles QR generation, validation, state management, twin detection,
and security alerts for the dual-authentication (QR + Face) gate system.

QR States:
    UNUSED           → Fresh QR, never scanned
    CHECKIN_USED     → Scanned once for check-in
    CHECKOUT_USED    → Scanned twice for checkout (terminal)
    ASSUMED_SCANNED  → Face-only check-in, QR treated as scanned
    INVALIDATED      → QR invalidated (stolen, face-override, etc.) (terminal)
"""

import secrets
import json
import logging
from datetime import datetime, timedelta
from io import BytesIO
import base64

try:
    import qrcode
except ImportError:
    qrcode = None

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
QR_MAX_SCANS = 2
QR_EXPIRY_HOURS = 36          # QR valid for visit_date + 36 h
QR_SCAN_COOLDOWN_SECONDS = 60 # Min gap between successive scans

# QR State Constants
QR_UNUSED = "UNUSED"
QR_CHECKIN_USED = "CHECKIN_USED"
QR_CHECKOUT_USED = "CHECKOUT_USED"
QR_ASSUMED_SCANNED = "ASSUMED_SCANNED"
QR_INVALIDATED = "INVALIDATED"

# Allowed state transitions
_VALID_TRANSITIONS = {
    # Allow invalidation even if a QR was never physically scanned.
    # This supports "stolen QR" / wrong-person mismatch workflows.
    QR_UNUSED:           [QR_CHECKIN_USED, QR_ASSUMED_SCANNED, QR_INVALIDATED],
    QR_CHECKIN_USED:     [QR_CHECKOUT_USED, QR_INVALIDATED],
    QR_ASSUMED_SCANNED:  [QR_CHECKOUT_USED, QR_INVALIDATED],
    QR_CHECKOUT_USED:    [],   # terminal
    QR_INVALIDATED:      [],   # terminal
}


# ──────────────────────────────────────────────
# QR Generation
# ──────────────────────────────────────────────

def generate_qr_token():
    """Generate a cryptographically-secure 32-byte URL-safe token."""
    return secrets.token_urlsafe(32)


def generate_qr_payload(visitor_id, visit_id, visit_date, token):
    """
    Build the compact JSON payload embedded inside the QR code.

    Keys are kept short to minimise QR complexity:
        v = visitor_id,  i = visit_id,  k = token,  e = expiry
    """
    try:
        date_obj = datetime.strptime(str(visit_date), "%Y-%m-%d")
        expiry = date_obj + timedelta(hours=QR_EXPIRY_HOURS)
    except (ValueError, TypeError):
        expiry = datetime.now() + timedelta(hours=QR_EXPIRY_HOURS)

    payload = {
        "v": str(visitor_id),
        "i": str(visit_id),
        "k": str(token),
        "e": expiry.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return json.dumps(payload, separators=(",", ":"))


def generate_qr_image_base64(payload_string):
    """Return the QR code as a ``data:image/png;base64,…`` string."""
    if qrcode is None:
        logger.error("qrcode library is not installed – cannot generate QR image")
        return None
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
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


def create_qr_for_visit(visitor_id, visit_id, visit_date, token=None):
    """
    One-call helper: generate everything needed for a visit's QR.

    If token is provided (e.g. for demo), it is used; otherwise a random token is generated.

    Returns
    -------
    tuple (token, payload_string, image_base64, firebase_data_dict)
    """
    if token is None:
        token = generate_qr_token()
    payload_string = generate_qr_payload(visitor_id, visit_id, visit_date, token)
    image_base64 = generate_qr_image_base64(payload_string)

    try:
        date_obj = datetime.strptime(str(visit_date), "%Y-%m-%d")
        expiry = date_obj + timedelta(hours=QR_EXPIRY_HOURS)
    except (ValueError, TypeError):
        expiry = datetime.now() + timedelta(hours=QR_EXPIRY_HOURS)

    firebase_data = {
        "qr_token": token,
        "qr_payload": payload_string,
        "qr_expires_at": expiry.strftime("%Y-%m-%d %H:%M:%S"),
        "qr_max_scans": QR_MAX_SCANS,
        "qr_created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "qr_state": {
            "status": QR_UNUSED,
            "scan_count": 0,
            "checkin_scan_time": None,
            "checkout_scan_time": None,
            "auth_method": None,
            "invalidated_at": None,
            "invalidated_reason": None,
        },
    }

    return token, payload_string, image_base64, firebase_data


# ──────────────────────────────────────────────
# QR Parsing & Validation
# ──────────────────────────────────────────────

def parse_qr_payload(qr_string):
    """
    Parse the raw QR string into a dict.

    Returns (data_dict | None, error_message | None)
    """
    if not qr_string or not isinstance(qr_string, str):
        return None, "Empty or invalid QR data"
    try:
        data = json.loads(qr_string)
        required = {"v", "i", "k", "e"}
        if not required.issubset(data.keys()):
            return None, "Invalid QR format – missing required fields"
        return data, None
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"Cannot decode QR: {exc}"


def validate_qr_token(qr_data, db_ref):
    """
    Validate a parsed QR payload against Firebase.

    Returns
    -------
    tuple (is_valid, visitor_id, visit_id, visit_data, error_msg)
    """
    if not qr_data:
        return False, None, None, None, "No QR data provided"

    visitor_id = str(qr_data.get("v") or "").strip()
    visit_id = str(qr_data.get("i") or "").strip()
    token = str(qr_data.get("k") or "").strip()
    expiry_str = str(qr_data.get("e") or "").strip()

    if not all([visitor_id, visit_id, token, expiry_str]):
        return False, None, None, None, "Incomplete QR data"

    # ── Expiry check ──
    try:
        expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d %H:%M:%S")
        if datetime.now() > expiry_dt:
            return False, visitor_id, visit_id, None, "QR code has expired"
    except ValueError:
        return False, None, None, None, "Invalid expiry format in QR"

    # ── Firebase lookup ──
    try:
        visit_data = db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}").get()
        if not visit_data:
            return False, visitor_id, visit_id, None, "Visit record not found"

        stored_token = visit_data.get("qr_token")
        if not stored_token:
            return False, visitor_id, visit_id, None, "No QR token stored for this visit"

        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(str(token), str(stored_token)):
            return False, visitor_id, visit_id, None, "QR token mismatch – possible forgery"

        # ── State checks ──
        qr_state = visit_data.get("qr_state", {})
        status = qr_state.get("status", QR_UNUSED)
        scan_count = qr_state.get("scan_count", 0)

        if status == QR_INVALIDATED:
            return False, visitor_id, visit_id, visit_data, "QR code has been invalidated"

        if status == QR_CHECKOUT_USED:
            return False, visitor_id, visit_id, visit_data, "QR already fully used (checked out)"

        if scan_count >= QR_MAX_SCANS:
            return False, visitor_id, visit_id, visit_data, f"Scan limit reached ({QR_MAX_SCANS} scans max)"

        # ── Cooldown check ──
        last_scan = qr_state.get("checkin_scan_time") or qr_state.get("checkout_scan_time")
        if last_scan:
            try:
                elapsed = (datetime.now() - datetime.strptime(last_scan, "%Y-%m-%d %H:%M:%S")).total_seconds()
                if elapsed < QR_SCAN_COOLDOWN_SECONDS:
                    wait = int(QR_SCAN_COOLDOWN_SECONDS - elapsed)
                    return False, visitor_id, visit_id, visit_data, f"Cooldown active – wait {wait}s before scanning again"
            except ValueError:
                pass

        return True, visitor_id, visit_id, visit_data, None

    except Exception as exc:
        logger.error(f"QR validation DB error: {exc}")
        return False, visitor_id, visit_id, None, "Database error during QR validation"


# ──────────────────────────────────────────────
# QR State Management
# ──────────────────────────────────────────────

def get_qr_state(visitor_id, visit_id, db_ref):
    """Fetch current QR state dict from Firebase."""
    try:
        state = db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}/qr_state").get()
        return state or {"status": QR_UNUSED, "scan_count": 0}
    except Exception as exc:
        logger.error(f"Error fetching QR state: {exc}")
        return {"status": QR_UNUSED, "scan_count": 0}


def update_qr_state(visitor_id, visit_id, new_status, db_ref,
                     auth_method=None, reason=None):
    """
    Transition QR to *new_status* with validation.

    Returns (success: bool, error_msg: str | None)
    """
    try:
        visit_ref = db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}")
        if not visit_ref.get():
            msg = f"Visit {visit_id} not found for visitor {visitor_id}"
            logger.warning(msg)
            return False, msg
        ref = visit_ref.child("qr_state")
        current = ref.get() or {}
        cur_status = current.get("status", QR_UNUSED)

        allowed = _VALID_TRANSITIONS.get(cur_status, [])
        if new_status not in allowed:
            msg = f"Invalid QR transition {cur_status} → {new_status}"
            logger.warning(msg)
            return False, msg

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        scan_count = current.get("scan_count", 0)

        update = {"status": new_status, "scan_count": scan_count + 1}

        if auth_method:
            update["auth_method"] = auth_method

        if new_status == QR_CHECKIN_USED:
            update["checkin_scan_time"] = now_str
        elif new_status == QR_CHECKOUT_USED:
            update["checkout_scan_time"] = now_str
        elif new_status == QR_ASSUMED_SCANNED:
            update["checkin_scan_time"] = now_str
            update["auth_method"] = "face_only"
        elif new_status == QR_INVALIDATED:
            update["invalidated_at"] = now_str
            update["invalidated_reason"] = reason or "Unknown"

        ref.update(update)
        logger.info(f"QR state → {new_status} for visitor={visitor_id} visit={visit_id}")
        return True, None

    except Exception as exc:
        logger.error(f"Error updating QR state: {exc}")
        return False, str(exc)


def invalidate_qr(visitor_id, visit_id, reason, db_ref):
    """Short-hand: force-invalidate a QR (stolen, face-override, etc.)."""
    return update_qr_state(visitor_id, visit_id, QR_INVALIDATED, db_ref, reason=reason)


# ──────────────────────────────────────────────
# Scan & Security Logging
# ──────────────────────────────────────────────

def log_qr_scan(visitor_id, visit_id, scan_type, db_ref, **extra):
    """
    Persist a QR scan event (success or failure) under the visit.

    Parameters
    ----------
    scan_type : str   e.g. "checkin", "checkout", "rejected", "face_only"
    extra     : dict  any additional fields (ip, face_matched, etc.)
    """
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        key = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        entry = {
            "scan_type": scan_type,
            "timestamp": now_str,
            "visitor_id": str(visitor_id),
            "visit_id": str(visit_id),
        }
        entry.update(extra)
        db_ref.child(f"visitors/{visitor_id}/visits/{visit_id}/qr_scan_log/{key}").set(entry)
        return True
    except Exception as exc:
        logger.error(f"Error logging QR scan: {exc}")
        return False


def log_security_alert(alert_type, db_ref, **fields):
    """
    Write a top-level security alert (visible in admin dashboard).

    alert_type examples: QR_FACE_MISMATCH, QR_STOLEN, TWIN_DETECTED
    """
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        key = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        entry = {"alert_type": alert_type, "timestamp": now_str}
        entry.update(fields)
        db_ref.child(f"security_alerts/{key}").set(entry)
        logger.warning(f"SECURITY ALERT: {alert_type} | {fields}")
        return True
    except Exception as exc:
        logger.error(f"Error logging security alert: {exc}")
        return False


# ──────────────────────────────────────────────
# Twin / Multi-Match Detection
# ──────────────────────────────────────────────

def find_all_face_matches(live_embedding, all_visitors, threshold=0.6):
    """
    Compare *live_embedding* against every stored visitor embedding.

    Returns a **sorted** list of dicts (closest first):
        [{"visitor_id", "distance", "name", "blacklisted"}, …]
    """
    import numpy as np

    live_flat = np.asarray(live_embedding).flatten()
    if live_flat.size != 128:
        return []

    matches = []
    for vid, vdata in all_visitors.items():
        if not isinstance(vdata, dict):
            continue
        basic = vdata.get("basic_info", {})
        emb_str = basic.get("embedding")
        if not emb_str:
            continue
        try:
            stored = np.array([float(x) for x in emb_str.strip().split()])
            if stored.size != 128:
                continue
            dist = float(np.linalg.norm(live_flat - stored))
            if dist <= threshold:
                matches.append({
                    "visitor_id": vid,
                    "distance": dist,
                    "name": basic.get("name", "Unknown"),
                    "blacklisted": str(basic.get("blacklisted", "no")).lower() in ("yes", "true", "1"),
                })
        except Exception:
            continue

    matches.sort(key=lambda m: m["distance"])
    return matches


def detect_twin(matches, strong_threshold=0.45):
    """
    Heuristic twin detector.

    Returns (is_twin: bool, ambiguous_matches: list)

    A "twin" scenario is flagged when:
      • 2+ matches exist
      • the top match is NOT a very strong match (distance > strong_threshold)
      • the gap between #1 and #2 is small (< 0.08)
    """
    if len(matches) < 2:
        return False, []

    top = matches[0]
    runner = matches[1]

    gap = abs(top["distance"] - runner["distance"])
    if top["distance"] > strong_threshold and gap < 0.08:
        return True, matches[:2]

    return False, []

