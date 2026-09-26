import os
from functools import wraps
from flask import Blueprint, request, session, redirect, url_for, render_template, current_app

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username", "") == current_app.config.get("ADMIN_USERNAME", os.environ.get("ADMIN_USERNAME", "admin")) and request.form.get("password", "") == current_app.config.get("ADMIN_PASSWORD", os.environ.get("ADMIN_PASSWORD", "change-me")):
            session["user"] = request.form.get("username", "")
            return redirect(url_for("main.index"))
        error = "Identifiants invalides"
    return render_template("login.html", error=error)

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped
