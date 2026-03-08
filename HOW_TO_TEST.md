# How to Test the Entire Project

Quick runbook to run all three apps and test the full visitor flow.

---

## 1. One-time setup

- **Python 3.8+** installed.
- **Dependencies** (from project root):
  ```bash
  pip install -r Register_App/requirements.txt
  pip install -r Admin/requirements.txt
  pip install -r Webcam/requirements.txt
  ```
- **Firebase**: `firebase_credentials.json` in `Register_App/`, `Admin/`, and `Webcam/` (you already have these).
- **.env**: You have `.env` in each app with `SECRET_KEY` and Firebase vars.
- **Real data**: In `Admin/.env` set `USE_MOCK_DATA=False` so approve/check-in/check-out persist in Firebase.
- **Face recognition (required)**: Install dlib and add the two model files to `Register_App/` and `Webcam/`. See **[docs/FACE_RECOGNITION_SETUP.md](docs/FACE_RECOGNITION_SETUP.md)** for full steps (Windows: CMake, pip install dlib, download and place `shape_predictor_68_face_landmarks.dat` and `dlib_face_recognition_resnet_model_v1.dat`).

---

## 2. Start all three apps (3 terminals)

Use **three separate terminals**. Run and leave each one open.

| # | Directory      | Command        | URL                    |
|---|----------------|----------------|------------------------|
| 1 | `Register_App` | `python app.py`| http://localhost:5001  |
| 2 | `Admin`        | `python app.py`| http://localhost:5000  |
| 3 | `Webcam`       | `python app.py`| http://localhost:5002  |

**Windows (PowerShell):**
```powershell
# Terminal 1
cd Register_App; python app.py

# Terminal 2 (new window)
cd Admin; python app.py

# Terminal 3 (new window)
cd Webcam; python app.py
```

**Check:** No port-in-use errors; Admin should log something like “Using REAL data” (if `USE_MOCK_DATA=False`).

---

## 3. End-to-end test flow

1. **Register a visitor** (Register_App)  
   - Open http://localhost:5001  
   - Start a new registration: name, email, purpose, date, meeting room  
   - Capture/upload photo (or skip if no camera/models)  
   - Submit → you should get a **QR code** and success message  

2. **Approve in Admin**  
   - Open http://localhost:5000  
   - Go to **Visitors**  
   - Find the new visitor (status “Registered”)  
   - Click **Approve** (green check) → status becomes “Approved”  

3. **Check-in at the gate** (Webcam)  
   - Open http://localhost:5002 (or http://localhost:5002/checkin_gate)  
   - Show the **QR code** from step 1 (e.g. on phone or printed)  
   - If hybrid mode: also show your face to the camera  
   - You should see “Access Granted” / check-in success  

4. **Check-out at the gate**  
   - At http://localhost:5002, use the same visitor (QR + face if hybrid) to **check out**  
   - You should see checkout success  

5. **Verify in Admin**  
   - In Admin → **Visitors**, confirm the visitor shows “Checked Out” and times are recorded  
   - In Admin → **Dashboard**, check “Currently Active” and occupancy charts  

---

## 4. Full testing checklist

For a detailed step-by-step checklist (all Admin pages, Rooms, Blacklist, Feedback, Employees, etc.), use:

- **[docs/TESTING_CHECKLIST.md](docs/TESTING_CHECKLIST.md)** — full checklist with checkboxes

For model files, security scenarios, and troubleshooting:

- **[docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md)**

---

## 5. Ports summary

| App         | Port | URL                     |
|------------|------|-------------------------|
| Admin      | 5000 | http://localhost:5000   |
| Register_App | 5001 | http://localhost:5001 |
| Webcam     | 5002 | http://localhost:5002   |

If a port is in use, close the app using it or change the port in that app’s `app.py`.
