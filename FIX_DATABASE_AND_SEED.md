# Fix "Database unavailable" and empty employees/rooms

Do these two things in order.

---

## Step 1: Create the Realtime Database and set the URL

1. Open this link in your browser (sign in to Google if asked):  
   **https://console.firebase.google.com/u/0/project/visitor-management-8f5b4/database/visitor-management-8f5b4-default-rtdb/data/~2F**

2. If you see **"Create Database"**:
   - Click it.
   - Choose a **location** (e.g. **United States (us-central1)**).
   - Click **Next**, then choose **"Start in test mode"** → **Enable**. Click **Done**.

3. On the Realtime Database page, at the top you’ll see the **database URL**, for example:
   - `https://visitor-management-8f5b4-default-rtdb.firebaseio.com`  
   or  
   - `https://visitor-management-8f5b4-default-rtdb.REGION.firebasedatabase.app`  
   **Copy that URL exactly.**

4. Open these three files and set the URL in each (create the variable if it’s missing):
   - **Register_App/.env** → `FIREBASE_DATABASE_URL=<paste URL>`
   - **Admin/.env** → `FIREBASE_DATABASE_URL=<paste URL>`
   - **Webcam/.env** → `FIREBASE_DATABASE_URL=<paste URL>`

5. **Restart** Register_App, Admin, and Webcam (stop and run `python app.py` again in each folder).

After this, registration should no longer show "Database unavailable."

---

## Step 2: Add one employee and one meeting room (optional but recommended)

So that **"Meeting with an employee"** and **Meeting room** dropdowns are not empty:

1. From the **project root** (the folder that contains `Register_App`, `Admin`, `Webcam`), run:
   ```bash
   python seed_firebase_data.py
   ```
2. You should see:
   - `Added employee: emp1 (Admin User, rohankolachala@gmail.com)`
   - `Added meeting room: room1 (Conference Room A)`
3. **Refresh** the registration page (http://localhost:5001/register). You should see one employee and one room in the dropdowns.

You can still register without this by choosing **"Other"** for purpose and typing e.g. "Testing", and leaving meeting room as "No room selected."
