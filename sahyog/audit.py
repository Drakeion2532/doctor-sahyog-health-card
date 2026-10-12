from flask import request
from flask_login import current_user

from .models import db, AuditLog


def log(action: str, patient_ref: str | None = None, detail: str = "", actor: str | None = None,
        role: str | None = None):
    if actor is None:
        actor = current_user.email if current_user.is_authenticated else "anonymous"
        role = current_user.role if current_user.is_authenticated else "public"
    db.session.add(AuditLog(actor=actor, actor_role=role, action=action, patient_ref=patient_ref,
                            ip=request.remote_addr if request else None, detail=detail[:200]))
    db.session.commit()
