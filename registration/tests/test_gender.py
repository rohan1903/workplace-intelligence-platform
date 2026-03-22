"""Gender model test. Run from registration/: python tests/test_gender.py. Requires genderage.onnx in registration/."""
import os
import sys
from pathlib import Path

_register_app_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_register_app_dir))
os.chdir(_register_app_dir)

import cv2
import numpy as np
import onnxruntime

# Load ONNX gender model (from registration directory)
model_path = _register_app_dir / "genderage.onnx"
if not model_path.exists():
    print(f"[FAIL] Model not found: {model_path}")
    sys.exit(1)
session = onnxruntime.InferenceSession(str(model_path))

# Gender Detection Function
def detect_gender(img_cv2):
    try:
        face_img = cv2.resize(img_cv2, (96, 96))  # Model expects 96x96
        face_img = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
        face_img = np.transpose(face_img, (2, 0, 1))  # Shape: (3, 96, 96)
        face_img = np.expand_dims(face_img, axis=0).astype(np.float32)

        outputs = session.run(None, {"data": face_img})
        print("Model outputs:", len(outputs))  # Debug output length

        # Handling different output formats
        if len(outputs) == 1:
            output = outputs[0]
            if isinstance(output, list) and len(output) > 1:
                gender_index = np.argmax(output[1])
            else:
                gender_index = np.argmax(output[0])
        elif len(outputs) > 1:
            gender_output = outputs[1]  # Use second output if present
            gender_index = np.argmax(gender_output[0])
        else:
            print("[FAIL] No outputs returned from model.")
            return "Unknown"

        return "Male" if gender_index == 1 else "Female"

    except Exception as e:
        print(f"Error during gender detection: {e}")
        return "Unknown"

# Start Webcam
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        print("[FAIL] Failed to grab frame")
        break

    # Basic center crop for approximation
    h, w = frame.shape[:2]
    center_crop = frame[h//4:h*3//4, w//4:w*3//4]

    gender = detect_gender(center_crop)

    # Draw gender result
    cv2.putText(frame, f"Gender: {gender}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)

    # Display webcam
    cv2.imshow("Gender Detection", frame)

    # Exit on pressing 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Cleanup
cap.release()
cv2.destroyAllWindows()
