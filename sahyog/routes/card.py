"""Public QR endpoint.

Scanning the card (anyone, e.g. a paramedic) shows ONLY emergency info:
name, blood group, allergies, chronic conditions, emergency contact.
The full OPD history needs the patient's 6-digit PIN (5 tries, then 15-min lockout).
"""
from flask import Blueprint, render_template, request, abort, session, flash

from ..models import db, Patient
from ..security import parse_qr_token, pin_locked, register_pin_failure
from ..audit import log

bp = Blueprint("card", __name__)


def _patient_from_token(token):
    parsed = parse_qr_token(token)
    if not parsed:
        abort(404)
    pid, version = parsed
    p = Patient.query.filter_by(patient_id=pid).first()
    if not p or p.card_version != version:
        log("qr_revoked_or_invalid", pid, actor="public-qr-scan", role="public")
        abort(410, "This card has been revoked.")
    return p


@bp.route("/c/<token>", methods=["GET", "POST"])
def scan(token):
    p = _patient_from_token(token)
    unlocked_key = f"unlocked:{p.patient_id}"
    if request.method == "POST":
        if pin_locked(p):
            flash("Too many wrong PINs. Try again in 15 minutes.", "error")
        elif p.check_pin(request.form.get("pin", "")):
            p.pin_failures = 0
            session[unlocked_key] = True
            log("pin_unlock", p.patient_id, actor="card-holder", role="patient")
        else:
            register_pin_failure(p)
            log("pin_fail", p.patient_id, actor="public-qr-scan", role="public")
            flash("Incorrect PIN.", "error")
        db.session.commit()
    else:
        log("qr_scan", p.patient_id, "emergency view", actor="public-qr-scan", role="public")
    return render_template("card_public.html", p=p, unlocked=session.get(unlocked_key, False),
                           locked=pin_locked(p))
