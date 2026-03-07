# Admin Dashboard — Full Functionality Test Guide

Use this checklist to test **all** Admin dashboard features end-to-end. Run the Admin app from the project root: `cd Admin` then `python app.py`. Base URL: **http://localhost:5000**.

---

## Prerequisites

- [ ] Admin app running on port 5000
- [ ] `USE_MOCK_DATA=True` in `Admin/.env` for testing without Firebase (or `False` with Firebase configured)
- [ ] Optional: `sentiment_analysis.pkl` in `Admin/` for feedback analysis; model files in Register_App/Webcam for full flow

---

## 1. Home (Index) — `/`

| # | Action | Expected |
|---|--------|----------|
| 1.1 | Open http://localhost:5000/ | Page loads with "Admin Dashboard" and "Workplace Intelligence Control Center" |
| 1.2 | Click **Visitors** card | Redirects to `/visitors` |
| 1.3 | Go back, click **Analytics Dashboard** | Redirects to `/dashboard` |
| 1.4 | Go back, click **Bulk Invitations** | Redirects to `/upload_invitations` |
| 1.5 | Go back, click **Blacklist** | Redirects to `/blacklist` |
| 1.6 | Go back, click **Meeting Rooms** | Redirects to `/rooms` |
| 1.7 | Go back, click **Employees** | Redirects to `/employees` |
| 1.8 | Go back, click **Feedback Analysis** | Redirects to `/feedback_analysis` |

---

## 2. Analytics Dashboard — `/dashboard`

| # | Action | Expected |
|---|--------|----------|
| 2.1 | Open `/dashboard` | Page shows "Workspace Intelligence Analytics", metric cards, and charts |
| 2.2 | Verify metrics | At least: Total Visitors, Checked-In, Checked-Out, Exceeded (or similar) and filter description text |
| 2.3 | Click **Today** | Time filter updates; chart/data reflect "today" |
| 2.4 | Click **This Week** | Filter shows "This Week" |
| 2.5 | Click **This Month** | Filter shows "This Month" |
| 2.6 | Use **Custom range**: set start date, end date, start time, end time; apply | Description and data update to custom range |
| 2.7 | Change **Chart type** (if tabs: All / Check-ins / etc.) | Chart content updates |
| 2.8 | Check **Occupancy widget** (current occupancy count) | Shows a number; if mock data, may be 0 or sample value |
| 2.9 | **Export** (if button present) | CSV/Excel download or export action works |
| 2.10 | Click **Blacklisted** link in header | Goes to `/blacklist` |
| 2.11 | Click **View Visitors** link | Goes to `/visitors` |

---

## 3. Bulk Invitations — `/upload_invitations` and `/upload_invites`

| # | Action | Expected |
|---|--------|----------|
| 3.1 | Open `/upload_invitations` | Upload form with file input and "Upload and Send Invitations" (or similar) |
| 3.2 | Submit without file | Validation error or no upload |
| 3.3 | Upload valid Excel (`.xlsx`/`.xls`) with **Email** column | Success message; if email configured, invitations sent (or mock success) |

---

## 4. Visitors List — `/visitors`

| # | Action | Expected |
|---|--------|----------|
| 4.1 | Open `/visitors` | Table of visitors with columns (e.g. Name, Contact, Purpose, Duration, Status, Blacklist, Actions) |
| 4.2 | Use **Search** by name or contact | List filters to matching rows |
| 4.3 | Use **Status filter** (All / Checked-In / Checked-Out / Exceeded) | List filters by status |
| 4.4 | Set **Date range** (start_date, end_date) and apply | List filtered to visits in range |
| 4.5 | Use **Time range** (e.g. all, today, week, month, &lt;1hr, &lt;3hr, &lt;6hr) | List updates accordingly |
| 4.6 | If multiple pages: **Pagination** next/prev | Page changes, URL has `page=` |
| 4.7 | Click **View** / visitor name for one row | Opens `/visitor/<visitor_id>` |
| 4.8 | **Toggle blacklist** (Enable/Disable) for a visitor | Request succeeds; list or detail reflects new blacklist status |

---

## 5. Visitor Detail — `/visitor/<visitor_id>`

| # | Action | Expected |
|---|--------|----------|
| 5.1 | Open a visitor detail from `/visitors` | Full profile: name, contact, photo if any, visits, transactions, blacklist status |
| 5.2 | Click **Approve** (if available) | POST to `/visitor/<id>/approve`; status becomes Approved |
| 5.3 | Click **Reject** (if available) | POST to `/visitor/<id>/reject`; status becomes Rejected |
| 5.4 | Click **Check In** (if available) | POST to `/visitor/<id>/checkin`; status Checked-In, check_in_time and expected_checkout_time set |
| 5.5 | Click **Check Out** (if available) | POST to `/visitor/<id>/checkout`; status Checked-Out, check_out_time set |
| 5.6 | Toggle **Blacklist** (add to / remove from blacklist) | POST to `/blacklist/<visitor_id>`; blacklist status and reason update |
| 5.7 | Open `/visitor/invalid_id_12345` | 404 "Visitor record not found" (or similar) |

---

## 6. Blacklist Page — `/blacklist`

| # | Action | Expected |
|---|--------|----------|
| 6.1 | Open `/blacklist` | Page "Blacklisted Individuals"; list of blacklisted visitors or "No blacklisted individuals" |
| 6.2 | If list not empty: check total count and details (name, reason, contact, etc.) | Data matches visitor records |
| 6.3 | Click **View full profile** for one | Goes to `/visitor/<visitor_id>` |
| 6.4 | Click **Remove from blacklist** | Visitor removed from blacklist; list updates or redirects |
| 6.5 | Pagination (if multiple pages) | Next/prev works |

---

## 7. Feedback Analysis — `/feedback_analysis`

| # | Action | Expected |
|---|--------|----------|
| 7.1 | Open `/feedback_analysis` | "Visitor Feedback Sentiment Dashboard" (or similar); sentiment chart and/or list of feedbacks |
| 7.2 | If sentiment model loaded: check Positive / Neutral / Negative counts and chart | Values and chart render |
| 7.3 | If no model: page still loads (may show zeros or "Neutral" only) | No crash |

---

## 8. Meeting Rooms — `/rooms` and APIs

| # | Action | Expected |
|---|--------|----------|
| 8.1 | Open `/rooms` | Table of rooms (Name, Capacity, Floor, Amenities, Actions) or "No rooms yet" |
| 8.2 | Click **Add Room** | Modal opens with fields: Name, Capacity, Floor, Amenities |
| 8.3 | Fill and **Save** new room | Room appears in table (and in Firebase if not mock) |
| 8.4 | Click **Edit** on a room | Modal opens with pre-filled data; save updates row |
| 8.5 | Click **Delete** on a room | Room removed from list (and DB if not mock) |
| 8.6 | **API** `GET /api/rooms/list` | JSON list of rooms |
| 8.7 | **API** `POST /api/rooms` with JSON `{name, capacity, floor, amenities}` | New room created; response success |
| 8.8 | **API** `PUT /api/rooms/<room_id>` with JSON | Room updated |
| 8.9 | **API** `DELETE /api/rooms/<room_id>` | Room deleted |
| 8.10 | **API** `GET /api/rooms/suggest?count=N` | JSON with `suggestions` array (rooms by capacity ≥ N) |

---

## 9. Employees — `/employees` and APIs

| # | Action | Expected |
|---|--------|----------|
| 9.1 | Open `/employees` | Employee list/analytics: names, departments, visitor counts, "Top employee", etc. |
| 9.2 | **Add employee** (form or modal): name, email, department, role, contact | New employee appears in list (and in Firebase if not mock) |
| 9.3 | **Edit employee**: change name/department/role/contact and save | Row updates |
| 9.4 | **Delete employee** | Employee removed from list |
| 9.5 | Click **View visitors** for an employee | Opens `/employee/visitors/<emp_id>` with list of visitors linked to that employee |
| 9.6 | **API** `GET /get_employee/<emp_id>` | JSON with employee details |
| 9.7 | **API** `POST /add_employee` with JSON | Returns success and `emp_id` |
| 9.8 | **API** `POST /edit_employee/<emp_id>` with JSON | Success |
| 9.9 | **API** `POST /delete_employee/<emp_id>` | Success |

---

## 10. APIs (Occupancy & Notify)

| # | Action | Expected |
|---|--------|----------|
| 10.1 | `GET /api/occupancy` | JSON: `current_occupancy` (number), `timestamp` (ISO) |
| 10.2 | `GET /api/occupancy_over_time` | JSON: `occupancy_over_time_last24` with `labels` and `data` (or similar) |
| 10.3 | `POST /api/notify_host_time_exceeded` with JSON body (e.g. visit/visitor info) | Success or appropriate error (implementation-dependent) |

---

## 11. Admin-Side Registration — `/register`

| # | Action | Expected |
|---|--------|----------|
| 11.1 | Open `/register` (GET) | Registration form (name, contact, purpose, etc.) |
| 11.2 | Submit form (POST) | Success message; visitor created in data (or mock) |

---

## 12. Uploaded Image Serving

| # | Action | Expected |
|---|--------|----------|
| 12.1 | If you have a visitor with `profile_link` or photo path: open `/uploads_reg/<path>` with a valid filename | Image loads or 404 if file missing |

---

## Quick Run (manual)

1. Start Admin: `cd Admin` → `python app.py`
2. In browser: **/** → **/dashboard** → **/visitors** → open one **/visitor/<id>** → test Approve/Reject/Check In/Check Out/Blacklist
3. **/blacklist** → remove one if any
4. **/rooms** → Add room, Edit, Delete
5. **/employees** → Add, Edit, Delete, View visitors
6. **/feedback_analysis** → confirm page loads
7. **/upload_invitations** → try upload with sample Excel (with Email column)

---

## Automated API Smoke Test (optional)

From project root or Admin directory:

```bash
cd Admin
python tests/test_occupancy_api.py
```

This checks `GET /api/occupancy` returns 200 and has `current_occupancy` and `timestamp`. For full API coverage you can extend this script or use a tool like `curl`/Postman against the endpoints in sections 8, 9, and 10.

---

*Last updated: March 2025. Aligns with Admin app routes and FEATURES_CHECKLIST.md.*
