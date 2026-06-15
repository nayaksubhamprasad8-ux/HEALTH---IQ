import csv
import json
import os
import hashlib
import requests
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

app = Flask(__name__)
# FIX 1: Secret key should come from env; fallback only for dev
app.secret_key = os.environ.get("SECRET_KEY", "healthiq_dev_secret_change_in_prod")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =====================================================
# HELPERS
# =====================================================
def hash_password(pw: str) -> str:
    """SHA-256 hash for password storage (upgrade to bcrypt in production)."""
    return hashlib.sha256(pw.encode()).hexdigest()


def _safe_float(value):
    """Return float(value) or None if it can't be converted."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def login_required(f):
    """Decorator to guard routes that require login."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator to guard admin-only routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated


# =====================================================
# LOAD / SAVE USERS
# =====================================================
def load_users():
    path = os.path.join(BASE_DIR, "users.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print("Error loading users:", e)
        return []


def save_users(users):
    path = os.path.join(BASE_DIR, "users.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)


# =====================================================
# LOAD PLANS CSV  (cached per process)
# =====================================================
_plans_cache = None

CSV_FILENAME = "Health_IQ_Pure_Health_Plans_Detailed.csv"

# FIX: the CSV may live directly in BASE_DIR or inside a "Data" subfolder
# (as in the current project structure: Health IQ/Data/...csv)
CSV_SEARCH_PATHS = [
    os.path.join(BASE_DIR, CSV_FILENAME),
    os.path.join(BASE_DIR, "Data", CSV_FILENAME),
    os.path.join(BASE_DIR, "data", CSV_FILENAME),
]


def find_plans_csv():
    """Return the first existing path among CSV_SEARCH_PATHS, or None."""
    for p in CSV_SEARCH_PATHS:
        if os.path.exists(p):
            return p
    return None


def load_plans():
    global _plans_cache
    if _plans_cache:  # FIX: only short-circuit if cache is non-empty
        return _plans_cache

    path = find_plans_csv()

    if path is None:
        print("[load_plans] ERROR: CSV not found. Looked in:")
        for p in CSV_SEARCH_PATHS:
            print(f"    - {p}")
        return []

    try:
        with open(path, "r", encoding="utf-8-sig") as f:  # FIX: utf-8-sig handles BOM
            rows = list(csv.DictReader(f))
        if not rows:
            print(f"[load_plans] WARNING: CSV at {path} loaded 0 rows. "
                  f"Check the file has a header row plus data rows.")
            return []
        print(f"[load_plans] Loaded {len(rows)} plans from {path}")
        _plans_cache = rows
        return _plans_cache
    except Exception as e:
        print(f"[load_plans] ERROR reading {path}: {e}")
        return []


# =====================================================
# TEMPORARY DEBUG ROUTE — disabled unless DEBUG_ROUTES=1
# Set DEBUG_ROUTES=1 locally if you need to troubleshoot CSV loading.
# Leave unset (default) in production/Render to keep this hidden.
# =====================================================
@app.route("/debug/plans")
def debug_plans():
    if os.environ.get("DEBUG_ROUTES") != "1":
        return jsonify({"error": "Not found"}), 404

    path = find_plans_csv()
    info = {
        "BASE_DIR": BASE_DIR,
        "search_paths": CSV_SEARCH_PATHS,
        "resolved_path": path,
        "file_exists": path is not None,
    }
    if path:
        info["file_size_bytes"] = os.path.getsize(path)
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                info["columns"] = reader.fieldnames
                rows = list(reader)
                info["row_count"] = len(rows)
                info["first_row"] = rows[0] if rows else None
        except Exception as e:
            info["read_error"] = str(e)
    else:
        try:
            info["files_in_base_dir"] = os.listdir(BASE_DIR)
            data_dir = os.path.join(BASE_DIR, "Data")
            if os.path.isdir(data_dir):
                info["files_in_data_dir"] = os.listdir(data_dir)
        except Exception as e:
            info["listdir_error"] = str(e)
    return jsonify(info)


# =====================================================
# ROOT
# =====================================================
@app.route("/")
def index():
    return redirect(url_for("login"))


# =====================================================
# LOGIN / SIGNUP
# =====================================================
@app.route("/login")
def login():
    if "user" in session:
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/signin", methods=["POST"])
def signin():
    users = load_users()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    # FIX 2: Support both hashed passwords and legacy plaintext
    for user in users:
        stored_email = user["email"].strip().lower()
        if stored_email != email:
            continue
        stored_pw = user["password"]
        # Accept hashed or legacy plaintext
        if stored_pw == hash_password(password) or stored_pw == password:
            session["user"] = user["name"]
            session["email"] = user["email"]
            session["role"] = user.get("role", "user")
            return redirect(url_for("home"))

    return render_template("login.html", error="Invalid email or password")


@app.route("/signup", methods=["POST"])
def signup():
    users = load_users()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    # FIX 3: Input validation
    if not name or not email or not password:
        return render_template("login.html", error="All fields are required.")
    if len(password) < 6:
        return render_template("login.html", error="Password must be at least 6 characters.")
    if any(u["email"].lower() == email for u in users):
        return render_template("login.html", error="An account with that email already exists.")

    new_user = {
        "name": name,
        "email": email,
        "password": hash_password(password),  # FIX 4: Hash on signup
        "role": "user"
    }
    users.append(new_user)
    save_users(users)

    session["user"] = name
    session["email"] = email
    session["role"] = "user"
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =====================================================
# HOME
# =====================================================
@app.route("/home")
@login_required
def home():
    plans_list = load_plans()
    total_plans = len(plans_list)
    companies = len(set(p["Company"] for p in plans_list))
    # FIX 5: Guard against division by zero
    avg_rating = round(
        sum(float(p["Rating"]) for p in plans_list) / max(total_plans, 1), 1
    )
    return render_template(
        "index.html",
        user=session["user"],
        total_plans=total_plans,
        companies=companies,
        avg_rating=avg_rating,
    )


# =====================================================
# PLANS PAGE
# =====================================================
@app.route("/plans")
@login_required
def plans():
    plans_list = load_plans()
    # FIX 6: Pass user to template (was missing — navbar macro needs it)
    return render_template("plans.html", plans=plans_list, user=session["user"])


# =====================================================
# COMPARE PAGE
# =====================================================
@app.route("/compare")
@login_required
def compare():
    selected_names = request.args.getlist("plans")
    # FIX 7: Allow exactly 2 or 3, not < 2
    if len(selected_names) < 2 or len(selected_names) > 3:
        return render_template(
            "compare.html",
            selected=[],
            error="Please select 2 or 3 plans to compare.",
            user=session["user"],
        )
    all_plans = load_plans()
    selected = [p for p in all_plans if p.get("Plan_Name") in selected_names]
    if len(selected) < 2:
        return render_template(
            "compare.html",
            selected=[],
            error="One or more selected plans could not be found.",
            user=session["user"],
        )
    return render_template(
        "compare.html", selected=selected, error=None, user=session["user"]
    )


# =====================================================
# SMART RECOMMENDATION ENGINE
# =====================================================
@app.route("/recommend")
@login_required
def recommend():
    return render_template("recommend.html", user=session["user"])


@app.route("/api/recommend", methods=["POST"])
@login_required
def api_recommend():
    data = request.get_json(silent=True) or {}
    # FIX 8: Safe int/float parsing with try/except
    try:
        age = int(data.get("age", 30))
        budget = int(data.get("budget", 50000))
        coverage_needed = int(data.get("coverage_needed", 500000))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric input"}), 400

    plan_type = data.get("plan_type", "Individual")
    priority = data.get("priority", "balanced")

    all_plans = load_plans()
    scored = []
    for p in all_plans:
        try:
            annual_premium = float(p["Annual_Premium"])
            coverage = float(p["Coverage_Limit"])
            rating = float(p["Rating"])
            csr = float(p["Claim_Settlement_Ratio_Percent"])
            hospitals = int(p["Network_Hospitals"])
        except (KeyError, ValueError):
            continue

        score = 0

        # Plan type match
        if p["Plan_Type"].lower() == plan_type.lower():
            score += 30
        elif plan_type == "Senior" and age >= 60:
            score += 20

        # Budget fit
        if annual_premium <= budget:
            score += 25
        elif annual_premium <= budget * 1.2:
            score += 10

        # Coverage adequacy
        if coverage >= coverage_needed:
            score += 20
        elif coverage >= coverage_needed * 0.8:
            score += 10

        # Priority weighting
        if priority == "claim":
            score += (csr / 100) * 15
        elif priority == "hospital":
            score += min(hospitals / 15000, 1) * 15
        elif priority == "coverage":
            score += min(coverage / 10_000_000, 1) * 15
        else:
            score += rating * 3

        # Rating bonus
        score += rating * 2

        # Wellness bonus
        if p.get("Wellness_Benefit") == "Yes":
            score += 5

        scored.append({**p, "score": round(score, 1)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(scored[:5])


# =====================================================
# COVERAGE CALCULATOR
# =====================================================
@app.route("/calculator")
@login_required
def calculator():
    return render_template("calculator.html", user=session["user"])


@app.route("/api/calculate", methods=["POST"])
@login_required
def api_calculate():
    data = request.get_json(silent=True) or {}
    try:
        age = int(data.get("age", 30))
        members = max(1, int(data.get("members", 1)))
        income = max(0, int(data.get("income", 500000)))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric input"}), 400

    city_tier = data.get("city_tier", "tier1")
    existing_conditions = data.get("conditions", [])
    if not isinstance(existing_conditions, list):
        existing_conditions = []

    base = 500_000

    if age < 30:
        age_mult = 1.0
    elif age < 45:
        age_mult = 1.5
    elif age < 60:
        age_mult = 2.0
    else:
        age_mult = 3.0

    city_mult = {"tier1": 1.5, "tier2": 1.2, "tier3": 1.0}.get(city_tier, 1.0)
    member_mult = 1 + (members - 1) * 0.5
    condition_add = len(existing_conditions) * 200_000
    income_rec = income * 0.5

    recommended = max(
        int(base * age_mult * city_mult * member_mult + condition_add),
        int(income_rec),
    )
    recommended = max(500_000, round(recommended / 500_000) * 500_000)

    base_premium = recommended * 0.04 if age < 45 else recommended * 0.07
    premium_low = int(base_premium * 0.8)
    premium_high = int(base_premium * 1.3)

    return jsonify({
        "recommended_coverage": recommended,
        "premium_low": premium_low,
        "premium_high": premium_high,
        "breakdown": {
            "base": base,
            "age_factor": age_mult,
            "city_factor": city_mult,
            "members_factor": round(member_mult, 2),
            "conditions_add": condition_add,
        },
    })


# =====================================================
# PREMIUM PREDICTION
# =====================================================
@app.route("/premium-predict")
@login_required
def premium_predict():
    return render_template("premium_predict.html", user=session["user"])


@app.route("/api/predict-premium", methods=["POST"])
@login_required
def api_predict_premium():
    data = request.get_json(silent=True) or {}
    try:
        age = int(data.get("age", 30))
        coverage = int(data.get("coverage", 500_000))
        bmi = float(data.get("bmi", 22))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric input"}), 400

    plan_type = data.get("plan_type", "Individual")
    company = data.get("company", "")
    smoker = bool(data.get("smoker", False))

    all_plans = load_plans()
    relevant = [p for p in all_plans if p["Plan_Type"].lower() == plan_type.lower()]
    if company:
        comp_plans = [p for p in relevant if company.lower() in p["Company"].lower()]
        if comp_plans:
            relevant = comp_plans

    if not relevant:
        relevant = all_plans

    weights, premiums = [], []
    for p in relevant:
        try:
            pcov = float(p["Coverage_Limit"])
            pprem = float(p["Annual_Premium"])
            dist = abs(pcov - coverage)
            w = 1.0 / (dist + 1)
            weights.append(w)
            premiums.append(pprem)
        except (KeyError, ValueError):
            pass

    if not premiums:
        return jsonify({"error": "No data available for the selected criteria"}), 404

    base_pred = sum(w * p for w, p in zip(weights, premiums)) / sum(weights)

    # Age adjustment
    if age < 30:
        age_adj = 0.85
    elif age < 45:
        age_adj = 1.0
    elif age < 60:
        age_adj = 1.4
    else:
        age_adj = 2.0

    # BMI adjustment
    if bmi > 30:
        bmi_adj = 1.15
    elif bmi > 25:
        bmi_adj = 1.05
    else:
        bmi_adj = 1.0

    smoker_adj = 1.3 if smoker else 1.0

    predicted = int(base_pred * age_adj * bmi_adj * smoker_adj)
    monthly = int(predicted / 12)
    lo = int(predicted * 0.85)
    hi = int(predicted * 1.15)

    return jsonify({
        "predicted_annual": predicted,
        "predicted_monthly": monthly,
        "range_low": lo,
        "range_high": hi,
        "adjustments": {
            "age": round(age_adj, 2),
            "bmi": round(bmi_adj, 2),
            "smoker": round(smoker_adj, 2),
        },
    })


# =====================================================
# CLAIM APPROVAL PREDICTION
# =====================================================
@app.route("/claim-predict")
@login_required
def claim_predict():
    plans_list = load_plans()
    return render_template(
        "claim_predict.html", user=session["user"], plans=plans_list
    )


@app.route("/api/predict-claim", methods=["POST"])
@login_required
def api_predict_claim():
    data = request.get_json(silent=True) or {}
    plan_name = data.get("plan_name", "")

    try:
        claim_amount = float(data.get("claim_amount", 100_000))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid claim amount"}), 400

    claim_type = data.get("claim_type", "hospitalization")
    waiting_period_done = bool(data.get("waiting_period_done", True))
    pre_existing = bool(data.get("pre_existing", False))
    documents_complete = bool(data.get("documents_complete", True))

    all_plans = load_plans()
    plan = next((p for p in all_plans if p["Plan_Name"] == plan_name), None)
    if not plan:
        return jsonify({"error": "Plan not found"}), 404

    base_csr = float(plan["Claim_Settlement_Ratio_Percent"]) / 100
    coverage_limit = float(plan["Coverage_Limit"])

    prob = base_csr

    if not waiting_period_done:
        prob *= 0.3
    if pre_existing:
        prob *= 0.75
    if not documents_complete:
        prob *= 0.6
    if claim_amount > coverage_limit:
        prob *= 0.5
    elif claim_amount > coverage_limit * 0.8:
        prob *= 0.85

    if claim_type == "cashless":
        prob = min(prob * 1.05, 0.98)
    elif claim_type == "reimbursement":
        prob *= 0.95

    prob = max(0.05, min(prob, 0.98))
    approval_pct = round(prob * 100, 1)

    tips = []
    if not waiting_period_done:
        tips.append("⚠️ Complete your waiting period before filing a claim.")
    if pre_existing:
        tips.append("📋 Disclose all pre-existing conditions during policy purchase to avoid rejection.")
    if not documents_complete:
        tips.append("📁 Ensure all documents (bills, discharge summary, ID proof) are submitted.")
    if claim_amount > coverage_limit:
        tips.append("💡 Your claim amount exceeds the coverage limit. Consider upgrading your plan.")
    if approval_pct > 80:
        tips.append("✅ Your claim has a high probability of approval. Ensure timely submission.")

    return jsonify({
        "approval_probability": approval_pct,
        "csr": float(plan["Claim_Settlement_Ratio_Percent"]),
        "coverage_limit": int(coverage_limit),
        "tips": tips,
        "verdict": "High" if approval_pct >= 75 else "Medium" if approval_pct >= 50 else "Low",
    })


# =====================================================
# ANALYTICS DASHBOARD
# =====================================================
@app.route("/analytics")
@login_required
def analytics():
    plans_list = load_plans()

    company_data = {}
    type_data = {"Individual": 0, "Family": 0, "Senior": 0}
    premium_buckets = {"<₹15K": 0, "₹15K–30K": 0, "₹30K–50K": 0, ">₹50K": 0}
    csr_data = []
    rating_data = {}

    for p in plans_list:
        try:
            comp = (
                p["Company"]
                .replace(" Insurance", "")
                .replace(" General", "")
                .replace(" Health", "")
            )
            company_data[comp] = company_data.get(comp, 0) + 1

            pt = p["Plan_Type"]
            if pt in type_data:
                type_data[pt] += 1

            prem = float(p["Annual_Premium"])
            if prem < 15_000:
                premium_buckets["<₹15K"] += 1
            elif prem < 30_000:
                premium_buckets["₹15K–30K"] += 1
            elif prem < 50_000:
                premium_buckets["₹30K–50K"] += 1
            else:
                premium_buckets[">₹50K"] += 1

            csr_data.append({
                "plan": p["Plan_Name"][:20],
                "csr": float(p["Claim_Settlement_Ratio_Percent"]),
            })
            rating_data[comp] = max(rating_data.get(comp, 0), float(p["Rating"]))
        except (KeyError, ValueError):
            pass

    csr_data.sort(key=lambda x: x["csr"], reverse=True)

    # Dynamic KPI values (replace previously hardcoded figures)
    valid = [p for p in plans_list if _safe_float(p.get("Annual_Premium")) is not None]
    avg_premium_k = round(sum(float(p["Annual_Premium"]) for p in valid) / max(len(valid), 1) / 1000)
    avg_csr = round(sum(float(p["Claim_Settlement_Ratio_Percent"]) for p in valid) / max(len(valid), 1), 1)
    avg_hospitals_k = round(sum(int(p["Network_Hospitals"]) for p in valid) / max(len(valid), 1) / 1000, 1)
    total_companies = len(set(p["Company"] for p in plans_list))

    return render_template(
        "analytics.html",
        user=session["user"],
        company_data=json.dumps(company_data),
        type_data=json.dumps(type_data),
        premium_buckets=json.dumps(premium_buckets),
        csr_data=json.dumps(csr_data[:10]),
        rating_data=json.dumps(rating_data),
        total_plans=len(plans_list),
        total_companies=total_companies,
        avg_premium_k=avg_premium_k,
        avg_csr=avg_csr,
        avg_hospitals_k=avg_hospitals_k,
    )


# =====================================================
# HOSPITAL FINDER
# =====================================================
@app.route("/hospitals")
@login_required
def hospitals():
    plans_list = load_plans()
    companies = sorted(set(p["Company"] for p in plans_list))
    return render_template(
        "hospitals.html", user=session["user"], companies=companies, plans=plans_list
    )


# =====================================================
# ADMIN DASHBOARD
# =====================================================
@app.route("/admin")
@admin_required
def admin():
    users = load_users()
    plans_list = load_plans()
    return render_template(
        "admin.html",
        users=users,
        plans=plans_list,
        user=session["user"],
        total_users=len(users),
        total_plans=len(plans_list),
        current_email=session.get("email", ""),
    )


@app.route("/admin/delete-user/<email>", methods=["POST"])
@admin_required
def delete_user(email):
    # FIX 9: Prevent admin from deleting their own account via direct POST
    if email == session.get("email"):
        return redirect(url_for("admin"))
    users = load_users()
    users = [u for u in users if u["email"] != email]
    save_users(users)
    return redirect(url_for("admin"))


# =====================================================
# PDF EXPORT
# =====================================================
@app.route("/export-pdf")
@login_required
def export_pdf():
    selected_names = request.args.getlist("plans")
    # FIX 10: Validate at least 1 plan selected
    if not selected_names:
        return redirect(url_for("plans"))
    all_plans = load_plans()
    selected = [p for p in all_plans if p.get("Plan_Name") in selected_names]
    return render_template(
        "export_pdf.html", selected=selected, user=session["user"]
    )


# =====================================================
# API: GET ALL PLANS (for AI Advisor)
# =====================================================
@app.route("/api/plans")
@login_required
def api_plans():
    return jsonify(load_plans())


# =====================================================
# AI ADVISOR PAGE
# =====================================================
@app.route("/advisor")
@login_required
def advisor():
    plans_list = load_plans()
    # FIX: With 1100+ plans, sending the full dataset to the browser/model on
    # every message is too large (~50K+ tokens) and slow. The page no longer
    # embeds plan data; /api/advisor builds a condensed summary server-side
    # on each request instead.
    return render_template(
        "advisor.html",
        user=session["user"],
        total_plans=len(plans_list),
    )


def build_advisor_context(plans_list):
    """
    Build a condensed, token-efficient summary of the plans dataset for the
    AI advisor's system prompt. Instead of dumping all 1100+ rows (which
    would be ~50K+ tokens per message), this sends aggregate stats and a
    curated set of standout plans per category.
    """
    by_company = {}
    by_type = {"Individual": [], "Family": [], "Senior": []}

    for p in plans_list:
        try:
            row = {
                "name": p["Plan_Name"],
                "company": p["Company"],
                "type": p["Plan_Type"],
                "annual_premium": float(p["Annual_Premium"]),
                "coverage": float(p["Coverage_Limit"]),
                "csr": float(p["Claim_Settlement_Ratio_Percent"]),
                "rating": float(p["Rating"]),
                "hospitals": int(p["Network_Hospitals"]),
                "wellness": p["Wellness_Benefit"],
            }
        except (KeyError, ValueError):
            continue

        by_company.setdefault(row["company"], []).append(row)
        if row["type"] in by_type:
            by_type[row["type"]].append(row)

    # Per-company aggregate stats
    company_stats = []
    for company, rows in by_company.items():
        company_stats.append({
            "company": company,
            "plan_count": len(rows),
            "avg_premium": round(sum(r["annual_premium"] for r in rows) / len(rows)),
            "avg_csr": round(sum(r["csr"] for r in rows) / len(rows), 1),
            "avg_rating": round(sum(r["rating"] for r in rows) / len(rows), 2),
            "max_hospitals": max(r["hospitals"] for r in rows),
        })

    def top_n(rows, key, n=8, reverse=True):
        return sorted(rows, key=lambda r: r[key], reverse=reverse)[:n]

    all_rows = [r for rows in by_company.values() for r in rows]

    highlights = {
        "top_csr_overall": top_n(all_rows, "csr"),
        "top_rating_overall": top_n(all_rows, "rating"),
        "cheapest_overall": top_n(all_rows, "annual_premium", reverse=False),
        "highest_coverage": top_n(all_rows, "coverage"),
        "most_hospitals": top_n(all_rows, "hospitals"),
    }
    for ptype, rows in by_type.items():
        if rows:
            highlights[f"best_{ptype.lower()}_by_csr"] = top_n(rows, "csr", n=5)
            highlights[f"cheapest_{ptype.lower()}"] = top_n(rows, "annual_premium", n=5, reverse=False)

    return {
        "total_plans": len(all_rows),
        "companies": company_stats,
        "highlights": highlights,
    }


@app.route("/api/advisor", methods=["POST"])
@login_required
def api_advisor():
    """
    Proxies chat messages to the Google Gemini API server-side.
    Keeps the API key out of the browser, and builds a condensed dataset
    summary on each request so the prompt stays small even with 1100+
    plans in the CSV.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "AI advisor is not configured. Set GEMINI_API_KEY."}), 503

    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])

    if not isinstance(messages, list) or not messages:
        return jsonify({"error": "No messages provided"}), 400

    # Cap history sent to the model
    messages = messages[-20:]

    plans_list = load_plans()
    context = build_advisor_context(plans_list)

    system_prompt = (
        "You are an expert AI Health Insurance Advisor for Health IQ, India's "
        "leading insurance comparison platform.\n\n"
        f"The platform has {context['total_plans']} health insurance plans "
        f"across {len(context['companies'])} insurers. Below is a condensed "
        "summary: per-company stats and standout plans by category (not the "
        "full dataset).\n\n"
        f"COMPANY STATS:\n{json.dumps(context['companies'], indent=2)}\n\n"
        f"HIGHLIGHTS (top plans by various metrics):\n{json.dumps(context['highlights'], indent=2)}\n\n"
        "Your role:\n"
        "- Help users understand and choose health insurance plans\n"
        "- Compare plans based on their needs (budget, age, plan type, claim ratio, hospital network)\n"
        "- Explain insurance terms clearly (waiting period, CSR, cashless, co-payment, etc.)\n"
        "- Give specific plan recommendations with data-backed reasoning, citing plan names, "
        "premiums, coverage, and CSR from the data above\n"
        "- If the user needs a plan that isn't in the highlights above, suggest they use the "
        "Recommend or Plans pages for an exhaustive, filterable search\n"
        "- Answer questions about Indian health insurance regulations and best practices\n\n"
        "Be concise, friendly, and data-driven. Format responses cleanly with line breaks "
        "for readability."
    )

    # FIX: Gemini's "contents" format differs from Anthropic's "messages":
    # - roles are "user" / "model" (not "assistant")
    # - each message is { role, parts: [{ text }] } instead of { role, content }
    gemini_contents = []
    for m in messages:
        role = "model" if m.get("role") == "assistant" else "user"
        content = m.get("content", "")
        if isinstance(content, list):
            # In case content is already a list of blocks, extract text
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        gemini_contents.append({"role": role, "parts": [{"text": str(content)}]})

    # gemini-2.5-flash-lite currently has the most generous free-tier quota
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    try:
        resp = requests.post(
            url,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "contents": gemini_contents,
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": {"maxOutputTokens": 1000},
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        text = ""
        candidates = result.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)

        if not text:
            # Check if the response was blocked or empty for another reason
            finish_reason = candidates[0].get("finishReason") if candidates else None
            if finish_reason == "SAFETY":
                return jsonify({"text": "I can't respond to that. Could you rephrase your question?"})
            return jsonify({"text": "I couldn't generate a response. Please try again."})

        return jsonify({"text": text})
    except requests.exceptions.Timeout:
        return jsonify({"error": "The advisor took too long to respond. Please try again."}), 504
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        body = e.response.text[:500] if e.response is not None else str(e)
        print(f"Advisor API error ({status}):", body)
        if status == 400:
            return jsonify({"error": "Invalid request to the AI advisor. Please try again."}), 502
        if status in (401, 403):
            return jsonify({"error": "AI advisor authentication failed. Check GEMINI_API_KEY."}), 502
        if status == 429:
            return jsonify({"error": "AI advisor rate limit reached. Please try again shortly."}), 502
        return jsonify({"error": "The AI advisor is temporarily unavailable."}), 502
    except requests.exceptions.RequestException as e:
        print("Advisor API error:", e)
        return jsonify({"error": "The AI advisor is temporarily unavailable."}), 502


# =====================================================
# ERROR HANDLERS
# =====================================================
@app.errorhandler(404)
def not_found(e):
    return render_template("login.html", error="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("login.html", error="Internal server error. Please try again."), 500


# =====================================================
# HEALTH CHECK
# =====================================================
@app.route("/healthz")
def healthz():
    info = {
        "status": "ok",
        "plans_loaded": len(load_plans()),
    }
    # Verbose diagnostics only when explicitly enabled
    if os.environ.get("DEBUG_ROUTES") == "1":
        info["app_file"] = os.path.abspath(__file__)
        info["base_dir"] = BASE_DIR
        info["csv_resolved_path"] = find_plans_csv()
        info["users_loaded"] = len(load_users())
    return jsonify(info)


# =====================================================
# RUN APP
# =====================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # FIX 11: debug=True only in development
    debug = os.environ.get("FLASK_ENV", "production") == "development"

    # Startup diagnostics — confirms which app.py/CSV is actually running
    _plans = load_plans()
    print("=" * 60)
    print(f"Health IQ starting")
    print(f"  app.py location : {os.path.abspath(__file__)}")
    print(f"  BASE_DIR         : {BASE_DIR}")
    print(f"  CSV search paths :")
    for p in CSV_SEARCH_PATHS:
        marker = " <-- FOUND" if os.path.exists(p) else ""
        print(f"     - {p}{marker}")
    print(f"  Plans loaded     : {len(_plans)}")
    print(f"  Users loaded     : {len(load_users())}")
    print(f"  debug mode       : {debug}")
    print(f"  Visit /healthz for a live JSON check after startup")
    print("=" * 60)

    app.run(host="0.0.0.0", port=port, debug=debug)
