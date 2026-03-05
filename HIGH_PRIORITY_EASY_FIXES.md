# High-priority, easy-fix gaps

Gaps that are **high impact** and **quick to implement**. Ordered by priority (must-have first) then effort.

---

## Done

| Item | What was done |
|------|----------------|
| **G11 Production & liability disclaimer** | Added "Production use and disclaimer" section in README (no warranty, production checklist). |
| **#3 Occupancy by selected date/range** | Dashboard now has "Occupancy over selected period" chart; single day = hourly buckets, multi-day = daily buckets; uses current time filter. |
| **#8 Room suggestions** | `GET /api/rooms/suggest?count=5&top=3` returns rooms with capacity ≥ count, sorted by capacity (best fit). |
| **G4 Time exceeded – notify host** | "Notify host" button on each time-exceeded visitor; `POST /api/notify_host_time_exceeded` sends email to host (employee) via SMTP. |
| **#14 Export occupancy/room data** | Dashboard: "Export CSV" for room utilization; "Export last 24h CSV" and "Export selected period CSV" for occupancy. |

---

## Medium priority, still relatively easy

### 4. **Peak time prediction (#9 – Should Have)**  
**Effort: ~2–3 hours**

- **Gap:** No “predicted busy hours” for the next 7 days.
- **Fix:** Use last 4 weeks’ hourly check-in counts by weekday; for each hour of the next 7 days compute a simple average (or max) and return as “predicted peak” (e.g. “Tue 14:00–15:00”). Show in a small dashboard block or API.
- **Where:** `get_visitor_analytics()` or a small helper; new dashboard card or extend existing.

---

### 5. **Visitor volume forecast (#10 – Should Have)**  
**Effort: ~2–3 hours**

- **Gap:** No “expected visitors per day next week.”
- **Fix:** By day-of-week, average past 4 weeks’ daily counts; return next 7 days’ expected counts. Simple model, no ML. Expose in analytics and optionally in dashboard.
- **Where:** Same as #9; one more block or API.

---

## Summary

| Priority | Item | Effort | Category |
|----------|------|--------|----------|
| 1 | Room suggestions (#8) | Easy | Should Have |
| 2 | Time exceeded notify host (G4) | Easy | Should Have |
| 3 | Export occupancy/rooms (#14) | Easy | Nice to Have |
| 4 | Peak time prediction (#9) | Medium | Should Have |
| 5 | Visitor volume forecast (#10) | Medium | Should Have |

**Already addressed:** G11 (disclaimer in README), #3 occupancy by selected date/range (second chart on dashboard).
