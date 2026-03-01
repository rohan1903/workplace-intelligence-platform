@echo off
REM Quick Start Script for Visitor Management System (Windows)
REM This script helps you start the applications for testing

echo ==========================================
echo Visitor Management System - Quick Start
echo ==========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

echo [OK] Python found
python --version
echo.

REM Check if virtual environment exists
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Virtual environment found. Activating...
    call venv\Scripts\activate.bat
) else (
    echo [INFO] No virtual environment found. Using system Python.
    echo [TIP] Create virtual environment: python -m venv venv
)
echo.

REM Check ports
echo Checking ports...
netstat -ano | findstr :5000 >nul 2>&1
if errorlevel 1 (
    echo [OK] Port 5000 is available
) else (
    echo [WARNING] Port 5000 is already in use!
)

netstat -ano | findstr :5001 >nul 2>&1
if errorlevel 1 (
    echo [OK] Port 5001 is available
) else (
    echo [WARNING] Port 5001 is already in use!
)

netstat -ano | findstr :5002 >nul 2>&1
if errorlevel 1 (
    echo [OK] Port 5002 is available
) else (
    echo [WARNING] Port 5002 is already in use!
)
echo.

echo ==========================================
echo INSTRUCTIONS:
echo ==========================================
echo.
echo You need to run 3 applications in SEPARATE terminal windows:
echo.
echo Terminal 1 - Register App (Port 5001):
echo   cd Register_App
echo   python app.py
echo   Access at: http://localhost:5001
echo.
echo Terminal 2 - Admin Dashboard (Port 5000):
echo   cd Admin
echo   python app.py
echo   Access at: http://localhost:5000
echo.
echo Terminal 3 - Webcam Check-in (Port 5002):
echo   cd Webcam
echo   python app.py
echo   Access at: http://localhost:5002
echo.
echo ==========================================
echo.

REM Check for required files
echo Checking for required files...
if not exist "Register_App\shape_predictor_68_face_landmarks.dat" (
    echo [WARNING] Missing: Register_App\shape_predictor_68_face_landmarks.dat
    echo [INFO] Download from: http://dlib.net/files/
) else (
    echo [OK] Register_App\shape_predictor_68_face_landmarks.dat found
)

if not exist "Register_App\dlib_face_recognition_resnet_model_v1.dat" (
    echo [WARNING] Missing: Register_App\dlib_face_recognition_resnet_model_v1.dat
    echo [INFO] Download from: http://dlib.net/files/
) else (
    echo [OK] Register_App\dlib_face_recognition_resnet_model_v1.dat found
)

if not exist "Webcam\shape_predictor_68_face_landmarks.dat" (
    echo [WARNING] Missing: Webcam\shape_predictor_68_face_landmarks.dat
) else (
    echo [OK] Webcam\shape_predictor_68_face_landmarks.dat found
)

if not exist "Webcam\dlib_face_recognition_resnet_model_v1.dat" (
    echo [WARNING] Missing: Webcam\dlib_face_recognition_resnet_model_v1.dat
) else (
    echo [OK] Webcam\dlib_face_recognition_resnet_model_v1.dat found
)
echo.

REM Check for .env files
echo Checking configuration files...
if not exist "Register_App\.env" (
    echo [WARNING] Missing: Register_App\.env
    echo [INFO] Create .env file with required variables (see TESTING_GUIDE.md)
) else (
    echo [OK] Register_App\.env found
)

if not exist "Admin\.env" (
    echo [WARNING] Missing: Admin\.env
) else (
    echo [OK] Admin\.env found
)

if not exist "Webcam\.env" (
    echo [WARNING] Missing: Webcam\.env
) else (
    echo [OK] Webcam\.env found
)
echo.

REM Check for Firebase credentials
echo Checking Firebase credentials...
if not exist "Register_App\firebase_credentials.json" (
    echo [WARNING] Missing: Register_App\firebase_credentials.json
    echo [INFO] Get from Firebase Console: https://console.firebase.google.com/
) else (
    echo [OK] Register_App\firebase_credentials.json found
)

if not exist "Admin\firebase_credentials.json" (
    echo [WARNING] Missing: Admin\firebase_credentials.json
) else (
    echo [OK] Admin\firebase_credentials.json found
)

if not exist "Webcam\firebase_credentials.json" (
    echo [WARNING] Missing: Webcam\firebase_credentials.json
) else (
    echo [OK] Webcam\firebase_credentials.json found
)
echo.

echo ==========================================
echo Quick Start Options:
echo ==========================================
echo.
echo 1. Start Register App (Port 5001)
echo 2. Start Admin Dashboard (Port 5000)
echo 3. Start Webcam Gate (Port 5002)
echo 4. Open all in browser (after starting apps)
echo 5. Exit
echo.
set /p choice="Enter your choice (1-5): "

if "%choice%"=="1" (
    echo.
    echo Starting Register App...
    cd Register_App
    python app.py
    cd ..
    pause
    goto :end
)

if "%choice%"=="2" (
    echo.
    echo Starting Admin Dashboard...
    cd Admin
    python app.py
    cd ..
    pause
    goto :end
)

if "%choice%"=="3" (
    echo.
    echo Starting Webcam Gate...
    cd Webcam
    python app.py
    cd ..
    pause
    goto :end
)

if "%choice%"=="4" (
    echo.
    echo Opening browsers...
    start http://localhost:5001
    timeout /t 1 /nobreak >nul
    start http://localhost:5000
    timeout /t 1 /nobreak >nul
    start http://localhost:5002
    echo.
    echo [INFO] Make sure all apps are running first!
    pause
    goto :end
)

if "%choice%"=="5" (
    goto :end
)

:end
echo.
echo ==========================================
echo For detailed testing guide, see: TESTING_GUIDE.md
echo ==========================================
pause
