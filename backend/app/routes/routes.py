"""
app/routes/routes.py
Page routes (render Krish's real templates) plus the API endpoints
they call:
    GET  /              -> landing page (index.html)
    GET  /login           -> login page
    POST /api/login         -> real auth (auto-registers on first login), starts a session
    POST /api/logout          -> clears the session
    GET  /dashboard             -> requires login; redirects to /login otherwise
    GET  /workpage                -> requires login; the actual analyzer tool
    GET  /api/session               -> lets JS check if already logged in
    POST /api/analyze                 -> runs the full audit pipeline for a URL
"""
import threading
import traceback
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for

from app.config import Config
from app.services.pipeline import run_pipeline_core
from app.services.scoring import build_frontend_data
from app.agents.promo_email_agent import send_promo_email
from app.utils import users_store

api_bp = Blueprint("api", __name__)


def login_required(view):
    """Redirects to /login if there's no logged-in session. Used on
    every page that shouldn't be reachable without an account."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_email"):
            return redirect(url_for("api.login_page"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------

@api_bp.route("/")
def index():
    return render_template("index.html")


@api_bp.route("/login")
def login_page():
    if session.get("user_email"):
        return redirect(url_for("api.dashboard_page"))
    return render_template("login.html")


@api_bp.route("/dashboard")
@login_required
def dashboard_page():
    return render_template("dashboard.html", user_name=session.get("user_name", "there"))


@api_bp.route("/workpage")
@login_required
def workpage_page():
    return render_template("workpage.html")


# ---------------------------------------------------------------------
# Auth API
# ---------------------------------------------------------------------

@api_bp.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "Please enter a valid email address"}), 400
    if not password:
        return jsonify({"error": "Please enter a password"}), 400

    user, error = users_store.authenticate(email, password)
    if error:
        return jsonify({"error": error}), 401

    session["user_email"] = user["email"]
    session["user_name"] = user["name"]
    return jsonify({"ok": True, "email": user["email"], "name": user["name"]})


@api_bp.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@api_bp.route("/api/session")
def get_session():
    if session.get("user_email"):
        return jsonify({"logged_in": True, "email": session["user_email"], "name": session.get("user_name", "")})
    return jsonify({"logged_in": False})


# ---------------------------------------------------------------------
# Analysis API
# ---------------------------------------------------------------------

@api_bp.route("/api/analyze", methods=["POST"])
def analyze():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing 'url' in request body"}), 400
    if not url.startswith("http"):
        url = "https://" + url

    try:
        domain = urlparse(url).hostname or url
    except Exception:
        return jsonify({"error": "Invalid URL"}), 400

    try:
        result = run_pipeline_core(url, max_pages=Config.MAX_PAGES, skip_tests=Config.SKIP_TESTS)
        data = build_frontend_data(
            domain=domain,
            pages=result["pages"],
            crawl_errors=result["crawl_errors"],
            tech_findings=result["tech_findings"],
            security_findings=result["security_findings"],
            content_analysis=result["content_analysis"],
            modernization=result["modernization"],
            test_results=result["test_results"],
        )

        user_email = session.get("user_email")
        if user_email:
            threading.Thread(
                target=send_promo_email,
                args=(user_email, session.get("user_name", ""), domain, data),
                daemon=True,
            ).start()

        return jsonify({"domain": domain, "url": url, "data": data})
    except Exception as e:
        # Full technical detail goes to the backend log only; the
        # frontend gets a short, friendly message it can display as-is.
        print(f"[routes] /api/analyze failed for {url}: {e}")
        traceback.print_exc()
        return jsonify({"error": "We couldn't complete the analysis for this website. Please double-check "
                                  "the URL and try again."}), 500
