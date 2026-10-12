from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

from .security import encrypt, decrypt

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class EncryptedField:
    """Descriptor: attribute `foo` reads/writes encrypted column `_foo`."""

    def __set_name__(self, owner, name):
        self.col = "_" + name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return decrypt(getattr(obj, self.col))

    def __set__(self, obj, value):
        setattr(obj, self.col, encrypt(value))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # patient | doctor | admin
    # doctor-only
    registration_no = db.Column(db.String(40))      # medical council registration number
    specialization = db.Column(db.String(80))
    doctor_verified = db.Column(db.Boolean, default=False)
    failed_logins = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=now)

    patient = db.relationship("Patient", back_populates="user", uselist=False)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True)
    patient_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    card_version = db.Column(db.Integer, default=1)
    pin_hash = db.Column(db.String(256))
    pin_failures = db.Column(db.Integer, default=0)
    pin_locked_until = db.Column(db.DateTime(timezone=True))

    # public "emergency" fields – shown when the QR code is scanned
    dob = db.Column(db.String(10))
    gender = db.Column(db.String(10))
    blood_group = db.Column(db.String(5))
    emergency_contact_name = db.Column(db.String(80))

    # sensitive fields – encrypted at rest
    _phone = db.Column(db.Text)
    _address = db.Column(db.Text)
    _allergies = db.Column(db.Text)
    _chronic_conditions = db.Column(db.Text)
    _current_medications = db.Column(db.Text)
    _emergency_contact_phone = db.Column(db.Text)
    phone = EncryptedField()
    address = EncryptedField()
    allergies = EncryptedField()
    chronic_conditions = EncryptedField()
    current_medications = EncryptedField()
    emergency_contact_phone = EncryptedField()

    user = db.relationship("User", back_populates="patient")
    visits = db.relationship("OPDVisit", back_populates="patient", order_by="OPDVisit.visit_date.desc()")

    def set_pin(self, pin):
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin):
        return bool(self.pin_hash) and check_password_hash(self.pin_hash, pin)


class OPDVisit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patient.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    visit_date = db.Column(db.DateTime(timezone=True), default=now)
    bp = db.Column(db.String(10))
    pulse = db.Column(db.Integer)
    temperature_c = db.Column(db.Float)
    weight_kg = db.Column(db.Float)
    _complaints = db.Column(db.Text)
    _diagnosis = db.Column(db.Text)
    _prescription = db.Column(db.Text)
    _notes = db.Column(db.Text)
    complaints = EncryptedField()
    diagnosis = EncryptedField()
    prescription = EncryptedField()
    notes = EncryptedField()
    follow_up = db.Column(db.String(10))

    patient = db.relationship("Patient", back_populates="visits")
    doctor = db.relationship("User")


class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patient.id"), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    slot = db.Column(db.String(16), nullable=False)  # ISO "YYYY-MM-DDTHH:MM"
    reason = db.Column(db.String(200))
    status = db.Column(db.String(12), default="booked")  # booked | completed | cancelled
    patient = db.relationship("Patient")
    doctor = db.relationship("User")


class AuditLog(db.Model):
    """Every read/write of medical data is recorded and visible to the patient."""
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime(timezone=True), default=now, index=True)
    actor = db.Column(db.String(120))       # email or "public-qr-scan"
    actor_role = db.Column(db.String(10))
    action = db.Column(db.String(40))       # view_full_record, qr_scan, add_opd, pin_fail ...
    patient_ref = db.Column(db.String(20), index=True)
    ip = db.Column(db.String(45))
    detail = db.Column(db.String(200))
