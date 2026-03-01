# Complete Testing Guide for Visitor Management System

This guide will help you set up and test the entire visitor management system step by step.

---

## 📋 Prerequisites Checklist

Before starting, ensure you have:

- [ ] Python 3.8 or higher installed
- [ ] Webcam/camera access (for face recognition testing)
- [ ] Firebase Realtime Database credentials (`firebase_credentials.json`)
- [ ] Gmail account with App Password (for email notifications)
- [ ] Google Gemini API key (for chatbot - optional)
- [ ] Required model files (see MODEL_FILES.md)

---

## 🔧 Step 1: Install Dependencies

### Option A: Install All at Once (Recommended)

```bash
# Navigate to project root
cd visitor-management-system

# Create virtual environment (optional but recommended)
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install all dependencies
pip install -r Register_App/requirements.txt
pip install -r Admin/requirements.txt
pip install -r Webcam/requirements.txt
```

### Option B: Install Individually

```bash
# Core dependencies
pip install Flask firebase-admin python-dotenv opencv-python numpy

# For face recognition (dlib)
# On Windows: pip install dlib
# On Linux/Mac: May need cmake first
#   sudo apt-get install cmake libopenblas-dev liblapack-dev
#   pip install dlib

# For QR codes
pip install qrcode[pil] pillow

# For Admin dashboard
pip install pandas openpyxl

# For Chatbot (optional)
pip install streamlit google-generativeai

# For Webcam speech features (optional)
pip install openai-whisper sounddevice soundfile torch
```

---

## 📁 Step 2: Download Required Model Files

The system needs these model files to work:

### Required Files:

1. **Register_App/** directory:
   - `shape_predictor_68_face_landmarks.dat` (~95 MB)
   - `dlib_face_recognition_resnet_model_v1.dat` (~22 MB)

2. **Webcam/** directory:
   - `shape_predictor_68_face_landmarks.dat` (~96 MB)
   - `dlib_face_recognition_resnet_model_v1.dat` (~22 MB)

3. **Admin/** directory (optional):
   - `sentiment_analysis.pkl` (~355 MB) - for feedback analysis

### Download Links:

- **dlib models**: Download from http://dlib.net/files/
  - `shape_predictor_68_face_landmarks.dat`
  - `dlib_face_recognition_resnet_model_v1.dat`

Place them in the respective directories.

---

## 🔐 Step 3: Configure Environment Variables

Create `.env` files in each component directory:

### Register_App/.env

```env
SECRET_KEY=your_secret_key_here_12345
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_gmail_app_password
GEMINI_API_KEY=your_gemini_api_key_here
```

### Admin/.env

```env
SECRET_KEY=your_secret_key_here_12345
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_gmail_app_password
REGISTRATION_APP_URL=http://localhost:5001
USE_MOCK_DATA=True
```

### Webcam/.env

```env
SECRET_KEY=your_secret_key_here_12345
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_gmail_app_password
COMPANY_IP=127.0.0.1
AUTH_MODE=hybrid
USE_MOCK_DATA=False
```

**Note**: 
- For Gmail App Password: Go to Google Account → Security → 2-Step Verification → App Passwords
- `USE_MOCK_DATA=True` allows testing without Firebase (Admin only)
- `AUTH_MODE` can be: `hybrid`, `face_only`, or `qr_only`

---

## 🔥 Step 4: Setup Firebase

1. **Get Firebase Credentials**:
   - Go to Firebase Console: https://console.firebase.google.com/
   - Create/select a project
   - Go to Project Settings → Service Accounts
   - Click "Generate New Private Key"
   - Save as `firebase_credentials.json`

2. **Place credentials in each directory**:
   ```
   Register_App/firebase_credentials.json
   Admin/firebase_credentials.json
   Webcam/firebase_credentials.json
   ```

3. **Enable Realtime Database**:
   - In Firebase Console, go to Realtime Database
   - Create database (Start in test mode for testing)
   - Note the database URL (should be: `https://your-project-default-rtdb.firebaseio.com/`)

---

## ✅ Step 5: Quick Pre-Test Check

Run these quick tests to verify setup:

### Test 1: Check Python Dependencies

```bash
# Test Admin app imports
cd Admin
python test_run.py
```

### Test 2: Verify Model Files

```bash
# Check if model files exist
ls Register_App/shape_predictor_68_face_landmarks.dat
ls Register_App/dlib_face_recognition_resnet_model_v1.dat
ls Webcam/shape_predictor_68_face_landmarks.dat
ls Webcam/dlib_face_recognition_resnet_model_v1.dat
```

### Test 3: Test Gender Detection (Optional)

```bash
cd Register_App
python test_gender.py
# This will open webcam and test gender detection
```

---

## 🚀 Step 6: Start the Applications

You need to run **3 separate terminal windows** (one for each app):

### Terminal 1: Register App (Port 5001)

```bash
cd Register_App
python app.py
```

**Expected output:**
```
✅ Firebase initialized successfully
✅ Dlib models loaded successfully
Starting Flask application...
 * Running on http://0.0.0.0:5001
```

**Access at**: http://localhost:5001

---

### Terminal 2: Admin Dashboard (Port 5000)

```bash
cd Admin
python app.py
```

**Expected output:**
```
✅ Firebase initialized successfully - Using REAL data
 * Running on http://0.0.0.0:5000
```

**Access at**: http://localhost:5000

**Note**: If you see "Using MOCK DATA", that's fine for initial testing. Set `USE_MOCK_DATA=False` in `.env` to use real Firebase.

---

### Terminal 3: Webcam Gate (Port 5002)

```bash
cd Webcam
python app.py
```

**Expected output:**
```
✅ Firebase initialized successfully.
✅ Dlib Models loaded.
--- GATE APP STARTUP ---
VERIFICATION THRESHOLD: 0.6
AUTH_MODE (protocol): hybrid
 * Running on http://0.0.0.0:5002
```

**Access at**: http://localhost:5002

---

## 🧪 Step 7: Testing Scenarios

### Test Scenario 1: New Visitor Registration

1. **Open**: http://localhost:5001
2. **Click**: "Register as New Visitor"
3. **Fill form**:
   - Name: Test Visitor
   - Email: test@example.com
   - Purpose: General Visit
   - Visit Date: Today's date
4. **Take/Upload Photo**: Use webcam or upload image
5. **Submit**: Click "Register"
6. **Expected**: 
   - ✅ Registration success message
   - ✅ QR code displayed
   - ✅ Email sent (if configured)
   - ✅ Redirect to check-in page

**Verify in Firebase**:
- Check `visitors/{visitor_id}/basic_info` exists
- Check `visitors/{visitor_id}/visits/{visit_id}` exists
- Check QR code data is stored

---

### Test Scenario 2: Returning Visitor Verification

1. **Open**: http://localhost:5001/verify
2. **Click**: "Verify Face"
3. **Position face** in front of camera
4. **Expected**:
   - ✅ Face recognized (if previously registered)
   - ✅ Redirect to registration form with pre-filled data
   - OR
   - ❌ "Not recognized" → redirect to new registration

---

### Test Scenario 3: Check-In at Gate (Hybrid Mode)

1. **Open**: http://localhost:5002/checkin_gate
2. **Have QR code ready** (from registration)
3. **Position face** in front of camera
4. **Scan QR code** (or enter QR payload manually)
5. **Expected**:
   - ✅ "Access Granted" message
   - ✅ Check-in time recorded
   - ✅ QR state updated to `CHECKIN_USED`
   - ✅ Transaction logged

**Verify**:
- Visit status changed to `checked_in`
- `check_in_time` is set
- QR state is `CHECKIN_USED`

---

### Test Scenario 4: Check-Out at Gate

1. **Open**: http://localhost:5002/checkin_gate
2. **Position face** in front of camera
3. **Scan QR code** (or use face-only)
4. **Expected**:
   - ✅ "Checkout successful" message
   - ✅ Time spent calculated
   - ✅ QR state updated to `CHECKOUT_USED`
   - ✅ Feedback email sent (if configured)

**Verify**:
- Visit status changed to `checked_out`
- `check_out_time` is set
- `time_spent` is calculated

---

### Test Scenario 5: Security Test - QR Mismatch

1. **Register Visitor A** (get their QR code)
2. **Register Visitor B** (get their face registered)
3. **At gate**: Use Visitor A's QR code but Visitor B's face
4. **Expected**:
   - ❌ "Access Denied: QR code does not belong to you"
   - ✅ QR code invalidated
   - ✅ Security alert logged

**Verify in Firebase**:
- Check `security_alerts/` for `QR_FACE_MISMATCH`
- Check QR state is `INVALIDATED`

---

### Test Scenario 6: Stolen QR Detection

1. **Register and check-in** with QR + Face
2. **At checkout**: Use only face (don't scan QR)
3. **Expected**:
   - ✅ Checkout successful
   - ⚠️ QR invalidated (stolen detection)
   - ✅ Security alert logged

**Verify**:
- QR state is `INVALIDATED`
- Reason: "Face-only checkout after QR check-in"
- Security alert: `QR_POSSIBLY_STOLEN`

---

### Test Scenario 7: Employee Meeting Approval

1. **Register visitor** with purpose "Meeting with Employee"
2. **Select employee** from dropdown
3. **Submit registration**
4. **Expected**:
   - ✅ Status: "Pending Approval"
   - ✅ Employee receives email notification
   - ✅ Visit not approved yet

5. **As Employee**: Open employee action link from email
6. **Approve visit**
7. **Expected**:
   - ✅ Status changed to "Approved"
   - ✅ Visitor can now check-in

---

### Test Scenario 8: Admin Dashboard

1. **Open**: http://localhost:5000
2. **View Visitors**: Check visitor list
3. **View Analytics**: Check visit statistics
4. **Test Blacklist**: 
   - Select a visitor
   - Click "Blacklist"
   - Try to check-in → Should be denied

---

### Test Scenario 9: Different Auth Modes

Test the three authentication modes:

#### A. Hybrid Mode (Default)
```bash
cd Webcam
# In .env: AUTH_MODE=hybrid
python app.py
```
- Requires both face and QR to match
- Full security features enabled

#### B. Face-Only Mode
```bash
cd Webcam
# In .env: AUTH_MODE=face_only
python app.py
```
- Only face recognition required
- QR state machine disabled

#### C. QR-Only Mode
```bash
cd Webcam
# In .env: AUTH_MODE=qr_only
python app.py
```
- Only QR code required
- No face recognition

**Compare**: Test same scenarios in each mode and compare security/performance.

---

## 🔍 Step 8: Verify Data in Firebase

### Check Visitor Data

```json
visitors/
  {visitor_id}/
    basic_info/
      name: "Test Visitor"
      contact: "test@example.com"
      embedding: "0.123 0.456 ..." (128D vector)
      photo_url: "/uploads_reg/..."
    visits/
      {visit_id}/
        purpose: "General Visit"
        status: "checked_in"
        check_in_time: "2024-01-15 10:30:00"
        qr_state/
          status: "CHECKIN_USED"
```

### Check Protocol Events

```json
research_protocol_events/
  {event_id}/
    event: "arrival"
    auth_mode: "hybrid"
    visitor_id: "..."
    timestamp: "2024-01-15 10:30:00"
```

### Check Security Alerts

```json
security_alerts/
  {alert_id}/
    alert_type: "QR_FACE_MISMATCH"
    message: "..."
    timestamp: "..."
```

---

## 🐛 Troubleshooting

### Issue 1: "Dlib models not found"

**Solution**:
- Download model files from http://dlib.net/files/
- Place in correct directories
- Verify file paths in code match your structure

---

### Issue 2: "Firebase credentials not found"

**Solution**:
- Ensure `firebase_credentials.json` exists in each app directory
- Check file name is exactly `firebase_credentials.json`
- Verify JSON format is correct

---

### Issue 3: "No face detected"

**Solution**:
- Ensure good lighting
- Face should be clearly visible
- Check webcam permissions
- Try different camera angles

---

### Issue 4: "Port already in use"

**Solution**:
```bash
# Find process using port
# On Windows:
netstat -ano | findstr :5001
taskkill /PID <PID> /F

# On Linux/Mac:
lsof -ti:5001 | xargs kill -9
```

---

### Issue 5: "Email not sending"

**Solution**:
- Verify Gmail App Password (not regular password)
- Check SMTP settings in `.env`
- Ensure 2-Step Verification is enabled on Gmail
- Check firewall/network settings

---

### Issue 6: "Face recognition not working"

**Solution**:
- Verify dlib models are loaded (check startup logs)
- Check face detection threshold (default: 0.6)
- Ensure photo quality is good
- Try adjusting `VERIFICATION_THRESHOLD` in code

---

## 📊 Step 9: Performance Testing

### Measure Response Times

1. **Registration Time**: Time from form submit to QR display
2. **Face Recognition Time**: Time from image capture to match result
3. **Check-in Time**: Time from gate scan to access granted
4. **Database Query Time**: Monitor Firebase console

### Test with Multiple Visitors

1. Register 10+ visitors
2. Test check-in/check-out for each
3. Monitor system performance
4. Check Firebase database load

---

## 📝 Step 10: Test Results Documentation

Create a test results document:

```markdown
# Test Results - [Date]

## Test Environment
- Python Version: 3.x
- Operating System: Windows/Linux/Mac
- Firebase Project: [project-name]

## Test Scenarios
| Scenario | Status | Notes |
|----------|--------|-------|
| New Registration | ✅ Pass | QR generated successfully |
| Face Verification | ✅ Pass | Recognition accuracy: 95% |
| Check-in (Hybrid) | ✅ Pass | Response time: 2.3s |
| Check-out | ✅ Pass | Time calculation correct |
| QR Mismatch | ✅ Pass | Security alert triggered |
| ... | ... | ... |

## Performance Metrics
- Average Registration Time: X seconds
- Average Check-in Time: Y seconds
- Face Recognition Accuracy: Z%

## Issues Found
1. [Issue description]
2. [Issue description]

## Recommendations
- [Recommendation 1]
- [Recommendation 2]
```

---

## 🎯 Quick Test Checklist

Use this checklist for quick testing:

- [ ] All 3 apps start without errors
- [ ] Can register new visitor
- [ ] QR code is generated
- [ ] Face recognition works
- [ ] Check-in at gate works
- [ ] Check-out at gate works
- [ ] Admin dashboard shows visitors
- [ ] Email notifications work (if configured)
- [ ] Security alerts are logged
- [ ] Firebase data is stored correctly

---

## 🚨 Important Notes

1. **Model Files**: System won't work without dlib model files
2. **Firebase**: Can use mock data for Admin, but Register_App and Webcam need real Firebase
3. **Webcam**: Requires camera access - may need to grant permissions
4. **Email**: Optional but recommended for full functionality
5. **Security**: Don't commit `.env` or `firebase_credentials.json` to Git

---

## 📞 Need Help?

If you encounter issues:

1. Check the logs in terminal output
2. Verify all prerequisites are met
3. Check Firebase console for data
4. Review error messages carefully
5. Ensure all model files are in place

---

## ✅ Success Criteria

Your system is working correctly if:

- ✅ All 3 apps start successfully
- ✅ You can register a visitor
- ✅ QR code is generated and displayed
- ✅ Face recognition identifies registered visitors
- ✅ Check-in/check-out works at gate
- ✅ Data appears in Firebase
- ✅ Admin dashboard shows visitors

---

**Happy Testing! 🎉**
