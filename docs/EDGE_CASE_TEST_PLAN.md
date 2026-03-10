# Edge-Case Test Plan – Hybrid Face–QR Visitor Management

This document lists focused scenarios to validate security and correctness beyond the happy path.  
Use it together with `TESTING_GUIDE.md`.

---

## Phase 0 – Setup & Environment

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 0.1 | Apps running | Start `Register_App/app.py` (5001), `Admin/app.py` (5000), `Webcam/app.py` (5002). | All three start without errors and respond on their ports. |
| 0.2 | Clean Firebase visitors | From project root run `python clear_firebase_visitors.py`. | “No visitors in Firebase” or “Deleted N visitors”. |
| 0.3 | Credentials & env | Verify `.env` and `firebase_credentials.json` exist in `Register_App/`, `Admin/`, `Webcam/`. | All present; no startup errors about missing credentials. |

---

## Phase 1 – Happy Path (Baseline)

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 1.1 | New visitor registration (no host approval) | In `http://localhost:5001`, register with purpose “Other”, valid email, date, and face. | JSON success; redirect to `/check_in`; visit created under `visitors/{id}/visits/{visit_id}`. |
| 1.2 | Check-in page after registration | After redirect, observe `/check_in`. | No QR shown. Message reflects registration state (e.g. “Registration complete” or “pending approval”) based on visit status. |
| 1.3 | Host/employee approval (if applicable) | For a “Meet employee” purpose, approve in Admin/employee UI, then trigger “send QR/check-in email”. | Visit status becomes Approved; `qr_email_sent=true` written on the visit; visitor receives QR/check-in email. |
| 1.4 | Gate check-in | At `http://localhost:5002` (hybrid mode), scan QR + show face. | Access granted; visit status → `checked_in`; QR state transitions to `CHECKIN_USED`. |
| 1.5 | Gate check-out | Same visitor uses QR + face (or valid checkout flow) at gate. | Access granted; status → `checked_out`; QR state → `CHECKOUT_USED`. |

---

## Phase 2 – Rejection & Check-in UX

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 2.1 | Admin rejects visit | Register with “Meet employee”; from Admin/employee view, reject the visit. | Visit status becomes `Rejected`. |
| 2.2 | Check-in page when rejected | Open `/check_in?visitor_id={id}` after rejection. | Page shows “Your visit has been rejected” (or equivalent); it does **not** claim that check-in details were emailed. |
| 2.3 | Rejected at gate | Attempt to use that visit’s QR at the gate. | Gate returns `status=denied` and message like “This visit has been rejected.” |

---

## Phase 3 – Blacklist Behavior

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 3.1 | Blacklisted visitor blocked at gate | Register visitor; blacklist them in Admin; try to use their QR + face at gate. | Gate denies with blacklist message; QR is invalidated according to protocol logic. |
| 3.2 | No new QR for blacklisted visitor | With visitor `basic_info.blacklisted='yes'`, attempt new registration as returning visitor or email-based returning flow. | Returning registration is blocked with a clear error; no new visits with QR are created. |
| 3.3 | New registration for blacklisted email | If a visitor email already belongs to a blacklisted record, attempt a new registration using the same email. | Visit is created with status reflecting blacklist (e.g. `Blacklisted`), QR generation is skipped, and gate still denies access. |

---

## Phase 4 – Returning Visitors & Twins (Email-First + Face)

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 4.1 | Returning visitor (email-first flow) | Use `New Visitor` once; then use `Returning Visitor Verification` (`/verify_email`), enter the same email, then run face verification. | System selects the correct visitor by email, then verifies face; on success, redirects to `old_register` and then `/check_in`. |
| 4.2 | Twin A at kiosk, Twin B email | Create two visitors with similar faces but different emails. For returning flow, have Twin A at kiosk enter **Twin B’s** email, then run face verification. | Face comparison against B’s embedding fails; returning flow is rejected with “face does not match this account”; no email is sent to B. |
| 4.3 | Correct twin returning | With same setup, Twin A enters A’s email and passes face verification. | Flow succeeds; new visit created under A’s `visitor_id`; QR/check-in email is sent to A’s email only. |
| 4.4 | Direct `/verify` (legacy face-only) | Optionally exercise old `/verify` endpoint if still exposed. | Behavior matches legacy docs; recommend using `/verify_email` as primary returning path. |

---

## Phase 5 – QR / Face Mismatch

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 5.1 | Right face, wrong QR | At gate, present Visitor A’s face with Visitor B’s valid QR. | Gate denies; QR is invalidated; a security alert (e.g. `QR_FACE_MISMATCH`) is logged. |
| 5.2 | Right QR, wrong face | Present Visitor B’s face with Visitor A’s valid QR. | Same as 5.1: denial + QR invalidation + alert. |
| 5.3 | Invalid or expired QR | Use an old or tampered QR payload at the gate. | Gate denies with an “invalid QR” style message; visit status is not incorrectly modified. |

---

## Phase 6 – Spoof & Reclaim-by-Email

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 6.1 | Spoof registration with photo/mask | Register using a printed photo or mask of Person X and some email `x@example.com`. | Visitor record is created; embedding corresponds to the spoof image. |
| 6.2 | Real X re-registers with same email | Later, the real Person X registers as a new visitor using `x@example.com`. | System finds the existing visitor by email, reuses that `visitor_id`, updates `basic_info.embedding`/photo with the real face, and creates a new visit. |
| 6.3 | Returning + gate after reclaim | After 6.2, use returning flow and gate with real X. | Returning flow and gate work for real X; the spoof embedding is effectively overwritten. |

---

## Phase 7 – Auth Modes (Webcam AUTH_MODE)

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 7.1 | `AUTH_MODE=hybrid` | Set `AUTH_MODE=hybrid` in `Webcam/.env`, restart gate; run normal QR+face arrival and departure. | Both QR and face are required; mismatch invalidates QR and logs alerts. |
| 7.2 | `AUTH_MODE=face_only` | Set `AUTH_MODE=face_only`; restart gate; run arrival/checkout with face only. | Check-in/out works with face only; QR state machine is not used. |
| 7.3 | `AUTH_MODE=qr_only` | Set `AUTH_MODE=qr_only`; restart gate; run arrival/checkout with QR only. | Check-in/out works with QR only; face is ignored. |

---

## Phase 8 – Stolen QR / Face-Only Checkout

| Case ID | Scenario | Steps | Expected Outcome |
|--------|----------|-------|------------------|
| 8.1 | Stolen QR detection on checkout | In hybrid mode, check in with QR+face. At checkout, use face-only (no QR). | Checkout succeeds, but QR is invalidated with a “possibly stolen” reason; a corresponding security alert is logged. |

---

## Notes

- For each scenario, you can capture Firebase snapshots (`visitors/`, `research_protocol_events/`, `security_alerts/`) to support evaluation and documentation.
- When SMTP is not configured, `/check_in` must **never** display a QR; instead it should show guidance to contact host/reception, as covered in the UI patches.\n

