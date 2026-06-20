# Health IQ — AI-Powered Health Insurance Comparison Platform

India's health insurance comparison platform — compare 1,100+ plans, get AI-powered recommendations, predict premiums, and check claim approval probability before you apply.

**Live app:** [https://health-iq-2.onrender.com](https://health-iq-2.onrender.com)

> Hosted on Render's free tier — the first request after a period of inactivity may take 30–60 seconds to wake up the server.

---

## Features

- **Firebase Authentication** — Email/Password + Google Sign-In, with server-side token verification
- **Forgot Password** — self-service password reset via Firebase
- **Smart Recommendation Engine** — personalized plan suggestions based on age, budget, and health needs
- **AI Insurance Advisor** — chat-based advisor powered by Gemini
- **Coverage Calculator** — recommends ideal coverage based on age, income, family size, and city tier
- **Premium Predictor** — ML-style weighted prediction of annual premium
- **Claim Approval Predictor** — estimates claim approval probability with actionable tips
- **Analytics Dashboard** — visual breakdown of plans by company, type, premium, and CSR
- **Hospital Finder** — browse network hospitals by company
- **Admin Panel** — manage users and view platform-wide stats
- **PDF Export** — export plan comparisons

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask (Python) |
| Auth | Firebase Authentication (client) + Firebase Admin SDK (server) |
| AI Advisor | Google Gemini API |
| Data | CSV (`Health_IQ_Pure_Health_Plans_Detailed.csv`) |
| Frontend | HTML, CSS, vanilla JS |
| Deployment | Render |

---

## Project Structure

```
Health IQ/
├── app.py                          # Flask app — routes, APIs, Firebase token verification
├── firebase-service-account.json   # Firebase Admin credentials (gitignored, local dev only)
├── users.json                      # User registry (auto-created/updated on login)
├── requirements.txt
├── Procfile                        # Render start command
├── .gitignore
├── Data/
│   └── Health_IQ_Pure_Health_Plans_Detailed.csv
├── static/
│   ├── css/
│   └── images/
└── templates/
    ├── login.html                  # Firebase sign-in / sign-up / forgot password
    ├── index.html
    ├── plans.html
    ├── compare.html
    ├── recommend.html
    ├── calculator.html
    ├── premium_predict.html
    ├── claim_predict.html
    ├── analytics.html
    ├── hospitals.html
    ├── advisor.html
    ├── admin.html
    ├── export_pdf.html
    └── macros.html
```

---

## How Authentication Works

Authentication is split between **Firebase (client-side)** and **Flask (server-side)** — Firebase never directly controls your Flask session.

```
1. User signs in / signs up / uses Google  →  handled entirely by Firebase JS SDK in login.html
2. Firebase returns a short-lived ID token to the browser
3. Browser POSTs that token to  /api/firebase-login
4. Flask verifies the token using firebase-admin (checks signature + expiry)
5. Flask upserts the user into users.json and sets the session
6. Flask returns { "redirect": "/home" } and the browser navigates there
```

All protected routes use the `@login_required` / `@admin_required` decorators, which check Flask's session — not Firebase directly. This means your backend stays the single source of truth for "is this user logged in."

### Forgot Password

Handled entirely client-side via Firebase's `sendPasswordResetEmail()` — no backend route needed. Firebase sends the reset email and hosts the reset-password page itself.

To customize the sender name/email content:
```
Firebase Console → Authentication → Templates → Password reset
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | Flask session secret key |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Yes (production) | Full contents of your Firebase service account JSON, as a single env var string |
| `GOOGLE_APPLICATION_CREDENTIALS` | Alternative | Path to a service account JSON file (used if the env var above isn't set — typical for GCP) |
| `GEMINI_API_KEY` | Yes | API key for the AI Advisor (Google Gemini) |
| `GEMINI_MODEL` | No | Defaults to `gemini-2.5-flash-lite` |
| `PORT` | No | Defaults to `5000` |
| `FLASK_ENV` | No | Set to `development` to enable debug mode |

**Credential resolution order** (see `_init_firebase()` in `app.py`):
1. `FIREBASE_SERVICE_ACCOUNT_JSON` (env var, JSON string) — used on Render
2. `GOOGLE_APPLICATION_CREDENTIALS` (env var, file path) — used on GCP
3. `firebase-service-account.json` in the project root — local development fallback

---

## Local Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Get your Firebase service account key
```
Firebase Console → Project Settings → Service Accounts → Generate new private key
```
Save the downloaded file as `firebase-service-account.json` in the project root.

### 3. Add it to `.gitignore`
```
firebase-service-account.json
```
(Already included — just confirm it's there before committing.)

### 4. Set your Gemini API key
```bash
export GEMINI_API_KEY="your-key-here"        # macOS/Linux
set GEMINI_API_KEY=your-key-here              # Windows (cmd)
```

### 5. Run the app
```bash
python app.py
```
Visit `http://localhost:5000`

### 6. Authorize localhost in Firebase
```
Firebase Console → Authentication → Settings → Authorized domains → Add domain → localhost
```
If accessing via a local network IP (e.g. `10.x.x.x`), add that IP too, or just always use `localhost` to avoid re-adding IPs that change.

---

## Deploying to Render

### 1. Push to GitHub
Make sure `firebase-service-account.json` is **not** committed (check `.gitignore`).

### 2. Set environment variables on Render
```
Render Dashboard → Your Service → Environment → Add Environment Variable
```

| Key | Value |
|---|---|
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Paste the entire contents of your service account JSON file |
| `SECRET_KEY` | Any long random string |
| `GEMINI_API_KEY` | Your Gemini API key |

### 3. Authorize your Render domain in Firebase
```
Firebase Console → Authentication → Settings → Authorized domains
→ Add domain → health-iq-2.onrender.com
```

### 4. Deploy
Render auto-deploys on push. Confirm in the deploy logs:
```
[firebase-admin] Initialised from FIREBASE_SERVICE_ACCOUNT_JSON env var
```

Then verify the live deployment:
```
https://health-iq-2.onrender.com/healthz
```
Should return `"firebase_admin_init": true`.

---

## Health Check

```
GET https://health-iq-2.onrender.com/healthz
```
Returns JSON with app status, resolved CSV path, plans/users loaded, and Firebase Admin init status — useful for confirming a deploy worked correctly.

```
GET https://health-iq-2.onrender.com/debug/plans
```
Diagnostic route for troubleshooting CSV loading issues (shows search paths, columns, row count).

---

## Notes

- `users.json` is no longer used for password storage — Firebase owns all credentials. It's kept as a lightweight registry for the admin panel and for storing user `role` (e.g. `"admin"`). To promote a user to admin, manually edit their entry's `role` field.
- The legacy `/signin` and `/signup` form routes still exist in `app.py` for any pre-Firebase local users, but `login.html` no longer calls them — all auth now flows through `/api/firebase-login`. Safe to remove once fully migrated.
- The AI Advisor sends a condensed summary of the plans dataset (aggregate stats + top plans per category) to Gemini on each request, rather than the full 1,100+ row dataset, to keep prompts small and fast.
