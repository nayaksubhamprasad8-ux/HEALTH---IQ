import csv
import json
import os
import random
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

app = Flask(__name__)
app.secret_key = "healthiq_secret_2026"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =====================================================
# LOAD USERS
# =====================================================
def load_users():
    try:
        with open(os.path.join(BASE_DIR, "users.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("Error loading users:", e)
        return []


def save_users(users):
    with open(os.path.join(BASE_DIR, "users.json"), "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)


# =====================================================
# LOAD PLANS CSV
# =====================================================
def load_plans():
    try:
        with open(
            os.path.join(BASE_DIR, "Health_IQ_Pure_Health_Plans_Detailed.csv"),
            "r", encoding="utf-8"
        ) as f:
            plans = list(csv.DictReader(f))
            return plans
    except Exception as e:
        print("Error loading plans:", e)
        return []


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
    return render_template("login.html")


@app.route("/signin", methods=["POST"])
def signin():
    users = load_users()
    email = request.form.get("email")
    password = request.form.get("password")
    for user in users:
        if user["email"] == email and user["password"] == password:
            session["user"] = user["name"]
            session["email"] = user["email"]
            session["role"] = user.get("role", "user")
            return redirect(url_for("home"))
    return render_template("login.html", error="Invalid email or password")


@app.route("/signup", methods=["POST"])
def signup():
    users = load_users()
    name = request.form.get("name")
    email = request.form.get("email")
    password = request.form.get("password")
    if any(u["email"] == email for u in users):
        return render_template("login.html", error="Email already exists")
    new_user = {"name": name, "email": email, "password": password, "role": "user"}
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
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    plans_list = load_plans()
    total_plans = len(plans_list)
    companies = len(set(p["Company"] for p in plans_list))
    avg_rating = round(sum(float(p["Rating"]) for p in plans_list) / total_plans, 1)
    return render_template("index.html", user=session["user"],
                           total_plans=total_plans, companies=companies, avg_rating=avg_rating)


# =====================================================
# PLANS PAGE
# =====================================================
@app.route("/plans")
def plans():
    if "user" not in session:
        return redirect(url_for("login"))
    plans_list = load_plans()
    return render_template("plans.html", plans=plans_list)


# =====================================================
# COMPARE PAGE
# =====================================================
@app.route("/compare")
def compare():
    if "user" not in session:
        return redirect(url_for("login"))
    selected_names = request.args.getlist("plans")
    if len(selected_names) < 2 or len(selected_names) > 3:
        return render_template("compare.html", selected=[], error="Please select 2 or 3 plans to compare.")
    all_plans = load_plans()
    selected = [p for p in all_plans if p.get("Plan_Name") in selected_names]
    return render_template("compare.html", selected=selected, error=None)


# =====================================================
# SMART RECOMMENDATION ENGINE
# =====================================================
@app.route("/recommend")
def recommend():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("recommend.html", user=session["user"])


@app.route("/api/recommend", methods=["POST"])
def api_recommend():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    age = int(data.get("age", 30))
    plan_type = data.get("plan_type", "Individual")
    budget = int(data.get("budget", 50000))
    coverage_needed = int(data.get("coverage_needed", 500000))
    priority = data.get("priority", "balanced")

    all_plans = load_plans()
    scored = []
    for p in all_plans:
        score = 0
        try:
            annual_premium = float(p["Annual_Premium"])
            coverage = float(p["Coverage_Limit"])
            rating = float(p["Rating"])
            csr = float(p["Claim_Settlement_Ratio_Percent"])
            hospitals = int(p["Network_Hospitals"])

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
                score += min(coverage / 10000000, 1) * 15
            else:
                score += rating * 3

            # Rating bonus
            score += rating * 2

            # Wellness bonus
            if p.get("Wellness_Benefit") == "Yes":
                score += 5

            scored.append({**p, "score": round(score, 1)})
        except:
            pass

    scored.sort(key=lambda x: x["score"], reverse=True)
    top5 = scored[:5]
    return jsonify(top5)


# =====================================================
# COVERAGE CALCULATOR
# =====================================================
@app.route("/calculator")
def calculator():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("calculator.html", user=session["user"])


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    age = int(data.get("age", 30))
    members = int(data.get("members", 1))
    city_tier = data.get("city_tier", "tier1")
    existing_conditions = data.get("conditions", [])
    income = int(data.get("income", 500000))

    # Base coverage calculation
    base = 500000
    # Age factor
    if age < 30:
        age_mult = 1.0
    elif age < 45:
        age_mult = 1.5
    elif age < 60:
        age_mult = 2.0
    else:
        age_mult = 3.0

    # City tier
    city_mult = {"tier1": 1.5, "tier2": 1.2, "tier3": 1.0}.get(city_tier, 1.0)

    # Members
    member_mult = 1 + (members - 1) * 0.5

    # Conditions
    condition_add = len(existing_conditions) * 200000

    # Income-based
    income_rec = income * 0.5

    recommended = max(int(base * age_mult * city_mult * member_mult + condition_add), int(income_rec))
    # Round to nearest 5L
    recommended = max(500000, round(recommended / 500000) * 500000)

    # Estimate premium range
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
            "members_factor": member_mult,
            "conditions_add": condition_add
        }
    })


# =====================================================
# PREMIUM PREDICTION
# =====================================================
@app.route("/premium-predict")
def premium_predict():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("premium_predict.html", user=session["user"])


@app.route("/api/predict-premium", methods=["POST"])
def api_predict_premium():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    age = int(data.get("age", 30))
    coverage = int(data.get("coverage", 500000))
    plan_type = data.get("plan_type", "Individual")
    company = data.get("company", "")
    bmi = float(data.get("bmi", 22))
    smoker = data.get("smoker", False)

    all_plans = load_plans()
    relevant = [p for p in all_plans if p["Plan_Type"].lower() == plan_type.lower()]
    if company:
        comp_plans = [p for p in relevant if company.lower() in p["Company"].lower()]
        if comp_plans:
            relevant = comp_plans

    if not relevant:
        relevant = all_plans

    # Weighted average based on coverage proximity
    weights, premiums = [], []
    for p in relevant:
        try:
            pcov = float(p["Coverage_Limit"])
            pprem = float(p["Annual_Premium"])
            dist = abs(pcov - coverage)
            w = 1 / (dist + 1)
            weights.append(w)
            premiums.append(pprem)
        except:
            pass

    if not premiums:
        return jsonify({"error": "No data available"})

    base_pred = sum(w * p for w, p in zip(weights, premiums)) / sum(weights)

    # Adjustments
    age_adj = 1.0
    if age < 30:
        age_adj = 0.85
    elif age < 45:
        age_adj = 1.0
    elif age < 60:
        age_adj = 1.4
    else:
        age_adj = 2.0

    bmi_adj = 1.0
    if bmi > 30:
        bmi_adj = 1.15
    elif bmi > 25:
        bmi_adj = 1.05

    smoker_adj = 1.3 if smoker else 1.0

    predicted = int(base_pred * age_adj * bmi_adj * smoker_adj)
    monthly = int(predicted / 12)

    # Confidence range
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
            "smoker": round(smoker_adj, 2)
        }
    })


# =====================================================
# CLAIM APPROVAL PREDICTION
# =====================================================
@app.route("/claim-predict")
def claim_predict():
    if "user" not in session:
        return redirect(url_for("login"))
    plans_list = load_plans()
    return render_template("claim_predict.html", user=session["user"], plans=plans_list)




@app.route("/api/predict-claim", methods=["POST"])
def api_predict_claim():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    plan_name = data.get("plan_name", "")
    claim_amount = float(data.get("claim_amount", 100000))
    claim_type = data.get("claim_type", "hospitalization")
    waiting_period_done = data.get("waiting_period_done", True)
    pre_existing = data.get("pre_existing", False)
    documents_complete = data.get("documents_complete", True)

    all_plans = load_plans()
    plan = next((p for p in all_plans if p["Plan_Name"] == plan_name), None)

    if not plan:
        return jsonify({"error": "Plan not found"})

    base_csr = float(plan["Claim_Settlement_Ratio_Percent"]) / 100
    coverage_limit = float(plan["Coverage_Limit"])

    # Probability scoring
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
        prob *= 1.05
    elif claim_type == "reimbursement":
        prob *= 0.95

    prob = min(prob, 0.98)
    prob = max(prob, 0.05)

    approval_pct = round(prob * 100, 1)

    tips = []
    if not waiting_period_done:
        tips.append("⚠️ Complete your waiting period before filing a claim.")
    if pre_existing:
        tips.append("📋 Disclose all pre-existing conditions during policy purchase.")
    if not documents_complete:
        tips.append("📁 Ensure all documents (bills, discharge summary, ID) are submitted.")
    if claim_amount > coverage_limit:
        tips.append("💡 Your claim exceeds coverage limit. Consider upgrading your plan.")
    if approval_pct > 80:
        tips.append("✅ Your claim has a high probability of approval.")

    return jsonify({
        "approval_probability": approval_pct,
        "csr": float(plan["Claim_Settlement_Ratio_Percent"]),
        "coverage_limit": int(coverage_limit),
        "tips": tips,
        "verdict": "High" if approval_pct >= 75 else "Medium" if approval_pct >= 50 else "Low"
    })


# =====================================================
# ANALYTICS DASHBOARD
# =====================================================
@app.route("/analytics")
def analytics():
    if "user" not in session:
        return redirect(url_for("login"))
    plans_list = load_plans()

    # Build analytics data
    company_data = {}
    type_data = {"Individual": 0, "Family": 0, "Senior": 0}
    premium_buckets = {"<₹15K": 0, "₹15K-30K": 0, "₹30K-50K": 0, ">₹50K": 0}
    csr_data = []
    rating_data = {}

    for p in plans_list:
        try:
            comp = p["Company"].replace(" Insurance", "").replace(" General", "").replace(" Health", "")
            company_data[comp] = company_data.get(comp, 0) + 1

            pt = p["Plan_Type"]
            if pt in type_data:
                type_data[pt] += 1

            prem = float(p["Annual_Premium"])
            if prem < 15000:
                premium_buckets["<₹15K"] += 1
            elif prem < 30000:
                premium_buckets["₹15K-30K"] += 1
            elif prem < 50000:
                premium_buckets["₹30K-50K"] += 1
            else:
                premium_buckets[">₹50K"] += 1

            csr_data.append({"plan": p["Plan_Name"][:20], "csr": float(p["Claim_Settlement_Ratio_Percent"])})
            rating_data[comp] = max(rating_data.get(comp, 0), float(p["Rating"]))
        except:
            pass

    csr_data.sort(key=lambda x: x["csr"], reverse=True)

    return render_template("analytics.html",
                           user=session["user"],
                           company_data=json.dumps(company_data),
                           type_data=json.dumps(type_data),
                           premium_buckets=json.dumps(premium_buckets),
                           csr_data=json.dumps(csr_data[:10]),
                           rating_data=json.dumps(rating_data),
                           total_plans=len(plans_list))


# =====================================================
# HOSPITAL FINDER
# =====================================================
@app.route("/hospitals")
def hospitals():
    if "user" not in session:
        return redirect(url_for("login"))
    plans_list = load_plans()
    companies = sorted(set(p["Company"] for p in plans_list))
    return render_template("hospitals.html", user=session["user"], companies=companies, plans=plans_list)


# =====================================================
# ADMIN DASHBOARD
# =====================================================
@app.route("/admin")
def admin():
    if "user" not in session:
        return redirect(url_for("login"))
    if session.get("role") != "admin":
        return redirect(url_for("home"))
    users = load_users()
    plans_list = load_plans()
    return render_template("admin.html", users=users, plans=plans_list,
                           user=session["user"], total_users=len(users),
                           total_plans=len(plans_list),
                           current_email=session.get("email",""))


@app.route("/admin/delete-user/<email>", methods=["POST"])
def delete_user(email):
    if session.get("role") != "admin":
        return jsonify({"error": "Unauthorized"}), 401
    users = load_users()
    users = [u for u in users if u["email"] != email]
    save_users(users)
    return redirect(url_for("admin"))


# =====================================================
# PDF EXPORT
# =====================================================
@app.route("/export-pdf")
def export_pdf():
    if "user" not in session:
        return redirect(url_for("login"))
    selected_names = request.args.getlist("plans")
    all_plans = load_plans()
    selected = [p for p in all_plans if p.get("Plan_Name") in selected_names]
    return render_template("export_pdf.html", selected=selected, user=session["user"])


# =====================================================
# API: GET ALL PLANS (for AI advisor)
# =====================================================
@app.route("/api/plans")
def api_plans():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(load_plans())


# =====================================================
# AI ADVISOR PAGE
# =====================================================
@app.route("/advisor")
def advisor():
    if "user" not in session:
        return redirect(url_for("login"))
    plans_list = load_plans()
    plan_summary = [{
        "name": p["Plan_Name"],
        "company": p["Company"],
        "type": p["Plan_Type"],
        "annual_premium": p["Annual_Premium"],
        "coverage": p["Coverage_Limit"],
        "csr": p["Claim_Settlement_Ratio_Percent"],
        "rating": p["Rating"],
        "hospitals": p["Network_Hospitals"],
        "wellness": p["Wellness_Benefit"]
    } for p in plans_list]
    return render_template("advisor.html", user=session["user"],
                           plans_json=json.dumps(plan_summary))


# =====================================================
# AI ADVISOR API — proxies Anthropic securely from backend
# =====================================================
@app.route("/api/advisor", methods=["POST"])
def api_advisor():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    import urllib.request
    import urllib.error

    data = request.json
    messages = data.get("messages", [])
    system_prompt = data.get("system", "")

    # Get API key from environment variable
    api_key = os.environ.get("ANTHROPIC_API_KEY", " ")
    if not api_key:
        return jsonify({"error": "API key not configured. Please set ANTHROPIC_API_KEY environment variable."}), 500

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1000,
        "system": system_prompt,
        "messages": messages
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            text = result.get("content", [{}])[0].get("text", "Sorry, I could not process that.")
            return jsonify({"response": text})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print("Anthropic API error:", err_body)
        return jsonify({"error": f"API error: {e.code}. Check your API key."}), 502
    except Exception as e:
        print("Advisor error:", e)
        return jsonify({"error": "Connection error. Please try again."}), 500


# =====================================================
# RUN APP
# =====================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
