# Project Structure & Organization

This document describes the organised layout of the **Office Workplace Intelligence Platform** and lists files that are redundant or archived.

---

## Directory layout

```
visitor-management-system/
├── README.md                    # Project overview, architecture, setup
├── .gitignore
├── .env.example                 # Template for env vars (copy to Register_App/.env, Admin/.env, Webcam/.env)
├── verify_setup.py              # Setup verification (Python, deps, .env, Firebase, models)
├── run_apps.sh                  # Unix: run all three apps
├── test_quick_start.bat         # Windows: quick start
├── PUSH_TO_GITHUB.sh            # Git initial-commit helper
│
├── docs/                        # All documentation
│   ├── README.md                # Docs index (start here)
│   ├── PROJECT_STRUCTURE.md     # This file
│   ├── Hybrid_Face_QR_Protocol.md
│   ├── PROJECT_STATUS_AND_RUNBOOKS.md
│   ├── FEATURES_CHECKLIST.md
│   ├── TESTING_GUIDE.md         # Primary testing guide
│   ├── QUICK_TEST_CHECKLIST.md
│   ├── ADMIN_DASHBOARD_TESTING.md
│   ├── SWITCH_TO_REAL_DATA.md
│   ├── MODEL_FILES.md
│   └── FACE_RECOGNITION_SETUP.md
│
├── Register_App/                # Visitor registration, QR, host approval (Flask, port 5001)
│   ├── app.py                   # Main entry
│   ├── app_attendance.py        # Alternate app (attendance / DeepFace) — optional
│   ├── speech_app.py            # Alternate app (feedback + Gemini) — optional
│   ├── chatbot.py, chatbot_utils.py, intents.py
│   ├── requirements.txt
│   ├── Procfile                 # Heroku-style (gunicorn app:app)
│   ├── tests/
│   │   └── test_gender.py       # Gender model test (run from Register_App)
│   ├── prompts/
│   │   └── system_prompt.txt
│   └── templates/
│
├── Admin/                       # Dashboard, analytics (Flask, port 5000)
│   ├── app.py                   # Main entry (HTML inlined via render_template_string)
│   ├── requirements.txt
│   ├── run_dashboard.sh
│   ├── tests/
│   │   ├── test_run.py          # Import/setup check
│   │   └── test_occupancy_api.py
│   └── templates/               # Empty; legacy templates moved to _archive (app.py uses inlined HTML)
│
├── Webcam/                      # Gate — face/QR protocol (Flask, port 5002)
│   ├── app.py
│   ├── qr_module.py             # QR token/state machine
│   ├── firebase_config.py
│   ├── speech_to_text.py
│   ├── requirements.txt
│   └── templates/
│
└── _archive/                    # Redundant/unused files moved here (safe to delete after review)
    ├── Register_App_generate_qr.py
    ├── Webcam_generate_qr.py
    ├── Admin_template_admin_dashboard.html
    ├── Admin_template_feedback_analysis.html
    └── Admin_template_visitor.html
```

---

## Entry points

| App           | Directory     | Port | Command (from app dir)   |
|---------------|---------------|------|--------------------------|
| Registration  | Register_App/ | 5001 | `python app.py`          |
| Admin         | Admin/        | 5000 | `python app.py`          |
| Gate          | Webcam/       | 5002 | `python app.py`          |

---

## Config

- **Per-app `.env`**: Each of `Register_App/`, `Admin/`, and `Webcam/` can have its own `.env`. Use root `.env.example` as a template; copy and fill for each app as needed.
- **Firebase**: `firebase_credentials.json` in each app directory (see `verify_setup.py` and docs).
- **Model files**: See `docs/MODEL_FILES.md` and `verify_setup.py`.

---

## Tests

- **Admin**: `Admin/tests/test_run.py`, `Admin/tests/test_occupancy_api.py` — run from `Admin/` (e.g. `python tests/test_run.py`).
- **Register_App**: `Register_App/tests/test_gender.py` — run from `Register_App/` (needs `genderage.onnx` in `Register_App/`).

---

## Redundant or low-value files

These have been **moved to `_archive/`** so you can review before deleting. Summary:

| File (original location) | Reason |
|---------------------------|--------|
| **Register_App/generate_qr.py** | Standalone script with hardcoded URL; not used by `app.py`. Real QR generation is in `app.py` (`_generate_qr_*`). |
| **Webcam/generate_qr.py** | Same: standalone, hardcoded URL. Real QR logic is in `Webcam/qr_module.py`. |
| **Admin/templates/admin_dashboard.html** | Dashboard is served via `render_template_string(DASHBOARD_HTML, ...)` in `app.py`; this file is never loaded. |
| **Admin/templates/feedback_analysis.html** | Feedback UI is inlined in `app.py`; this template is not used. |
| **Admin/templates/visitor.html** | Mostly commented-out; not referenced by `app.py`. |

### Other notes (not moved)

- **Register_App/templates/old_register.html** — In use by `/old_register`; keep. You may trim large commented blocks.
- **Register_App/app_attendance.py** — Alternate DeepFace attendance app; heavily commented. Keep if you use it; else consider archiving.
- **Register_App/speech_app.py** — Alternate speech/feedback app. Keep if you use it.
- **Testing docs** — `TESTING_GUIDE.md` is the primary guide; `QUICK_TEST_CHECKLIST.md` is a short reference (see `docs/README.md`).

---

## Organisation changes made

1. **Tests**: Moved `Admin/test_*.py` → `Admin/tests/`, `Register_App/test_gender.py` → `Register_App/tests/` and adjusted imports/paths so they still run from their app directory.
2. **Config**: Added root `.env.example` and documented env vars; per-app `.env` remains in each app folder.
3. **Docs**: Added `docs/README.md` as an index; `docs/PROJECT_STRUCTURE.md` (this file) documents structure and redundant files.
4. **Webcam/requirements.txt**: Removed invalid `pip install ...` line; left only package names.
5. **Redundant files**: Moved the five items above to `_archive/` with renamed filenames to avoid path collisions.

After you confirm you do not need anything in `_archive/`, you can delete the `_archive/` folder.
