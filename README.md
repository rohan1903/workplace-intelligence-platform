# Workplace Intelligence Platform with Hybrid Face–QR Authentication

## Abstract

This repository presents an **open-source Workplace Intelligence Platform with Hybrid Face–QR Authentication** that combines secure visitor management with comprehensive workspace analytics. The system implements a **Hybrid Face–QR Visitor Authentication Protocol (HFQVAP)** that binds a per-visit QR token to biometric face verification through a five-state QR lifecycle with automatic invalidation on misuse. Beyond access control, the platform provides real-time building occupancy tracking, meeting room optimization, predictive visitor pattern analytics, and workspace utilization insights.

Unlike commercial solutions (Envoy, Proxyclick) that are proprietary and cloud-based, this platform is fully open-source, self-hosted, and research-focused—making it ideal for academic institutions and privacy-conscious organizations. The system is configurable across three protocol variants (hybrid, face-only, QR-only) under the same deployment, enabling direct comparison of security properties. All gate events are logged with protocol metadata for post-hoc analysis and workspace intelligence.

## Research Problem

Modern organizations face dual challenges: ensuring secure visitor access control while optimizing workspace utilization. Traditional visitor management systems present three key limitations:

1. **Security Gaps**: Single-factor authentication (QR-only or face-only) leaves specific threats unaddressed:
   - **QR-only:** Any holder of the QR image can authenticate. A credential stolen inside the premises can be reused at departure.
   - **Face-only:** Visually similar individuals (twins, look-alikes) produce ambiguous matches without secondary verification.

2. **Proprietary Constraints**: Commercial solutions lack transparency, customization, and self-hosting options critical for research and privacy-sensitive deployments.

3. **Limited Intelligence**: Most systems focus solely on access control without providing workspace optimization insights such as occupancy analytics, room utilization, and predictive patterns.

This work investigates whether a hybrid protocol — cross-verifying face and QR with a token state machine and invalidation rules — addresses security weaknesses while simultaneously providing actionable workspace intelligence for building optimization.

## Contributions

- **Hybrid Authentication Protocol (HFQVAP).** A hybrid face–QR authentication protocol with a five-state QR lifecycle (UNUSED, CHECKIN_USED, ASSUMED_SCANNED, CHECKOUT_USED, INVALIDATED), defined transition rules, and six operational invariants.

- **Workspace Intelligence Module.** Real-time building occupancy tracking, meeting room optimization with AI-powered suggestions, predictive visitor pattern analytics, and workspace utilization insights integrated directly into the visitor management workflow.

- **Threat Analysis.** A qualitative threat model covering six categories (QR theft, QR replay, face spoofing, no-departure, post-entry QR theft, twin ambiguity) with per-threat comparison across all three variants. Limitations — notably liveness detection and tailgating — are explicitly scoped out.

- **Open-Source Platform.** A fully open-source, self-hosted solution with comprehensive documentation, enabling research, customization, and privacy-conscious deployments without vendor lock-in.

- **Comparative Evaluation Framework.** A single codebase supporting three authentication modes (`hybrid`, `face_only`, `qr_only`) switchable via environment variable, with structured event logging (`auth_mode`, `protocol_config`) for reproducible comparison.

## System Architecture

```
├── docs/
│   ├── SETUP_GUIDE.md      # Full setup instructions
│   └── TEST_PLAN.md        # End-to-end test plan with all edge cases
├── registration/            # Visitor registration, QR issuance, host approval
│   ├── app.py               # Flask (Port 5001)
│   └── templates/
├── admin/                   # Dashboard, analytics, access-control list
│   ├── app.py               # Flask (Port 5000)
│   └── templates/
└── gate/                    # Gate — protocol engine (AUTH_MODE configurable)
    ├── app.py               # Flask (Port 5002)
    ├── qr_module.py         # QR generation, validation, state machine
    └── templates/
```

| Component | Responsibility |
|-----------|---------------|
| registration | Visitor pre-registration, face embedding capture (dlib ResNet, 128-D), per-visit QR token generation (`secrets.token_urlsafe(32)`, JSON-encoded, visit-bound), host approval workflow, meeting room selection. |
| admin | Visitor and employee management, blacklist enforcement, feedback sentiment analysis, comprehensive visit analytics, **real-time occupancy dashboard**, **meeting room management**, **predictive analytics**, workspace intelligence insights. |
| gate | Gate endpoint implementing the three protocol variants: face matching, QR parsing and state management, cross-verification, invalidation logic, structured event logging, and occupancy tracking. |

Data is persisted in Firebase Realtime Database. All three components share the same database instance, enabling real-time synchronization of visitor data, occupancy metrics, and workspace analytics.

## Protocol Variants

The gate supports three modes selected via `AUTH_MODE`:

| Variant | Value | Gate behavior | QR state machine |
|---------|-------|---------------|------------------|
| Hybrid | `hybrid` | Face match + QR validation; cross-verification that both identify the same visitor. | Active: full lifecycle with invalidation on mismatch and stolen-QR detection. |
| Face-only | `face_only` | Face match only; QR data ignored. | Inactive: no state updates. |
| QR-only | `qr_only` | Valid QR token only; face not required. | Partial: token validated (expiry, state) but no face cross-check. |

The hybrid variant enforces six invariants: dual binding (face and QR must agree), single use per phase, mismatch invalidation, stolen-QR detection (face-only departure after QR arrival), blacklist enforcement, and token expiry. These invariants are enforced at the gate layer.

## Workspace Intelligence Features

### Real-Time Occupancy Tracking

- **Live Building Occupancy**: Real-time count of visitors currently in the building
- **Hourly Distribution**: Track visitor patterns throughout the day
- **Peak Time Identification**: Automatically identify busiest hours
- **Occupancy Trends**: Visualize occupancy patterns over time

### Meeting Room Optimization

- **Room Database**: Manage meeting rooms with capacity, floor, and amenities
- **AI-Powered Suggestions**: Automatically suggest optimal rooms based on visitor count
- **Room Utilization Analytics**: Track which rooms are most used
- **Capacity Matching**: Match visitor groups to appropriately sized rooms
- **Availability Tracking**: Monitor room usage patterns

### Predictive Analytics

- **Peak Time Prediction**: Forecast busy hours for the next week based on historical patterns
- **Visitor Volume Forecasting**: Predict expected visitor counts by day
- **Day-of-Week Patterns**: Identify recurring patterns (e.g., "Tuesdays are busiest")
- **Trend Analysis**: Analyze visitor patterns over time

### Workspace Utilization Insights

- **Department Analytics**: Track which departments receive most visitors
- **Purpose Distribution**: Analyze visit purposes (meetings, interviews, deliveries, etc.)
- **Time-Based Trends**: Understand visitor patterns by hour, day, week, month
- **Resource Utilization**: Identify underutilized or overutilized spaces

### Enhanced Analytics Dashboard

- **Comprehensive Metrics**: Total visitors, active visitors, completed visits, time exceeded alerts
- **Interactive Charts**: Purpose distribution, status overview, department-wise analysis, hourly trends
- **Custom Time Filters**: Analyze data for today, this week, this month, custom date ranges
- **Real-Time Updates**: Live dashboard updates with latest visitor data

## Threat Model

Six threat categories are analyzed:

| Threat | Face-only | QR-only | Hybrid |
|--------|-----------|---------|--------|
| T1. QR theft / sharing | N/A | Vulnerable | Mitigated (face–QR binding) |
| T2. QR replay | N/A | Mitigated (expiry + state) | Mitigated (expiry + state) |
| T3. Face spoofing | Out of scope (liveness assumption) | N/A | Same as face-only |
| T4. No departure | Operational (audit only) | Operational (audit only) | Operational (audit only) |
| T5. Post-entry QR theft | N/A | Vulnerable | Mitigated (invalidation on face-only departure) |
| T6. Twin / ambiguous face | Vulnerable | N/A | Mitigated (QR disambiguation) |

The hybrid variant addresses T1, T5, and T6 relative to the single-factor baselines. T3 (face spoofing) is an explicit non-goal: liveness detection is orthogonal to the protocol and is noted as an assumption. T4 (no departure) is operational and not mitigated by any variant.

## Evaluation

### Measured properties

| Property | Procedure | Applicable variants |
|----------|-----------|---------------------|
| Replay resistance | Resubmit a previously used QR; verify state-machine rejection. | QR-only, hybrid |
| Impersonation detection | Present a valid QR with a non-matching face; verify denial and QR invalidation. | Hybrid |
| Stolen-credential detection | Use QR at arrival, face-only at departure; verify QR invalidation and security alert. | Hybrid |
| Twin disambiguation | Present two visitors within the face-distance ambiguity threshold; verify QR-based resolution. | Face-only vs. hybrid |
| Gate response time | Measure time from HTTP request to response under each variant. | All |

### Event logs

| Firebase path | Contents |
|---------------|----------|
| `research_protocol_events/` | Arrival, departure, and invalidation events with `auth_mode`, `protocol_config`, `timestamp`, `visitor_id`, `visit_id`. |
| `visitors/{id}/visits/{id}/qr_state` | QR state snapshot: `status`, `scan_count`, `auth_method`, `invalidated_at`, `invalidated_reason`. |
| `visitors/{id}/visits/{id}/qr_scan_log/` | Chronological scan events: `scan_type`, `auth_mode`, `ip`, `face_distance`. |
| `visitors/{id}/transactions/` | Per-action log: `action`, `auth_mode`, `face_distance`, `timestamp`. |
| `security_alerts/` | Alert records: `alert_type` (QR_FACE_MISMATCH, QR_POSSIBLY_STOLEN, TWIN_DETECTED). |

### Comparison method

1. Deploy the gate under each `AUTH_MODE` in sequence or on parallel instances.
2. Execute a fixed set of scenarios: normal visit, QR reuse, QR presented by wrong person, face-only departure after QR arrival, twin presentation.
3. Export `research_protocol_events` and `security_alerts` from Firebase (console, REST API, or SDK).
4. Compare across variants: (a) threat detection coverage, (b) false rejection of legitimate visitors, (c) response latency.

## Reproducibility

### Switching modes

```bash
AUTH_MODE=hybrid    python gate/app.py   # default
AUTH_MODE=face_only python gate/app.py   # baseline A
AUTH_MODE=qr_only   python gate/app.py   # baseline B
```

Alternatively, set `AUTH_MODE` in `gate/.env`. The active mode is validated and logged at startup.

### Log locations

- **Protocol events:** `research_protocol_events/` — each record includes `protocol_config` (which mode was active).
- **QR state:** `visitors/{id}/visits/{id}/qr_state` and `qr_scan_log/`.
- **Security alerts:** `security_alerts/` at database root.

---

## Setup

### Prerequisites

- Python 3.8+
- Firebase Realtime Database credentials (`firebase_credentials.json`)
- Camera or uploaded images for face registration
- Pre-trained models (included): `shape_predictor_68_face_landmarks.dat`, `dlib_face_recognition_resnet_model_v1.dat`, `sentiment_analysis.pkl`, `genderage.onnx`

### Installation

```bash
python3 -m venv venv && source venv/bin/activate

pip install -r registration/requirements.txt
pip install -r admin/requirements.txt
pip install -r gate/requirements.txt
```

dlib requires CMake and platform libraries (`sudo apt-get install cmake libopenblas-dev liblapack-dev` on Debian/Ubuntu). See [dlib.net](http://dlib.net/compile.html) or use `conda install -c conda-forge dlib`. Full setup instructions in [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md).

### Configuration

Create `.env` in each component directory:

**registration/.env:**
```
SECRET_KEY=<secret>
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=<email>
EMAIL_PASS=<app_password>
GEMINI_API_KEY=<key>
ADMIN_APP_URL=http://localhost:5000
```
(ADMIN_APP_URL is used to fetch meeting rooms for the registration dropdown.)

**admin/.env:**
```
SECRET_KEY=<secret>
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=<email>
EMAIL_PASS=<app_password>
REGISTRATION_APP_URL=http://localhost:5001
```

**gate/.env:**
```
SECRET_KEY=<secret>
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=<email>
EMAIL_PASS=<app_password>
COMPANY_IP=127.0.0.1
AUTH_MODE=hybrid
```

### Running

```bash
cd registration && python app.py   # Port 5001
cd admin && python app.py          # Port 5000
cd gate && python app.py           # Port 5002
```

Place `firebase_credentials.json` in each component directory before starting.

### Showcasing the platform

When demoing the system (e.g. Register + Gate in real time with fresh visitors):

- **Register & Gate:** Use real Firebase (no mock). Register a new visitor with face scan, get approved, then check in/out at the gate so the flow is live.
- **Admin dashboard:** Run Admin with **`USE_MOCK_DATA=True`** (default). The dashboard then shows rich, stable mock data (visitors, analytics, blacklist, occupancy) so you can showcase all features (filters, search, blacklist, analytics, room management) without pre-populating real data. Mock data is fixed per server run so it does not change on every refresh.
- **Admin automated tests (mock):** From `admin/`, run `python -m unittest tests.test_admin_dashboard_mock -v`. This forces mock mode for the test process; keep `USE_MOCK_DATA=True` in `admin/.env` (or unset) when running the server the same way.
- **Admin manual QA:** Use [docs/TEST_PLAN.md](docs/TEST_PLAN.md) Phase 9 in the browser. With mock data, listed visitors are generated (not live Firebase registrations); blacklist notification email only sends if SMTP is configured in `admin/.env`.
- **Optional:** To show the same visitors you just registered in the dashboard, run Admin with **`USE_MOCK_DATA=False`** and use the same Firebase project; the dashboard will read live data from Firebase.

## Key Features

### Security & Authentication
- ✅ Hybrid Face-QR Authentication Protocol (HFQVAP)
- ✅ Three authentication modes (hybrid, face-only, QR-only)
- ✅ Automatic QR invalidation on misuse
- ✅ Twin disambiguation via QR verification
- ✅ Comprehensive threat model and security alerts
- ✅ Blacklist management

### Workspace Intelligence
- ✅ Real-time building occupancy tracking
- ✅ Meeting room optimization and suggestions
- ✅ Predictive visitor pattern analytics
- ✅ Room utilization insights
- ✅ Department-wise visitor analytics
- ✅ Peak time predictions

### Visitor Management
- ✅ Visitor registration with face capture
- ✅ QR code generation and management
- ✅ Host approval workflow
- ✅ Check-in/check-out automation
- ✅ Visitor feedback and sentiment analysis
- ✅ Bulk invitation system

### Analytics & Reporting
- ✅ Comprehensive analytics dashboard
- ✅ Custom time range filters
- ✅ Interactive charts and visualizations
- ✅ Export capabilities
- ✅ Real-time data updates

## Scope and Limitations

### Security Limitations
- **Liveness detection** is not implemented. The threat model assumes face spoofing is handled by an orthogonal mechanism and explicitly scopes it out (T3).
- **Tailgating / no-departure** (T4) is an operational concern not addressed by any of the three protocol variants; the system provides audit logs but no automatic mitigation.
- **Face recognition accuracy** depends on dlib's pre-trained ResNet model and the quality of registered embeddings. The protocol evaluation focuses on the authentication logic, not on the underlying biometric performance.
- **QR token security** relies on `secrets.token_urlsafe(32)` for generation and HTTPS for transport in deployment. The protocol does not introduce novel cryptographic constructions.

### Workspace Intelligence Limitations
- **Predictive models** use simple time series analysis (moving average, linear regression). Machine learning models could enhance accuracy.
- **Room optimization** doesn't include real-time booking system integration (suggestions only).
- **Occupancy tracking** is limited to visitors; employee presence is not tracked.
- **Multi-gate support** requires additional configuration for building-wide occupancy.

### Scalability
- The system was tested in a single-gate, single-database configuration. Multi-gate or federated deployments are not evaluated.
- Firebase dependency (could support other databases in future).
- No mobile app (web-based interface only).

## Production use and disclaimer

This project is provided for **academic and research purposes**. If you use it in production or for access control:

- **Production checklist:** Use HTTPS, replace all default `SECRET_KEY` values, restrict Firebase credentials, and run behind a proper WSGI server (e.g. Gunicorn). See Security Notes below.
- **No warranty:** The software is provided “as is” without warranty of any kind. Use at your own risk. The maintainers are not liable for any loss or damage arising from its use.

## Security Notes

- Replace default `SECRET_KEY` values before any non-local deployment.
- Do not commit `firebase_credentials.json` to version control.
- Use HTTPS in production to protect QR tokens in transit.

## Comparison with Commercial Solutions

| Feature | Our Platform | Envoy | Proxyclick/Eptura |
|---------|------------|-------|-------------------|
| **Open-source** | ✅ Yes | ❌ No | ❌ No |
| **Self-hosted** | ✅ Yes | ❌ No | ⚠️ Limited |
| **Hybrid Protocol** | ✅ Yes (HFQVAP) | ❌ No | ⚠️ Basic |
| **Workspace Intelligence** | ✅ Yes | ✅ Yes | ⚠️ Limited |
| **Real-time Occupancy** | ✅ Yes | ✅ Yes | ⚠️ Limited |
| **Room Optimization** | ✅ Yes | ✅ Yes | ⚠️ Limited |
| **Predictive Analytics** | ✅ Yes | ✅ Yes | ❌ No |
| **Research Focus** | ✅ Yes | ❌ No | ❌ No |
| **Cost** | **Free** | $5-20/visitor | $8-15/visitor |
| **Customization** | ✅ Fully customizable | ❌ Limited | ❌ Limited |
| **Privacy** | ✅ Full data control | ⚠️ Cloud-based | ⚠️ Cloud-based |

## Use Cases

- **Academic Institutions**: Research-focused visitor management with full data control
- **Privacy-Conscious Organizations**: Self-hosted solution with no vendor lock-in
- **Small to Medium Businesses**: Cost-effective alternative to expensive SaaS platforms
- **Research Labs**: Open-source platform for authentication protocol research
- **Government/Healthcare**: Privacy-sensitive deployments requiring on-premise solutions

## Future Enhancements

- Machine learning models for enhanced visitor pattern prediction
- Real-time room booking system integration
- Employee presence tracking (WiFi/access card integration)
- Mobile app (iOS/Android)
- Calendar system integration (Google Calendar, Outlook)
- Slack/Teams notifications
- Multi-gate synchronization
- Energy consumption correlation with occupancy

## License

This project is provided for academic and research purposes.
