from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from ..models import db, Patient, OPDVisit, Appointment
from ..security import role_required, valid_patient_id
from ..audit import log

bp = Blueprint("doctor", __name__, url_prefix="/doctor")


@bp.route("/", methods=["GET", "POST"])
@login_required
@role_required("doctor")
def dashboard():
    if request.method == "POST":
        pid = request.form.get("patient_id", "").strip().upper()
        if not valid_patient_id(pid):
            flash("That is not a valid Patient ID (check the characters).", "error")
        else:
            return redirect(url_for("doctor.record", pid=pid))
    appts = (Appointment.query.filter_by(doctor_id=current_user.id, status="booked")
             .order_by(Appointment.slot).all())
    return render_template("doctor_dashboard.html", appts=appts)


def _patient_or_404(pid):
    p = Patient.query.filter_by(patient_id=pid).first()
    if not p:
        log("lookup_miss", pid)
        abort(404)
    return p


@bp.route("/patient/<pid>")
@login_required
@role_required("doctor")
def record(pid):
    p = _patient_or_404(pid)
    log("view_full_record", p.patient_id, f"Dr {current_user.name}")
    return render_template("doctor_record.html", p=p)


@bp.route("/patient/<pid>/opd", methods=["POST"])
@login_required
@role_required("doctor")
def add_opd(pid):
    p = _patient_or_404(pid)
    f = request.form
    v = OPDVisit(patient=p, doctor_id=current_user.id, bp=f.get("bp", "")[:10],
                 pulse=f.get("pulse", type=int), temperature_c=f.get("temperature_c", type=float),
                 weight_kg=f.get("weight_kg", type=float), follow_up=f.get("follow_up", "")[:10])
    v.complaints = f.get("complaints", "")
    v.diagnosis = f.get("diagnosis", "")
    v.prescription = f.get("prescription", "")
    v.notes = f.get("notes", "")
    db.session.add(v)
    for a in Appointment.query.filter_by(patient_id=p.id, doctor_id=current_user.id, status="booked"):
        a.status = "completed"
    db.session.commit()
    log("add_opd", p.patient_id, f"Dr {current_user.name}: {v.diagnosis[:80]}")
    flash("OPD entry saved.", "ok")
    return redirect(url_for("doctor.record", pid=pid))
