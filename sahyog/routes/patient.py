from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user

from ..models import db, User, Appointment, AuditLog
from ..security import role_required, qr_token
from ..card_image import render_card
from ..audit import log

bp = Blueprint("patient", __name__, url_prefix="/patient")

EDITABLE_PLAIN = ["dob", "gender", "blood_group", "emergency_contact_name"]
EDITABLE_SECRET = ["phone", "address", "allergies", "chronic_conditions", "current_medications",
                   "emergency_contact_phone"]


def card_url(p):
    return f"{current_app.config['PUBLIC_BASE_URL']}/c/{qr_token(p.patient_id, p.card_version)}"


@bp.route("/")
@login_required
@role_required("patient")
def dashboard():
    p = current_user.patient
    access = (AuditLog.query.filter_by(patient_ref=p.patient_id)
              .order_by(AuditLog.ts.desc()).limit(25).all())
    appts = Appointment.query.filter_by(patient_id=p.id).order_by(Appointment.slot.desc()).all()
    doctors = User.query.filter_by(role="doctor", doctor_verified=True).all()
    return render_template("patient_dashboard.html", p=p, access=access, appts=appts, doctors=doctors,
                           card_link=card_url(p))


@bp.route("/profile", methods=["POST"])
@login_required
@role_required("patient")
def update_profile():
    p = current_user.patient
    for f in EDITABLE_PLAIN + EDITABLE_SECRET:
        if f in request.form:
            setattr(p, f, request.form[f].strip()[:500])
    db.session.commit()
    log("update_profile", p.patient_id)
    flash("Profile updated.", "ok")
    return redirect(url_for("patient.dashboard"))


@bp.route("/card.png")
@login_required
@role_required("patient")
def card_png():
    p = current_user.patient
    png = render_card(current_user.name, p.patient_id, p.blood_group, p.dob, card_url(p))
    return Response(png, mimetype="image/png",
                    headers={"Content-Disposition": f"inline; filename={p.patient_id}.png"})


@bp.route("/reissue", methods=["POST"])
@login_required
@role_required("patient")
def reissue():
    """Lost card? New QR token; every previously printed card stops working."""
    p = current_user.patient
    p.card_version += 1
    db.session.commit()
    log("card_reissued", p.patient_id, f"version {p.card_version}")
    flash("New card issued. Old QR codes are now revoked.", "ok")
    return redirect(url_for("patient.dashboard"))


@bp.route("/book", methods=["POST"])
@login_required
@role_required("patient")
def book():
    p = current_user.patient
    doc = User.query.filter_by(id=request.form.get("doctor_id", type=int), role="doctor",
                               doctor_verified=True).first()
    slot = request.form.get("slot", "")
    if not doc or len(slot) < 16:
        flash("Choose a doctor and a time.", "error")
    elif Appointment.query.filter_by(doctor_id=doc.id, slot=slot[:16], status="booked").first():
        flash("That slot is already taken.", "error")
    else:
        db.session.add(Appointment(patient_id=p.id, doctor_id=doc.id, slot=slot[:16],
                                   reason=request.form.get("reason", "")[:200]))
        db.session.commit()
        log("book_appointment", p.patient_id, f"Dr {doc.name} {slot[:16]}")
        flash("Appointment booked.", "ok")
    return redirect(url_for("patient.dashboard"))
