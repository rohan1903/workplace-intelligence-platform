# Quick Test Checklist

Use this checklist to quickly verify your system is working.

## ✅ Pre-Test Setup

- [ ] Python 3.8+ installed
- [ ] All dependencies installed (`pip install -r requirements.txt` for each app)
- [ ] Model files downloaded and placed in correct directories
- [ ] `.env` files created in Register_App, Admin, and Webcam directories
- [ ] `firebase_credentials.json` placed in all three app directories
- [ ] Webcam/camera access granted

## ✅ Application Startup

- [ ] Register_App starts on port 5001 without errors
- [ ] Admin Dashboard starts on port 5000 without errors
- [ ] Webcam Gate starts on port 5002 without errors
- [ ] All apps show "Firebase initialized successfully"
- [ ] All apps show "Dlib models loaded successfully" (Register_App and Webcam)

## ✅ Basic Functionality Tests

### Registration
- [ ] Can access http://localhost:5001
- [ ] Can fill registration form
- [ ] Can capture/upload photo
- [ ] Registration completes successfully
- [ ] QR code is displayed after registration
- [ ] Email notification sent (if configured)

### Face Verification
- [ ] Can access /verify page
- [ ] Webcam opens for face capture
- [ ] Face detection works
- [ ] Returning visitor is recognized
- [ ] New visitor is redirected to registration

### Check-In
- [ ] Can access http://localhost:5002/checkin_gate
- [ ] Webcam opens for face capture
- [ ] QR code can be scanned
- [ ] Face recognition matches visitor
- [ ] Access is granted for valid visitor
- [ ] Check-in time is recorded
- [ ] Visit status changes to "checked_in"

### Check-Out
- [ ] Can check out at gate
- [ ] Face recognition works for checkout
- [ ] Check-out time is recorded
- [ ] Time spent is calculated correctly
- [ ] Visit status changes to "checked_out"
- [ ] Feedback email sent (if configured)

### Admin Dashboard
- [ ] Can access http://localhost:5000
- [ ] Visitor list is displayed
- [ ] Can view visitor details
- [ ] Analytics are shown
- [ ] Can blacklist a visitor
- [ ] Blacklisted visitor is denied access at gate

## ✅ Security Tests

- [ ] QR mismatch detection works (wrong person with valid QR)
- [ ] QR is invalidated on mismatch
- [ ] Security alert is logged
- [ ] Stolen QR detection works (face-only checkout after QR check-in)
- [ ] Blacklisted visitor is denied access
- [ ] Twin/ambiguous face detection works (if applicable)

## ✅ Data Verification

- [ ] Visitor data appears in Firebase
- [ ] Visit records are created
- [ ] QR state is tracked correctly
- [ ] Protocol events are logged
- [ ] Security alerts are logged
- [ ] Transactions are recorded

## ✅ Different Auth Modes

- [ ] Hybrid mode works (AUTH_MODE=hybrid)
- [ ] Face-only mode works (AUTH_MODE=face_only)
- [ ] QR-only mode works (AUTH_MODE=qr_only)

## ✅ Error Handling

- [ ] System handles missing face gracefully
- [ ] System handles invalid QR gracefully
- [ ] System handles expired QR gracefully
- [ ] System handles blacklisted visitor gracefully
- [ ] Error messages are clear and helpful

## ✅ Performance

- [ ] Registration completes in < 5 seconds
- [ ] Face recognition completes in < 3 seconds
- [ ] Check-in completes in < 5 seconds
- [ ] Check-out completes in < 5 seconds
- [ ] No significant lag or freezing

## 🐛 Common Issues to Check

- [ ] No "Model files not found" errors
- [ ] No "Firebase credentials not found" errors
- [ ] No "Port already in use" errors
- [ ] No "Email sending failed" errors (if email configured)
- [ ] No "Face detection failed" errors (with good lighting)

## 📝 Test Results

After completing tests, note:

- **Total Tests**: _____
- **Passed**: _____
- **Failed**: _____
- **Issues Found**: _____
- **Overall Status**: ✅ Working / ⚠️ Issues / ❌ Not Working

---

## Quick Test Commands

```bash
# Test 1: Check dependencies
cd Admin && python test_run.py

# Test 2: Start all apps (in separate terminals)
cd Register_App && python app.py
cd Admin && python app.py  
cd Webcam && python app.py

# Test 3: Verify model files
dir Register_App\*.dat
dir Webcam\*.dat
```

---

**Note**: If any test fails, refer to TESTING_GUIDE.md for detailed troubleshooting steps.
