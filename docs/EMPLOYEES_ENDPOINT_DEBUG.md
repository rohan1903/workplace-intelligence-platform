# `/employees` Endpoint — Testing & Debug Reference

Use this doc (and this chat) for testing and debugging the `/employees` endpoint.

---

## Two apps, two endpoints

| App | Route | Purpose |
|-----|--------|--------|
| **Admin** | `GET /employees` | Renders **HTML** Employee Analytics page (dashboard, table, add/edit/delete). |
| **Register_App** | `GET /employees` | Returns **JSON** list of employees for the registration form dropdown. |

---

## 1. Register_App — JSON API

- **File:** `Register_App/app.py` (around line 424)
- **Handler:** `get_employees()`
- **Response:** `200` → `[{ "id", "name", "department" }, ...]` or `[]` if no employees
- **Errors:** `500` → `{"error": "Failed to fetch employees"}`
- **Data:** Firebase `db_ref.child("employees")` (requires `firebase_credentials.json` and DB URL)

**Quick test (once Register_App is running):**
```bash
curl -s http://localhost:5XXX/employees
```
(Port is whatever Register_App uses, e.g. 5001.)

**Common issues:**
- Firebase not initialized → empty or 500
- `firebase_credentials.json` missing or wrong path
- Network/DB permission errors → check logs for exception in `get_employees`

---

## 2. Admin — HTML Page

- **File:** `Admin/app.py` (around line 6134)
- **Handler:** `employees_list()`
- **Response:** Rendered HTML (Employee Analytics Dashboard)
- **Data:** Mock (`USE_MOCK_DATA`) or Firebase `employees` + `visitors` for analytics

**Quick test (once Admin app is running):**
- Open in browser: `http://localhost:5000/employees`
- Or: `curl -s http://localhost:5000/employees` to see HTML

**Template variables passed:** `employees`, `employee_analytics`, `total_visitors`, `avg_visitors_per_employee`, `top_employee_name`, `top_employee_count`, `departments`

**Common issues:**
- Empty table → check `USE_MOCK_DATA` vs Firebase; ensure `employees` ref returns data
- Visitor counts wrong → logic in `employees_list()` (visits/transactions matching by `employee_name`)

---

## Which app are you testing?

- **Registration form dropdown / API** → Register_App `GET /employees`
- **Admin dashboard employee list/analytics** → Admin `GET /employees`

---

## Running the apps

- **Admin:** typically `python Admin/app.py` or `flask run` from project root (port 5000).
- **Register_App:** run from `Register_App` directory; port may differ (e.g. 5001). Check `Register_App/app.py` or run config.

When reporting issues, specify: which app, expected vs actual response, and any traceback or log lines.
