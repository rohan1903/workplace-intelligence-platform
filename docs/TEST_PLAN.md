# End-to-End Test Plan

Complete test plan for the Workplace Intelligence Platform, covering happy paths and all edge cases. Follow the [Setup Guide](SETUP_GUIDE.md) first.

---

## Pre-Flight Checklist

Before running any tests, verify:

- [ ] All 3 apps start without errors (registration:5001, admin:5000, gate:5002)
- [ ] All apps show "Firebase initialized successfully"
- [ ] Registration and gate apps show "Dlib models loaded"
- [ ] `.env` and `firebase_credentials.json` exist in `registration/`, `admin/`, `gate/`
- [ ] Webcam/camera access granted in browser
- [ ] At least one employee and one meeting room in Firebase (`python seed_firebase_data.py`)

**Clean slate (optional):** Run `python clear_firebase_visitors.py` to delete all visitor data before testing.

---

## Phase 1 -- Happy Path (Baseline)

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 1.1 | New visitor registration (no host approval) | Go to http://localhost:5001, register with purpose "Other", valid email, date, and face photo. | Success message; redirect to `/check_in`; visit created under `visitors/{id}/visits/{visit_id}` in Firebase. |
| 1.2 | Check-in page after registration | Observe the `/check_in` page after redirect. | No QR shown on page. Message reflects registration state. QR is delivered only via email. |
| 1.3 | Host/employee approval | Register with purpose "Meet employee", select an employee. Employee receives email with action link. Open the link and approve. | Visit status becomes "Approved"; `qr_email_sent=true`; visitor receives QR/check-in email. |
| 1.4 | Gate check-in | At http://localhost:5002 (hybrid mode), scan QR code + show face. | Access granted; visit status -> `checked_in`; QR state -> `CHECKIN_USED`. |
| 1.5 | Gate check-out | Same visitor scans QR + shows face at gate. | Access granted; status -> `checked_out`; QR state -> `CHECKOUT_USED`; feedback email sent. |

---

## Phase 2 -- Rejection Flows

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 2.1 | Admin/employee rejects visit | Register with "Meet employee"; from the employee action link, reject the visit. | Visit status becomes `Rejected`. Visitor receives rejection email. |
| 2.2 | Check-in page when rejected | Open `/check_in?visitor_id={id}` after rejection. | Page shows "Your visit has been rejected" -- does NOT claim check-in details were emailed. |
| 2.3 | Rejected visitor at gate | Attempt to use that visit's QR at the gate. | Gate denies with message like "This visit has been rejected." |

---

## Phase 3 -- Blacklist Behavior

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 3.1 | Blacklist a visitor | Register a visitor, then blacklist them in the admin dashboard (http://localhost:5000). | Visitor's `basic_info.blacklisted` set to `yes`; visitor receives blacklist email notification. |
| 3.2 | Blacklisted visitor at gate | Try to use the blacklisted visitor's QR + face at gate. | Gate denies with blacklist message; QR invalidated. |
| 3.3 | Blacklisted visitor tries new registration | Blacklisted visitor enters their email in `/verify_email` (returning flow) and completes face verification. | Registration is **blocked** (HTTP 403). No new visit created. Visitor receives email stating they are blacklisted. |
| 3.4 | New registration with blacklisted email | Attempt new registration using an email that belongs to a blacklisted record. | Registration blocked. Clear error message displayed. |

---

## Phase 4 -- Returning Visitors & Twins

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 4.1 | Returning visitor (email-first flow) | Register once as new visitor. Then go to "Returning Visitor Verification" (`/verify_email`), enter the same email, complete face verification. | System matches by email, verifies face; redirects to `/returning_visitor` then `/check_in`. |
| 4.2 | Twin A uses Twin B's email | Create two visitors with similar faces but different emails. Twin A enters Twin B's email, then does face verification. | Face comparison against B's embedding fails; returning flow rejected with "face does not match this account". |
| 4.3 | Correct twin returning | Same setup; Twin A enters A's own email and passes face verification. | Flow succeeds; new visit created under A's visitor_id. |

---

## Phase 5 -- QR / Face Mismatch & Stolen QR

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 5.1 | Right face, wrong QR | At gate, present Visitor A's face with Visitor B's valid QR. | Gate denies; QR invalidated; security alert `QR_FACE_MISMATCH` logged. |
| 5.2 | Right QR, wrong face | Present Visitor B's face with Visitor A's valid QR. | Same as 5.1: denial + QR invalidation + alert. |
| 5.3 | Invalid / expired QR | Use an old or tampered QR payload at gate. | Gate denies with "invalid QR" message; visit status not incorrectly modified. |
| 5.4 | Stolen QR detection | Check in with QR + face. At checkout, use face only (no QR). | Checkout succeeds, but QR invalidated with "possibly stolen" reason; security alert `QR_POSSIBLY_STOLEN` logged. |

---

## Phase 6 -- Auth Modes

Test each mode by changing `AUTH_MODE` in `gate/.env` and restarting the gate app.

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 6.1 | `AUTH_MODE=hybrid` (default) | Run normal QR + face arrival and departure. | Both QR and face required; mismatch invalidates QR and logs alerts. |
| 6.2 | `AUTH_MODE=face_only` | Restart gate with face_only; run arrival/checkout with face only. | Check-in/out works with face only; QR state machine not used. |
| 6.3 | `AUTH_MODE=qr_only` | Restart gate with qr_only; run arrival/checkout with QR only. | Check-in/out works with QR only; face ignored. |

---

## Phase 7 -- QR Usage Limits & Email Notifications

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 7.1 | Double check-in | After checking in, attempt to check in again with the same QR + face. | Gate denies: "You are already checked in." QR remains `CHECKIN_USED`. |
| 7.2 | Double check-out | After checking out, attempt to check out again. | Gate denies: "You are already checked out." QR is already `CHECKOUT_USED`. |
| 7.3 | QR scanned more than twice | Use the same QR for a third scan after check-in and check-out. | Gate denies: "Scan limit reached" or "QR already fully used." |
| 7.4 | Rejection email | After a host/admin rejects a visit, check the visitor's email. | Visitor receives email stating the visit was rejected (with optional reason). |
| 7.5 | Blacklist email | After admin blacklists a visitor, check that visitor's email. | Visitor receives email stating they have been blacklisted. |
| 7.6 | Feedback email | After checkout (or exceeded duration), check the visitor's email. | Visitor receives a feedback email with a link to the feedback form. |
| 7.7 | Feedback form validation | Open `/feedback_form` without a `visitor_id` parameter, or with an invalid one. | Returns 400 (missing) or 404 (invalid), not an error page. |

---

## Phase 8 -- Twin + Blacklist (Identity Ambiguity)

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 8.1 | Blacklisted twin uses non-blacklisted twin's email | Twin A (blacklisted) enters Twin B's email, then completes face verification. | System compares live face to B's embedding and all blacklisted embeddings; if ambiguous, verification **denied** with neutral message ("We could not confidently verify your identity"). A cannot enter as B. |
| 8.2 | Non-blacklisted twin, no email, ambiguous match | Twin B (not blacklisted) goes to `/verify` without email; face matches both A (blacklisted) and B. | System detects twin ambiguity; returns neutral message ("We could not uniquely verify your identity"), does NOT say "You are blacklisted." |

---

## Phase 9 -- Admin Dashboard

Test at http://localhost:5000.

| ID | Scenario | Steps | Expected Outcome |
|----|----------|-------|------------------|
| 9.1 | Visitor list | View the main dashboard. | All registered visitors displayed with name, email, status, photo. |
| 9.2 | Visitor details | Click on a visitor. | Full visitor profile shown: visits, QR states, check-in/out times. |
| 9.3 | Blacklist toggle | Blacklist a visitor, then un-blacklist them. | Status toggles correctly; email notifications sent for each action. |
| 9.4 | Analytics | View the analytics dashboard. | Charts display: purpose distribution, status overview, hourly trends. |
| 9.5 | Meeting rooms | View / add / edit / delete meeting rooms. | CRUD operations work; rooms appear in registration dropdown. |
| 9.6 | Employee management | View / add employees. | Employees appear in registration dropdown for "Meet employee" purpose. |

---

## Firebase Data Verification

After running tests, verify these paths in the Firebase Console:

```
visitors/{visitor_id}/
  basic_info/
    name, contact, embedding, photo_url, blacklisted
  visits/{visit_id}/
    purpose, status, check_in_time, check_out_time, time_spent
    qr_state/
      status (UNUSED -> CHECKIN_USED -> CHECKOUT_USED or INVALIDATED)
      scan_count

research_protocol_events/
  {event_id}/
    event, auth_mode, visitor_id, timestamp

security_alerts/
  {alert_id}/
    alert_type (QR_FACE_MISMATCH, QR_POSSIBLY_STOLEN, TWIN_DETECTED)
    message, timestamp
```

---

## Performance Benchmarks

| Metric | Target |
|--------|--------|
| Registration (form submit to QR generation) | < 5 seconds |
| Face recognition (image capture to match result) | < 3 seconds |
| Gate check-in (scan to access granted) | < 5 seconds |
| Gate check-out (scan to checkout complete) | < 5 seconds |

---

## Test Results Template

Copy this table and fill it in after testing:

```
# Test Results - [Date] - [Tester Name]

## Environment
- Python Version:
- OS:
- Firebase Project:
- AUTH_MODE:

## Results
| Phase | ID  | Scenario                  | Pass/Fail | Notes |
|-------|-----|---------------------------|-----------|-------|
| 1     | 1.1 | New visitor registration   |           |       |
| 1     | 1.2 | Check-in page             |           |       |
| 1     | 1.3 | Host approval             |           |       |
| 1     | 1.4 | Gate check-in             |           |       |
| 1     | 1.5 | Gate check-out            |           |       |
| 2     | 2.1 | Admin rejects visit       |           |       |
| 2     | 2.2 | Check-in page rejected    |           |       |
| 2     | 2.3 | Rejected at gate          |           |       |
| 3     | 3.1 | Blacklist a visitor       |           |       |
| 3     | 3.2 | Blacklisted at gate       |           |       |
| 3     | 3.3 | Blacklisted re-registers  |           |       |
| 3     | 3.4 | Blacklisted email         |           |       |
| 4     | 4.1 | Returning visitor         |           |       |
| 4     | 4.2 | Twin A uses Twin B email  |           |       |
| 4     | 4.3 | Correct twin returning    |           |       |
| 5     | 5.1 | Right face, wrong QR      |           |       |
| 5     | 5.2 | Right QR, wrong face      |           |       |
| 5     | 5.3 | Invalid QR                |           |       |
| 5     | 5.4 | Stolen QR detection       |           |       |
| 6     | 6.1 | Hybrid mode               |           |       |
| 6     | 6.2 | Face-only mode            |           |       |
| 6     | 6.3 | QR-only mode              |           |       |
| 7     | 7.1 | Double check-in           |           |       |
| 7     | 7.2 | Double check-out          |           |       |
| 7     | 7.3 | QR 3rd scan               |           |       |
| 7     | 7.4 | Rejection email           |           |       |
| 7     | 7.5 | Blacklist email           |           |       |
| 7     | 7.6 | Feedback email            |           |       |
| 7     | 7.7 | Feedback form validation  |           |       |
| 8     | 8.1 | Blacklisted twin          |           |       |
| 8     | 8.2 | Ambiguous twin            |           |       |
| 9     | 9.1 | Visitor list              |           |       |
| 9     | 9.2 | Visitor details           |           |       |
| 9     | 9.3 | Blacklist toggle          |           |       |
| 9     | 9.4 | Analytics                 |           |       |
| 9     | 9.5 | Meeting rooms             |           |       |
| 9     | 9.6 | Employee management       |           |       |

## Summary
- Total Tests:
- Passed:
- Failed:
- Issues Found:
```
