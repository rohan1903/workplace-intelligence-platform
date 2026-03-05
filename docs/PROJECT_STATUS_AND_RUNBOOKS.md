# Project status and runbooks

Single place for step-by-step runbooks, current status, and high-priority gaps.

---

## Part 1 — Step-by-step runbook

Work through these steps in order. Each step has a **Verify** checklist.

**Delegation:** Steps **2** (Register_App) and **3** (Webcam) require **Firebase credentials** and **webcam/camera** respectively. Delegate to group members who have that setup if needed.

### Step 1 — Admin app (mock data only)

**Goal:** Admin dashboard runs without errors.

1. From project root: `cd Admin`, `pip install -r requirements.txt`
2. Set env (optional; mock is default): Windows `$env:USE_MOCK_DATA="True"` / Linux `export USE_MOCK_DATA=True`
3. Run: `python app.py` → expect "Dashboard URL: http://localhost:5000"

**Verify:** http://localhost:5000 and /dashboard load; occupancy widget and "Occupancy over time (last 24 hours)" chart show data; /api/occupancy and /api/occupancy_over_time return JSON; no 500s on main nav.

### Step 2 — Register_App *(delegate: requires Firebase)*

**Goal:** Registration app starts. Requires `firebase_credentials.json` in `Register_App/`.

1. `cd Register_App`, `pip install -r requirements.txt`
2. Create `.env` with SECRET_KEY, SMTP (optional). For Firebase: place `firebase_credentials.json`, run `python app.py` → http://localhost:5001

**Verify:** http://localhost:5001 loads; test registration returns no 500.

### Step 3 — Webcam *(delegate)*

**Goal:** Gate runs in mock or with camera.

1. `cd Webcam`, `pip install -r requirements.txt`
2. `USE_MOCK_DATA=True` for mock. Run `python app.py` → http://localhost:5002

**Verify:** http://localhost:5002 loads; /mock_demo_data returns JSON when mock.

### Step 4 — Cross-app URLs

- In `Admin/.env`: `REGISTRATION_APP_URL=http://localhost:5001`
- Ports: Admin 5000, Register_App 5001, Webcam 5002

### Step 5 — End-to-end *(delegate to group)*

Full flow: register → approve → check-in at gate → check-out. Requires Firebase + Webcam.

**Handoff for group:** Register_App needs `firebase_credentials.json` and `.env`. Webcam needs `.env` and optionally `USE_MOCK_DATA=True`. Admin runs on 5000 (mock or Firebase).

---

## Part 2 — Current status

**Must Have (1–7):** All done (occupancy, meeting rooms, CRUD, room selection, room utilization, occupancy by selected period).

**Should Have:** #8 Room suggestions done. #9–#11 (peak prediction, forecast, prediction dashboard) not started.

**Nice to Have:** #14 Export done. #12–#13 not started.

See [FEATURES_CHECKLIST.md](FEATURES_CHECKLIST.md) for the full table and gaps backlog.

---

## Part 3 — High-priority easy fixes

**Done:** G11 (production disclaimer in README), #3 occupancy by selected date/range, #8 room suggestions, G4 notify host for time exceeded, #14 export occupancy/room CSV.

**Remaining (medium effort):**

- **Peak time prediction (#9):** Use last 4 weeks’ hourly check-ins by weekday; predict busy hours next 7 days; show in dashboard or API.
- **Visitor volume forecast (#10):** By day-of-week, average past 4 weeks’ daily counts; return next 7 days’ expected counts.

See [FEATURES_CHECKLIST.md](FEATURES_CHECKLIST.md) for the full gaps list (G1–G12).
