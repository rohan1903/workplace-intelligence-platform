# Face Recognition Setup (Required for This Project)

Face recognition is **required** for the visitor management system. It is used in:

- **Register_App** — to capture your face and compute a 128-D embedding stored with your visitor profile
- **Webcam** — to verify your face at the gate (hybrid mode: QR + face)

Without dlib and the model files, registration falls back to a placeholder embedding and the gate cannot match your face.

---

## 1. Install dlib (Windows)

### Step 1a: Install CMake

- Download **CMake** from https://cmake.org/download/ (e.g. “Windows x64 Installer”).
- Run the installer and choose **“Add CMake to the system PATH for all users”** (or “for current user”).
- Close and reopen your terminal/PowerShell so `cmake` is available.

### Step 1b: Install Visual Studio Build Tools (if needed)

If `pip install dlib` fails with a C++ or compiler error:

- Install **Visual Studio Build Tools**: https://visualstudio.microsoft.com/visual-cpp-build-tools/
- In the installer, select the workload **“Desktop development with C++”**.
- Restart the terminal after installation.

### Step 1c: Install dlib with pip

From the project root (or with your virtual environment activated):

```powershell
pip install cmake
pip install dlib
```

If that succeeds, skip to **Section 2 (Model files)**.

If it fails (e.g. Python 3.12 and compiler errors), try:

**Option B — Conda (often works when pip fails):**

```powershell
conda create -n vis python=3.10
conda activate vis
conda install -c conda-forge dlib
pip install -r Register_App/requirements.txt
pip install -r Webcam/requirements.txt
```

Then run the three apps from this `vis` environment.

---

## 2. Download and Place Model Files

The app needs two dlib model files in **both** `Register_App/` and `Webcam/`.

### Files required

| File | Size (approx) | Used by |
|------|----------------|--------|
| `shape_predictor_68_face_landmarks.dat` | ~95 MB | Register_App, Webcam |
| `dlib_face_recognition_resnet_model_v1.dat` | ~22 MB | Register_App, Webcam |

### Download

1. Open **http://dlib.net/files/** in your browser.
2. Download (they are `.bz2` archives):
   - **shape_predictor_68_face_landmarks.dat.bz2**
   - **dlib_face_recognition_resnet_model_v1.dat.bz2**
3. Uncompress them (e.g. 7-Zip, WinRAR, or `tar -xjf` if you have it). You should get two files:
   - `shape_predictor_68_face_landmarks.dat`
   - `dlib_face_recognition_resnet_model_v1.dat`

### Place the files

Copy the **same two files** into both folders:

- `Register_App/shape_predictor_68_face_landmarks.dat`
- `Register_App/dlib_face_recognition_resnet_model_v1.dat`
- `Webcam/shape_predictor_68_face_landmarks.dat`
- `Webcam/dlib_face_recognition_resnet_model_v1.dat`

So each of the two `.dat` files exists in both `Register_App/` and `Webcam/`.

---

## 3. Verify

From the project root:

```powershell
python verify_setup.py
```

Check that:

- **dlib** is reported as installed.
- **Register_App/...dat** and **Webcam/...dat** are reported as present.

Then start the apps:

- **Register_App**: you should see “Dlib models loaded” (or similar) in the terminal, and no “Face recognition disabled” message.
- **Webcam**: you should see “[OK] Dlib models loaded.” and no “Dlib not installed”.

---

## 4. Quick reference

| Step | Action |
|------|--------|
| 1 | Install CMake and add to PATH |
| 2 | (If needed) Install Visual Studio Build Tools with “Desktop development with C++” |
| 3 | `pip install cmake` then `pip install dlib` (or use conda) |
| 4 | Download the two `.dat.bz2` files from http://dlib.net/files/ and extract |
| 5 | Copy both `.dat` files into `Register_App/` and `Webcam/` |
| 6 | Run `python verify_setup.py` and start the apps |

After this, face recognition is enabled for registration and for the gate (hybrid mode).
