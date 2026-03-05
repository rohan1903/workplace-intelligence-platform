# Office Workplace Intelligence — Features Checklist

This document lists features to be added so the project matches the **Office Workplace Intelligence Platform** scope described in the README.

---

## Must Have

| # | Feature | Description | Status |
|---|--------|-------------|--------|
| 1 | **Real-time occupancy** | API/data that returns current number of people in the building (e.g. count of visitors with status "Checked-In") | ☑ Done |
| 2 | **Live occupancy widget** | Dashboard widget showing current occupancy, with optional auto-refresh | ☑ Done |
| 3 | **Occupancy-over-time view** | View occupancy trends (e.g. last 24 hours or by selected date) | ☑ Done |
| 4 | **Meeting room database** | Data model and storage for rooms (name, capacity, floor, amenities) in Firebase/DB | ☑ Done |
| 5 | **Room CRUD in Admin** | Add / edit / delete meeting rooms in the Admin panel | ☑ Done |
| 6 | **Room selection at registration** | During visitor registration, allow choosing or assigning a meeting room; store on visit | ☑ Done |
| 7 | **Room utilization analytics** | Which rooms are used how often (from visits linked to rooms); show in dashboard | ☑ Done |

---

## Should Have

| # | Feature | Description | Status |
|---|--------|-------------|--------|
| 8 | **Room suggestions** | Suggest rooms by visitor count (capacity ≥ count, top N suggestions, e.g. top 3) | ☑ Done |
| 9 | **Peak time prediction** | Use historical check-in data to predict "busy hours" for the next 7 days | ☐ Not started |
| 10 | **Visitor volume forecast** | Expected number of visitors per day for the next week (simple model from past data) | ☐ Not started |
| 11 | **Prediction dashboard section** | "Predicted peak times" / "Next week forecast" in the analytics dashboard | ☐ Not started |

---

## Nice to Have

| # | Feature | Description | Status |
|---|--------|-------------|--------|
| 12 | **Returning visitor detection** | Detect if the same person (email or visitor ID) has visited before | ☐ Not started |
| 13 | **Personalized greeting** | "Welcome back, [Name]!" on check-in or visitor-facing screen when identified | ☐ Not started |
| 14 | **Export occupancy/room data** | Export occupancy or room usage (e.g. CSV/Excel) for reporting | ☑ Done |

---

## Status legend

- ☐ Not started  
- ◐ In progress  
- ☑ Done  

---

## Gaps & limitations (backlog)

These items address known limitations. Implementable ones are listed as features; others are documentation/scope.

### Security

| # | Item | Type | Priority | Notes |
|---|------|------|----------|--------|
| G1 | **Liveness / anti-spoofing** | Feature | Should have | Optional layer (e.g. blink/smile or passive liveness) to mitigate photo/video attacks. |
| G2 | **Tailgating detection or alerting** | Feature | Nice to have | Capacity/sensor at gate or "N entered, 1 scanned" alert; no automatic mitigation today. |
| G3 | **Face capture quality checks** | Feature | Nice to have | Reject blur/poor lighting at registration; document recommended conditions. |
| G4 | **Time exceeded actions** | Feature | Should have | Notify host, revoke access for visit, or mark status; today only visibility on dashboard. |

### Workspace & scale

| # | Item | Type | Priority | Notes |
|---|------|------|----------|--------|
| G5 | **Employee presence (occupancy)** | Feature | Nice to have | Optional WiFi/badge feed so "occupancy" can include employees; today visitors only. |
| G6 | **Multi-gate occupancy** | Feature | Should have | gate_id on events, aggregate by building; tested single-gate only today. |
| G7 | **Simple room booking** | Feature | Should have | Time slots + link to visit; README says "suggestions only," no booking yet. |
| G8 | **Database abstraction** | Feature | Nice to have | Repository layer + second backend (e.g. Postgres) to reduce Firebase lock-in. |

### Product & ops

| # | Item | Type | Priority | Notes |
|---|------|------|----------|--------|
| G9 | **Mobile / PWA** | Feature | Nice to have | Responsive web today; optional PWA or thin native app. |
| G10 | **Per-gate auth policy** | Feature | Nice to have | Different auth mode per gate (e.g. hybrid at main, QR-only at delivery). |
| G11 | **Production & liability disclaimer** | Documentation | Must have | README: production checklist, "no warranty / use at your own risk." |
| G12 | **Load / scale testing** | Feature | Nice to have | Document limits; basic load tests for registration, check-in, dashboard. |

---

## Notes

- **Must Have (1–7)** — Core workspace intelligence; needed to match README and positioning.
- **Should Have (8–11)** — Room optimization and predictive analytics for stronger differentiation.
- **Nice to Have (12–14)** — Improves experience and reporting; can be phased later.
- **Gaps (G1–G12)** — Address limitations from security review and README scope; mix of features and docs.

*Last updated: [Add date when you update]*
