# Setup Guide

Complete setup instructions for the Workplace Intelligence Platform with Hybrid Face-QR Authentication.

---

## Prerequisites

- Python 3.8+
- Webcam / camera access (for face recognition)
- Firebase Realtime Database credentials
- Gmail account with App Password (for email notifications)

---

## 1. Install Dependencies

```bash
cd workplace-intelligence-platform

# Create and activate virtual environment (recommended)
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install all dependencies
pip install -r registration/requirements.txt
pip install -r admin/requirements.txt
pip install -r gate/requirements.txt
```

---

## 2. Install dlib (Face Recognition)

dlib is required for face recognition in both the registration and gate apps.

### Windows

1. Install **CMake**: download from https://cmake.org/download/ (choose "Add CMake to system PATH").
2. If `pip install dlib` fails with C++ errors, install **Visual Studio Build Tools**: https://visualstudio.microsoft.com/visual-cpp-build-tools/ and select "Desktop development with C++".
3. Then:

```powershell
pip install cmake
pip install dlib
```

**Fallback (conda):**

```powershell
conda create -n vis python=3.10
conda activate vis
conda install -c conda-forge dlib
pip install -r registration/requirements.txt
pip install -r gate/requirements.txt
```

### Linux / Mac

```bash
sudo apt-get install cmake libopenblas-dev liblapack-dev  # Debian/Ubuntu
pip install cmake dlib
```

---

## 3. Download Model Files

Download these two files from http://dlib.net/files/ (they are `.bz2` archives -- extract them):

| File | Size |
|------|------|
| `shape_predictor_68_face_landmarks.dat` | ~95 MB |
| `dlib_face_recognition_resnet_model_v1.dat` | ~22 MB |

Place the **same two files** in both directories:

```
registration/shape_predictor_68_face_landmarks.dat
registration/dlib_face_recognition_resnet_model_v1.dat
gate/shape_predictor_68_face_landmarks.dat
gate/dlib_face_recognition_resnet_model_v1.dat
```

**Optional (admin only):** `admin/sentiment_analysis.pkl` (~355 MB) for feedback sentiment analysis.

---

## 4. Firebase Setup

### Get Credentials

1. Go to https://console.firebase.google.com/
2. Select your project (or create one)
3. Go to Project Settings (gear icon) > Service Accounts
4. Click "Generate New Private Key" > Confirm
5. Rename the downloaded file to `firebase_credentials.json`

### Place Credentials

Copy the same file into all three app directories:

```
registration/firebase_credentials.json
admin/firebase_credentials.json
gate/firebase_credentials.json
```

### Create Realtime Database

1. In Firebase Console, go to Build > Realtime Database
2. Click "Create Database"
3. Choose a location, click Next, then "Start in test mode"
4. Copy the database URL from the top of the page (e.g. `https://your-project-default-rtdb.firebaseio.com`)

---

## 5. Environment Variables

Create a `.env` file in each app directory. Use `.env.example` at the project root as a template.

### registration/.env

```env
SECRET_KEY=your_secret_key_here
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_gmail_app_password
GEMINI_API_KEY=your_gemini_api_key_here
ADMIN_APP_URL=http://localhost:5000
FIREBASE_DATABASE_URL=https://your-project-default-rtdb.firebaseio.com
```

### admin/.env

```env
SECRET_KEY=your_secret_key_here
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_gmail_app_password
REGISTRATION_APP_URL=http://localhost:5001
USE_MOCK_DATA=False
FIREBASE_DATABASE_URL=https://your-project-default-rtdb.firebaseio.com
```

Set `USE_MOCK_DATA=True` to test the admin dashboard without Firebase.

### gate/.env

```env
SECRET_KEY=your_secret_key_here
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_gmail_app_password
COMPANY_IP=127.0.0.1
AUTH_MODE=hybrid
FIREBASE_DATABASE_URL=https://your-project-default-rtdb.firebaseio.com
```

`AUTH_MODE` options: `hybrid` (default), `face_only`, `qr_only`.

**Gmail App Password:** Go to Google Account > Security > 2-Step Verification > App Passwords.

---

## 6. Seed Sample Data

After Firebase is configured, seed one employee and one meeting room so the registration form dropdowns work:

```bash
python seed_firebase_data.py
```

---

## 7. Start the Apps

Run each in a **separate terminal**:

```bash
# Terminal 1 - Registration (Port 5001)
cd registration
python app.py

# Terminal 2 - Admin Dashboard (Port 5000)
cd admin
python app.py

# Terminal 3 - Gate (Port 5002)
cd gate
python app.py
```

### Expected Startup Output

**Registration:**
```
Firebase initialized successfully
Dlib models loaded successfully
 * Running on http://0.0.0.0:5001
```

**Admin:**
```
Firebase initialized successfully - Using REAL data
 * Running on http://0.0.0.0:5000
```

**Gate:**
```
Firebase initialized successfully.
Dlib Models loaded.
AUTH_MODE (protocol): hybrid
 * Running on http://0.0.0.0:5002
```

---

## 8. Verify Setup

Run the automated check from the project root:

```bash
python verify_setup.py
```

Or use the quick-start script:

```bash
# Windows:
test_quick_start.bat

# Linux/Mac:
bash run_apps.sh
```

---

## Troubleshooting

### "Dlib models not found"
Download the `.dat` files from http://dlib.net/files/ and place them in `registration/` and `gate/`.

### "Firebase credentials not found"
Ensure `firebase_credentials.json` exists in all three app directories. See FIREBASE_CREDENTIALS_SETUP.txt for step-by-step instructions.

### "Database unavailable" / Firebase 404
The Realtime Database may not exist yet. Create it in Firebase Console (Build > Realtime Database > Create Database), then set `FIREBASE_DATABASE_URL` in all `.env` files.

### "Port already in use"

```bash
# Windows:
netstat -ano | findstr :5001
taskkill /PID <PID> /F

# Linux/Mac:
lsof -ti:5001 | xargs kill -9
```

### "Email not sending"
- Use a Gmail **App Password**, not your regular password
- Ensure 2-Step Verification is enabled on your Google Account
- Check SMTP settings in `.env`

### "No face detected"
- Ensure good lighting
- Face should be clearly visible and frontal
- Check webcam permissions in your browser
- Try different camera angles

### "pip install dlib" fails
- Windows: Install CMake and Visual Studio Build Tools first
- Or use conda: `conda install -c conda-forge dlib`
