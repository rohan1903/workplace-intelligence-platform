#!/usr/bin/env python3
"""
Setup Verification Script for Visitor Management System
This script checks if your environment is ready for testing.
"""

import os
import sys
from pathlib import Path

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_success(message):
    print(f"{GREEN}✅ {message}{RESET}")

def print_error(message):
    print(f"{RED}❌ {message}{RESET}")

def print_warning(message):
    print(f"{YELLOW}⚠️  {message}{RESET}")

def print_info(message):
    print(f"{BLUE}ℹ️  {message}{RESET}")

def check_python_version():
    """Check if Python version is 3.8+"""
    print("\n" + "="*50)
    print("Checking Python Version...")
    print("="*50)
    
    version = sys.version_info
    if version.major == 3 and version.minor >= 8:
        print_success(f"Python {version.major}.{version.minor}.{version.micro} is installed")
        return True
    else:
        print_error(f"Python {version.major}.{version.minor} found. Python 3.8+ required")
        return False

def check_dependencies():
    """Check if required Python packages are installed"""
    print("\n" + "="*50)
    print("Checking Dependencies...")
    print("="*50)
    
    required_packages = {
        'flask': 'Flask',
        'firebase_admin': 'firebase-admin',
        'cv2': 'opencv-python',
        'numpy': 'numpy',
        'dotenv': 'python-dotenv',
        'qrcode': 'qrcode[pil]',
        'pandas': 'pandas',
    }
    
    optional_packages = {
        'dlib': 'dlib (for face recognition)',
        'streamlit': 'streamlit (for chatbot)',
        'google.generativeai': 'google-generativeai (for chatbot)',
    }
    
    all_ok = True
    
    for module, package_name in required_packages.items():
        try:
            __import__(module)
            print_success(f"{package_name} is installed")
        except ImportError:
            print_error(f"{package_name} is NOT installed")
            print_info(f"  Install with: pip install {package_name}")
            all_ok = False
    
    for module, package_name in optional_packages.items():
        try:
            __import__(module)
            print_success(f"{package_name} is installed")
        except ImportError:
            print_warning(f"{package_name} is NOT installed (optional)")
    
    return all_ok

def check_model_files():
    """Check if required model files exist"""
    print("\n" + "="*50)
    print("Checking Model Files...")
    print("="*50)
    
    model_files = {
        'Register_App/shape_predictor_68_face_landmarks.dat': 'http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2',
        'Register_App/dlib_face_recognition_resnet_model_v1.dat': 'http://dlib.net/files/dlib_face_recognition_resnet_model_v1.dat.bz2',
        'Webcam/shape_predictor_68_face_landmarks.dat': 'http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2',
        'Webcam/dlib_face_recognition_resnet_model_v1.dat': 'http://dlib.net/files/dlib_face_recognition_resnet_model_v1.dat.bz2',
    }
    
    all_ok = True
    
    for file_path, download_url in model_files.items():
        full_path = Path(file_path)
        if full_path.exists():
            size_mb = full_path.stat().st_size / (1024 * 1024)
            print_success(f"{file_path} exists ({size_mb:.1f} MB)")
        else:
            print_error(f"{file_path} is MISSING")
            print_info(f"  Download from: {download_url}")
            all_ok = False
    
    # Check optional Admin model
    admin_model = Path('Admin/sentiment_analysis.pkl')
    if admin_model.exists():
        size_mb = admin_model.stat().st_size / (1024 * 1024)
        print_success(f"Admin/sentiment_analysis.pkl exists ({size_mb:.1f} MB)")
    else:
        print_warning("Admin/sentiment_analysis.pkl is missing (optional for feedback analysis)")
    
    return all_ok

def check_env_files():
    """Check if .env files exist"""
    print("\n" + "="*50)
    print("Checking Configuration Files...")
    print("="*50)
    
    env_files = {
        'Register_App/.env': ['SECRET_KEY', 'EMAIL_USER', 'EMAIL_PASS', 'GEMINI_API_KEY'],
        'Admin/.env': ['SECRET_KEY', 'EMAIL_USER', 'EMAIL_PASS'],
        'Webcam/.env': ['SECRET_KEY', 'EMAIL_USER', 'EMAIL_PASS', 'AUTH_MODE'],
    }
    
    all_ok = True
    
    for env_path, required_vars in env_files.items():
        full_path = Path(env_path)
        if full_path.exists():
            print_success(f"{env_path} exists")
            # Try to check if variables are set (basic check)
            try:
                from dotenv import load_dotenv
                load_dotenv(full_path)
                missing_vars = []
                for var in required_vars:
                    if not os.getenv(var):
                        missing_vars.append(var)
                if missing_vars:
                    print_warning(f"  Missing variables: {', '.join(missing_vars)}")
            except:
                pass
        else:
            print_error(f"{env_path} is MISSING")
            print_info(f"  Create .env file with: {', '.join(required_vars)}")
            all_ok = False
    
    return all_ok

def check_firebase_credentials():
    """Check if Firebase credentials exist"""
    print("\n" + "="*50)
    print("Checking Firebase Credentials...")
    print("="*50)
    
    credential_files = [
        'Register_App/firebase_credentials.json',
        'Admin/firebase_credentials.json',
        'Webcam/firebase_credentials.json',
    ]
    
    all_ok = True
    
    for cred_path in credential_files:
        full_path = Path(cred_path)
        if full_path.exists():
            print_success(f"{cred_path} exists")
        else:
            print_error(f"{cred_path} is MISSING")
            print_info("  Get from Firebase Console: https://console.firebase.google.com/")
            all_ok = False
    
    return all_ok

def check_ports():
    """Check if required ports are available"""
    print("\n" + "="*50)
    print("Checking Port Availability...")
    print("="*50)
    
    import socket
    
    ports = {
        5000: 'Admin Dashboard',
        5001: 'Register App',
        5002: 'Webcam Gate',
    }
    
    all_ok = True
    
    for port, app_name in ports.items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if result == 0:
            print_warning(f"Port {port} ({app_name}) is already in use")
            print_info("  You may need to stop the running application")
        else:
            print_success(f"Port {port} ({app_name}) is available")
    
    return all_ok

def check_directories():
    """Check if required directories exist"""
    print("\n" + "="*50)
    print("Checking Directory Structure...")
    print("="*50)
    
    required_dirs = [
        'Register_App',
        'Admin',
        'Webcam',
        'Register_App/templates',
        'Register_App/uploads_reg',
        'Webcam/uploads',
    ]
    
    all_ok = True
    
    for dir_path in required_dirs:
        full_path = Path(dir_path)
        if full_path.exists():
            print_success(f"{dir_path}/ exists")
        else:
            print_error(f"{dir_path}/ is MISSING")
            all_ok = False
    
    return all_ok

def main():
    """Run all checks"""
    print("\n" + "="*60)
    print("Visitor Management System - Setup Verification")
    print("="*60)
    
    results = {
        'Python Version': check_python_version(),
        'Dependencies': check_dependencies(),
        'Model Files': check_model_files(),
        'Configuration Files': check_env_files(),
        'Firebase Credentials': check_firebase_credentials(),
        'Ports': check_ports(),
        'Directories': check_directories(),
    }
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check_name, result in results.items():
        if result:
            print_success(f"{check_name}: OK")
        else:
            print_error(f"{check_name}: FAILED")
    
    print("\n" + "="*60)
    if passed == total:
        print_success(f"All checks passed! ({passed}/{total})")
        print_info("You're ready to test the system!")
        print_info("Run: python test_quick_start.bat or see TESTING_GUIDE.md")
    else:
        print_warning(f"Some checks failed ({passed}/{total})")
        print_info("Please fix the issues above before testing")
        print_info("See TESTING_GUIDE.md for detailed setup instructions")
    print("="*60 + "\n")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
