# Switching from Mock Data to Real Firebase

## Quick Switch Instructions

When you're ready to use real Firebase data instead of mock data, follow these steps:

### Option 1: Using Environment Variable (Recommended)

```bash
# Set environment variable before running
export USE_MOCK_DATA=False
python3 app.py
```

### Option 2: Modify the Code Directly

Edit `app.py` and change line ~47:

```python
USE_MOCK_DATA = False  # Change from True to False
```

### Requirements

1. **Firebase Credentials**: Ensure `firebase_credentials.json` exists in the `Admin` directory
2. **Firebase Admin SDK**: Install if not already installed:
   ```bash
   pip install firebase-admin
   ```
3. **Database URL**: The database URL is already configured in the code

### Verification

When you switch to real data, you should see:
```
✅ Firebase initialized successfully - Using REAL data
```

Instead of:
```
💡 Using MOCK DATA for demonstration
```

### Switching Back to Mock Data

If you want to switch back to mock data:
```bash
export USE_MOCK_DATA=True
python3 app.py
```

Or set `USE_MOCK_DATA = True` in the code.

