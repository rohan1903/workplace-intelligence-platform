# Step-by-step: Make the project work flawlessly

Work through these steps in order. Each step ends with a **Verify** checklist; only move on when that step is solid.

**Delegation:** Steps **2** (Register_App) and **3** (Webcam) require **Firebase credentials** and **webcam/camera** respectively. These can be delegated to group members who have that setup. The rest of the steps (1, 4, 5) can be done without them.

---

## Step 1 — Admin app (mock data only)

**Goal:** Admin dashboard runs without errors, all main pages and APIs respond, mock data shows correctly.

1. From project root:
   ```bash
   cd Admin
   pip install -r requirements.txt
   ```
2. Set env (optional; mock is default):
   - Windows: `$env:USE_MOCK_DATA="True"`
   - Linux/Mac: `export USE_MOCK_DATA=True`
3. Run: `python app.py`  
   - Expected: "Dashboard URL: http://localhost:5000", no tracebacks.

**Verify:**

- [ ] Open http://localhost:5000 — landing/dashboard entry loads.
- [ ] Open http://localhost:5000/dashboard — analytics dashboard loads.
- [ ] "Currently Active" (or occupancy widget) shows a number; no JS errors in console.
- [ ] Chart "Occupancy over time (last 24 hours)" renders with data.
- [ ] Visitors list (e.g. /visitors or dashboard link) loads; department names look correct (no person names as departments).
- [ ] http://localhost:5000/api/occupancy returns JSON with `current_occupancy`.
- [ ] http://localhost:5000/api/occupancy_over_time returns JSON with `occupancy_over_time_last24`.
- [ ] No 500 errors or missing template errors on main navigation (Employees, Feedback, etc. if present).

**If something fails:** Fix crashes/imports first (e.g. sentiment model, missing deps), then re-verify.

---

## Step 2 — Register_App *(delegate: requires Firebase credentials)*

**Goal:** Registration app starts and core pages load. Requires **Firebase** (`firebase_credentials.json` in `Register_App/`). Skip locally if you don’t have credentials; assign to a group member who does.

1. From project root:
   ```bash
   cd Register_App
   pip install -r requirements.txt
   ```
2. Create `Register_App/.env` with at least:
   ```env
   SECRET_KEY=dev_secret
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   EMAIL_USER=
   EMAIL_PASS=
   ```
   (Email can be empty for local test; email-dependent actions will fail but app should start.)
3. **Option A — With Firebase:**  
   Place `firebase_credentials.json` in `Register_App/`. Run: `python app.py`  
   Expected: "Running on http://127.0.0.1:5001" (or similar).
4. **Option B — Without Firebase:**  
   Register_App currently requires Firebase; if credentials are missing, the app may fail on routes that use the DB. Step 2 is then "get Firebase credentials and run Register_App" or "add a mock mode to Register_App" (future).

**Verify (when app is running):**

- [ ] http://localhost:5001 loads (registration or home).
- [ ] Submit a test registration (with or without face upload); no 500 error.
- [ ] If Firebase is used: visitor appears in Firebase or in Admin (when Admin uses Firebase).

---

## Step 3 — Webcam (gate) app *(delegate: optional webcam for full flow)*

**Goal:** Gate runs in mock mode (no camera needed) or with camera for real face check-in/out. Can be assigned to a group member for testing.

1. From project root:
   ```bash
   cd Webcam
   pip install -r requirements.txt
   ```
2. Set mock mode:
   - Windows: `$env:USE_MOCK_DATA="True"`
   - Linux/Mac: `export USE_MOCK_DATA=True`
3. Run: `python app.py`  
   Expected: "Running on http://127.0.0.1:5002", message about USE_MOCK_DATA.

**Verify:**

- [ ] http://localhost:5002 loads (gate UI).
- [ ] http://localhost:5002/mock_demo_data returns JSON with demo visitors/payloads (when USE_MOCK_DATA=True).
- [ ] Mock check-in/check-out (e.g. via /mock_auth or UI) returns success/denied as expected; no tracebacks.

---

## Step 4 — Cross-app URLs and env

**Goal:** Links and API calls between Admin, Register_App, and Webcam point to the right places. Do this so when group members run Register_App and Webcam, the URLs are correct.

1. **Admin → Register_App**  
   In `Admin/.env` set:
   ```env
   REGISTRATION_APP_URL=http://localhost:5001
   ```
   (Or the URL where Register_App actually runs.)
2. **Any email or redirect** that points to Register_App (e.g. employee action link) should use this base URL.
3. **Webcam**  
   If Admin or Register_App link to the gate, ensure that URL is correct (e.g. http://localhost:5002).

**Verify:**

- [x] Admin uses `REGISTRATION_APP_URL` (default `http://localhost:5001`) for invitation/registration links.
- [x] README documents `REGISTRATION_APP_URL=http://localhost:5001` in Admin/.env.
- [ ] From Admin, any "Employee action" or "Visitor profile" link that targets Register_App opens the right page on 5001 (when Register_App is running).
- [x] Ports: Admin 5000, Register_App 5001, Webcam 5002 — consistent across apps.

---

## Step 5 — End-to-end flow *(delegate to group with Firebase + Webcam)*

**Goal:** One full path works: register → approve → check-in at gate → check-out. Assign to group members who have Firebase and (optionally) webcam.

- **With Firebase + Webcam:**  
  Register a visitor (Register_App) → Approve in Admin or Register_App → Check in at Webcam (gate) → Check out at gate. Confirm state in Admin (occupancy, visitor list).
- **What you can do without Firebase:**  
  Admin runs with mock data (Step 1). Full E2E is for the group members who run Register_App and Webcam.

**Verify (for group):**

- [ ] Full E2E (register → approve → check-in → check-out) works with their Firebase and gate setup.
- [ ] Or: document any limitations (e.g. "E2E requires Firebase; Admin works with mock only").

---

## After all steps

- Admin runs with mock data (Step 1 done).
- Steps 2 & 3 (Register_App, Webcam) delegated to group (Firebase + webcam).
- Cross-app URLs documented (Step 4).
- E2E verified or documented by group (Step 5).

Next phase: implement features from the checklist (e.g. room database, CRUD, room selection) in dependency order.

---

## Handoff for group members (Steps 2, 3, 5)

**You need:**

- **Register_App:** `firebase_credentials.json` in `Register_App/`, `.env` with `SECRET_KEY`, SMTP (optional for email). Run: `cd Register_App && python app.py` → http://localhost:5001.
- **Webcam:** `.env` with `AUTH_MODE=hybrid` (or `qr_only` / `face_only`). For mock (no camera): `USE_MOCK_DATA=True`. Run: `cd Webcam && python app.py` → http://localhost:5002.
- **Admin:** Already runs on port 5000 with mock data; with Firebase, set `USE_MOCK_DATA=False` and same `firebase_credentials.json` in `Admin/`.

**Ports:** Admin 5000, Register_App 5001, Webcam 5002. In `Admin/.env`, set `REGISTRATION_APP_URL=http://localhost:5001` so Admin links to registration correctly.
