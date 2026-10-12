from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, login_required, current_user

from ..models import db, User, Patient
from ..security import new_patient_id
from ..audit import log

bp = Blueprint("auth", __name__)


def _home_for(user):
    return url_for({"patient": "patient.dashboard", "doctor": "doctor.dashboard",
                    "admin": "admin.dashboard"}[user.role])


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))
    return render_template("index.html")


def _strong(pw: str) -> bool:
    return len(pw) >= 8 and any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        role = f.get("role", "patient")
        if role not in ("patient", "doctor"):
            role = "patient"
        email = f.get("email", "").strip().lower()
        if not email or not f.get("name"):
            flash("Name and email are required.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        elif not _strong(f.get("password", "")):
            flash("Password must be 8+ characters with letters and digits.", "error")
        elif role == "patient" and not (f.get("pin", "").isdigit() and len(f.get("pin", "")) == 6):
            flash("Choose a 6-digit card PIN.", "error")
        elif role == "doctor" and not f.get("registration_no"):
            flash("Doctors must provide their medical council registration number.", "error")
        else:
            u = User(email=email, name=f["name"].strip(), role=role)
            u.set_password(f["password"])
            if role == "doctor":
                u.registration_no = f["registration_no"].strip()
                u.specialization = f.get("specialization", "General Physician")
            db.session.add(u)
            db.session.flush()
            if role == "patient":
                p = Patient(user=u, patient_id=new_patient_id(), dob=f.get("dob"),
                            gender=f.get("gender"), blood_group=f.get("blood_group"))
                p.set_pin(f["pin"])
                db.session.add(p)
            db.session.commit()
            log("register", u.patient.patient_id if role == "patient" else None, role, actor=email, role=role)
            flash("Account created. " + ("Doctor accounts must be verified by an admin before accessing records."
                                         if role == "doctor" else "Your health card is ready."), "ok")
            return redirect(url_for("auth.login"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = User.query.filter_by(email=email).first()
        limit = current_app.config["MAX_LOGIN_FAILURES"]
        if u and u.failed_logins >= limit:
            log("login_blocked", None, "account locked", actor=email, role=u.role)
            flash("Account locked after repeated failed logins. Contact the administrator.", "error")
        elif u and u.check_password(request.form.get("password", "")):
            u.failed_logins = 0
            db.session.commit()
            login_user(u)
            log("login", u.patient.patient_id if u.patient else None)
            return redirect(_home_for(u))
        else:
            if u:
                u.failed_logins += 1
                db.session.commit()
            log("login_fail", None, "", actor=email or "?", role="?")
            flash("Invalid email or password.", "error")  # same message: no user enumeration
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.index"))
