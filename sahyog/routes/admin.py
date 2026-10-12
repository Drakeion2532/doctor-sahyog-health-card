from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

from ..models import db, User, AuditLog
from ..security import role_required
from ..audit import log

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@login_required
@role_required("admin")
def dashboard():
    pending = User.query.filter_by(role="doctor", doctor_verified=False).all()
    events = AuditLog.query.order_by(AuditLog.ts.desc()).limit(100).all()
    suspicious = AuditLog.query.filter(AuditLog.action.in_(
        ["pin_fail", "login_fail", "login_blocked", "qr_revoked_or_invalid", "lookup_miss"])).count()
    return render_template("admin_dashboard.html", pending=pending, events=events, suspicious=suspicious)


@bp.route("/verify/<int:uid>", methods=["POST"])
@login_required
@role_required("admin")
def verify(uid):
    u = db.session.get(User, uid)
    if u and u.role == "doctor":
        u.doctor_verified = True
        db.session.commit()
        log("verify_doctor", None, f"{u.email} reg {u.registration_no}")
        flash(f"Dr {u.name} verified.", "ok")
    return redirect(url_for("admin.dashboard"))


@bp.route("/unlock/<int:uid>", methods=["POST"])
@login_required
@role_required("admin")
def unlock(uid):
    u = db.session.get(User, uid)
    if u:
        u.failed_logins = 0
        db.session.commit()
        log("unlock_account", None, u.email)
    return redirect(url_for("admin.dashboard"))
