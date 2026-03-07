# Quick Browser Testing Reference Card

## 🚀 Quick Start

1. Open http://localhost:5000/visitors in browser
2. Press **F12** to open Developer Tools
3. Click **Console** tab
4. Look for **red error messages**

---

## 📸 Screenshots Needed

### Screenshot 1: `/visitors` page
- Full page view
- Console tab visible
- Any error messages

### Screenshot 2: `/employees` page  
- Full page view
- Console tab visible
- Any error messages

### Screenshot 3: Employee Modal
- Click "Add Employee" button
- Take screenshot of open modal
- Console tab visible

---

## ⚡ Quick Tests

### `/visitors` Page (30 seconds)

| Action | Expected Result | Mark if Works |
|--------|----------------|---------------|
| Page loads | No console errors | ⬜ |
| Click "Apply Filters" | Page reloads with filters | ⬜ |
| Change Status dropdown | No errors | ⬜ |
| Click any visitor action button | Action happens | ⬜ |

**If any ❌**: Copy exact error message from Console

---

### `/employees` Page (30 seconds)

| Action | Expected Result | Mark if Works |
|--------|----------------|---------------|
| Page loads | No console errors | ⬜ |
| Click "Add Employee" | Modal opens | ⬜ |
| Click Edit icon on row | Modal opens with data | ⬜ |
| Type in search box | Table filters | ⬜ |

**If any ❌**: Copy exact error message from Console

---

## 🔍 What to Look For in Console

### ✅ Good (No errors):
```
(Console is empty or only has info messages)
```

### ⚠️ Warning (Cosmetic issues only):
```
Failed to load resource: https://cdn.tailwindcss.com
(Yellow warning icon - CSS might not load, but JS still works)
```

### ❌ BAD (JavaScript errors):
```javascript
Uncaught ReferenceError: applyFilters is not defined
Uncaught TypeError: Cannot read property 'value' of null
```

---

## 📋 Error Reporting Template

If you find errors, copy this and fill in:

```
## Browser Testing Results

**Browser**: Chrome/Firefox/Safari [Version: ___]
**Date**: March 7, 2026

### `/visitors` Page

Console Errors:
```
[Paste exact error text here]
```

Apply Filters Button: ✅ Works / ❌ Doesn't work
Status Dropdown: ✅ Works / ❌ Doesn't work

### `/employees` Page

Console Errors:
```
[Paste exact error text here]
```

Add Employee Button: ✅ Works / ❌ Doesn't work
Edit Employee Button: ✅ Works / ❌ Doesn't work
Modal Opens: ✅ Yes / ❌ No

### Screenshots
[Attach screenshots here]
```

---

## 🎯 Common Issues & Quick Fixes

### Issue: "applyFilters is not defined"
**Cause**: JavaScript didn't load  
**Fix**: Check if page fully loaded, try refresh

### Issue: "Cannot read property 'value' of null"
**Cause**: HTML element missing  
**Fix**: Report which button/field you clicked

### Issue: Modal doesn't open
**Check**: Look in Console for fetch errors  
**Check**: Is there a 404 error in Network tab?

### Issue: Nothing happens when clicking buttons
**Check**: Console for errors  
**Try**: Click slowly, wait 2 seconds, check Console

---

## 🆘 If Stuck

1. **Refresh page** (Ctrl+R or Cmd+R)
2. **Clear Console** (trash icon in Console tab)
3. **Try action again**
4. **Take screenshot of error**
5. **Report back with error text**

---

## 📱 How to Open Console

- **Windows/Linux**: F12 or Ctrl+Shift+I
- **Mac**: Cmd+Option+I
- **Then click**: "Console" tab at top

---

## ⏱️ Total Testing Time: ~5 minutes

- Visitors page: 2 minutes
- Employees page: 2 minutes  
- Screenshots: 1 minute

---

**Need help?** Share:
1. Exact error message from Console
2. Which button you clicked
3. Screenshot of page + Console

**Created**: March 7, 2026  
**For**: Manual browser testing when automation unavailable
