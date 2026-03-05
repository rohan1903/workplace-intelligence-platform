# Screenshot Guide for Implementation Review

## Quick Steps to Get Screenshots

### Step 1: Check Prerequisites

Make sure you have:
- Python 3.8+ installed
- All dependencies installed (see README.md)
- Firebase credentials file in each directory
- Model files in place (see MODEL_FILES.md)

### Step 2: Start the Applications

You need to run **3 applications** in **separate terminal windows**:

#### Terminal 1: Register App (Port 5001)
```bash
cd /home/rohan/major-project/Register_App
python app.py
```
**Access at:** http://localhost:5001

#### Terminal 2: Admin Dashboard (Port 5000)
```bash
cd /home/rohan/major-project/Admin
python app.py
```
**Access at:** http://localhost:5000

#### Terminal 3: Webcam Check-in (Port 5002)
```bash
cd /home/rohan/major-project/Webcam
python app.py
```
**Access at:** http://localhost:5002

### Step 3: Take Screenshots

#### Screenshot 1: Registration Page
1. Open browser: http://localhost:5001
2. Navigate to the registration page
3. Take a screenshot showing:
   - Registration form
   - Face capture area (or upload option)
   - Form fields (name, email, etc.)

**Tip:** Fill in some sample data to make it look realistic

#### Screenshot 2: Admin Dashboard
1. Open browser: http://localhost:5000
2. Navigate to admin dashboard
3. Take a screenshot showing:
   - Dashboard overview
   - Visitor list/statistics
   - Navigation menu
   - Any charts or analytics (if available)

**Tip:** If you have test data in Firebase, it will show up automatically

#### Screenshot 3: Check-in Flow
1. Open browser: http://localhost:5002
2. Navigate to check-in page
3. Take a screenshot showing:
   - Check-in interface
   - Webcam feed area (or upload option)
   - Check-in form/buttons

**Tip:** Show the check-in process flow if possible

### Step 4: How to Take Screenshots

**Linux:**
- Use `Print Screen` key or `Shift + Print Screen` for area selection
- Or use `gnome-screenshot` command: `gnome-screenshot -a`
- Or use browser extensions for full-page screenshots

**Windows:**
- Use `Windows + Shift + S` for Snipping Tool
- Or `Print Screen` key
- Or browser extensions

**Mac:**
- Use `Command + Shift + 4` for area selection
- Or `Command + Shift + 3` for full screen

### Step 5: Prepare Screenshots for Presentation

1. **Crop and edit** screenshots to focus on important areas
2. **Add labels/annotations** if needed (arrows, text boxes)
3. **Resize** to fit presentation slides (recommended: 1920x1080 or smaller)
4. **Save** with descriptive names:
   - `registration_page.png`
   - `admin_dashboard.png`
   - `checkin_flow.png`

### Alternative: If Applications Don't Run

If you encounter errors:
1. Check error messages in terminal
2. Verify all dependencies are installed
3. Check Firebase credentials
4. Verify model files are present
5. Check .env files are configured

**Workaround:** You can still show:
- Code snippets from the application files
- Architecture diagrams
- UI mockups/wireframes
- Explain the features even if not fully functional

### Quick Test Checklist

Before taking screenshots, verify:
- [ ] All 3 applications start without errors
- [ ] You can access all 3 URLs in browser
- [ ] Pages load correctly
- [ ] Basic navigation works
- [ ] Forms are visible (even if not fully functional)

---

**Note:** For the first review, even basic screenshots showing the UI structure are sufficient. You can mention that full functionality will be demonstrated in the final review.

