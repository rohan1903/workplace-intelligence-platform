# Model Files Setup

## ⚠️ Important: Large Model Files

Due to GitHub's file size limits (100MB hard limit, 50MB recommended), the following large model files are **NOT** included in this repository:

### Missing Files:

1. **Admin/**
   - `sentiment_analysis.pkl` (355.71 MB) - Sentiment analysis model

2. **Register_App/**
   - `shape_predictor_68_face_landmarks.dat` (95.08 MB) - dlib face landmarks predictor
   - `dlib_face_recognition_resnet_model_v1.dat` (22 MB) - dlib face recognition model
   - `dlib_casia_face_classifier.pkl` - Face classifier
   - `dlib_casia_label_encoder.pkl` - Label encoder
   - `genderage.onnx` - Gender/age detection model

3. **Webcam/**
   - `shape_predictor_68_face_landmarks.dat` (96 MB) - dlib face landmarks predictor
   - `dlib_face_recognition_resnet_model_v1.dat` (22 MB) - dlib face recognition model

## 📥 How to Get These Files

### Option 1: Download from Original Source

**dlib Models:**
- Download from: http://dlib.net/files/
  - `shape_predictor_68_face_landmarks.dat`
  - `dlib_face_recognition_resnet_model_v1.dat`

**Other Models:**
- These were likely trained/obtained during development
- Check your original project files or backup
- Or retrain if you have the training data

### Option 2: Use Git LFS (Large File Storage)

If you want to store these files in Git:

```bash
# Install Git LFS
git lfs install

# Track large files
git lfs track "*.pkl"
git lfs track "*.dat"
git lfs track "*.onnx"

# Add and commit
git add .gitattributes
git add Admin/sentiment_analysis.pkl
git add Register_App/*.dat Register_App/*.pkl Register_App/*.onnx
git add Webcam/*.dat
git commit -m "Add large model files via Git LFS"
git push
```

**Note:** Git LFS requires a GitHub account with LFS quota (1GB free for personal accounts).

### Option 3: Store Separately

- Upload to cloud storage (Google Drive, Dropbox, etc.)
- Share download links in project documentation
- Or use a model hosting service

## 🔧 Setup After Cloning

After cloning the repository, you need to:

1. **Download the model files** using one of the methods above
2. **Place them in the correct directories:**
   ```
   Admin/sentiment_analysis.pkl
   Register_App/shape_predictor_68_face_landmarks.dat
   Register_App/dlib_face_recognition_resnet_model_v1.dat
   Register_App/dlib_casia_face_classifier.pkl
   Register_App/dlib_casia_label_encoder.pkl
   Register_App/genderage.onnx
   Webcam/shape_predictor_68_face_landmarks.dat
   Webcam/dlib_face_recognition_resnet_model_v1.dat
   ```

3. **Verify the files are in place** before running the applications

## ✅ Verification

You can verify all required files are present by running:

```bash
# Check for required files
ls -lh Admin/sentiment_analysis.pkl
ls -lh Register_App/shape_predictor_68_face_landmarks.dat
ls -lh Register_App/dlib_face_recognition_resnet_model_v1.dat
ls -lh Webcam/shape_predictor_68_face_landmarks.dat
ls -lh Webcam/dlib_face_recognition_resnet_model_v1.dat
```

All files should exist and have reasonable sizes (not 0 bytes).

---

**Note:** The applications will fail to start or function properly without these model files.

