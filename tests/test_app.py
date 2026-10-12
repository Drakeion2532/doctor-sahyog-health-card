import re

import pytest

from sahyog import create_app
from sahyog.models import db, User, Patient, AuditLog
from sahyog.security import new_patient_id, valid_patient_id, generate_key


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path}/t.db",
                      "FIELD_ENCRYPTION_KEY": generate_key(), "SECRET_KEY": "test"})
    with app.app_context():
        admin = User(email="admin@x.io", name="Admin", role="admin"); admin.set_password("Admin12345")
        doc = User(email="doc@x.io", name="Doc", role="doctor", registration_no="R1", doctor_verified=True)
        doc.set_password("Doctor12345")
        db.session.add_all([admin, doc]); db.session.commit()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def register_patient(client, email="pat@x.io"):
    return client.post("/register", data={"role": "patient", "name": "Asha", "email": email,
                                          "password": "Secret123", "pin": "654321", "dob": "1990-01-01",
                                          "gender": "Female", "blood_group": "B+"}, follow_redirects=True)


def login(client, email, pw):
    return client.post("/login", data={"email": email, "password": pw}, follow_redirects=True)


def test_patient_id_checksum():
    pid = new_patient_id()
    assert valid_patient_id(pid)
    bad = pid[:-1] + ("2" if pid[-1] != "2" else "3")
    assert not valid_patient_id(bad)


def test_register_creates_card_and_encrypts(app, client):
    register_patient(client)
    login(client, "pat@x.io", "Secret123")
    client.post("/patient/profile", data={"allergies": "Penicillin"})
    with app.app_context():
        p = Patient.query.first()
        assert valid_patient_id(p.patient_id)
        assert p.allergies == "Penicillin"
        assert "Penicillin" not in p._allergies  # stored encrypted
    r = client.get("/patient/card.png")
    assert r.status_code == 200 and r.data[:4] == b"\x89PNG"


def test_weak_password_rejected(client):
    r = client.post("/register", data={"role": "patient", "name": "x", "email": "w@x.io",
                                       "password": "short", "pin": "123456"}, follow_redirects=True)
    assert b"8+ characters" in r.data


def test_rbac_patient_cannot_open_doctor_pages(client):
    register_patient(client)
    login(client, "pat@x.io", "Secret123")
    assert client.get("/doctor/").status_code == 403
    assert client.get("/admin/").status_code == 403


def test_unverified_doctor_blocked(client):
    client.post("/register", data={"role": "doctor", "name": "New", "email": "nd@x.io",
                                   "password": "Doctor12345", "registration_no": "R9"})
    login(client, "nd@x.io", "Doctor12345")
    assert client.get("/doctor/").status_code == 403


def _qr_path(app):
    with app.test_request_context():
        from sahyog.routes.patient import card_url
        with app.app_context():
            return "/" + card_url(Patient.query.first()).split("/", 3)[3]


def test_qr_scan_shows_only_emergency_info_and_pin_unlocks(app, client):
    register_patient(client)
    login(client, "pat@x.io", "Secret123")
    client.post("/patient/profile", data={"allergies": "Peanuts"})
    client.get("/logout")
    path = _qr_path(app)
    r = client.get(path)
    assert b"Peanuts" in r.data and b"Medical history" not in r.data
    r = client.post(path, data={"pin": "654321"})
    assert b"Medical history" in r.data


def test_pin_lockout_after_5_failures(app, client):
    register_patient(client)
    path = _qr_path(app)
    for _ in range(5):
        client.post(path, data={"pin": "000000"})
    r = client.post(path, data={"pin": "654321"})  # correct PIN, but locked
    assert b"locked" in r.data and b"Medical history" not in r.data


def test_reissue_revokes_old_qr(app, client):
    register_patient(client)
    login(client, "pat@x.io", "Secret123")
    old = _qr_path(app)
    client.post("/patient/reissue")
    assert client.get(old).status_code == 410
    assert client.get(_qr_path(app)).status_code == 200


def test_tampered_qr_rejected(app, client):
    register_patient(client)
    path = _qr_path(app)
    assert client.get(path[:-3] + "AAA").status_code == 404


def test_doctor_access_is_audited_and_opd_saved(app, client):
    register_patient(client)
    with app.app_context():
        pid = Patient.query.first().patient_id
    login(client, "doc@x.io", "Doctor12345")
    r = client.get(f"/doctor/patient/{pid}")
    assert r.status_code == 200
    client.post(f"/doctor/patient/{pid}/opd", data={"complaints": "fever", "diagnosis": "Viral fever",
                                                    "prescription": "PCM", "pulse": "90"})
    with app.app_context():
        acts = [a.action for a in AuditLog.query.filter_by(patient_ref=pid)]
        assert "view_full_record" in acts and "add_opd" in acts
        assert Patient.query.first().visits[0].diagnosis == "Viral fever"


def test_login_lockout_and_no_user_enumeration(client):
    r1 = login(client, "nobody@x.io", "x")
    r2 = login(client, "doc@x.io", "wrong")
    assert b"Invalid email or password" in r1.data and b"Invalid email or password" in r2.data
    for _ in range(5):
        login(client, "doc@x.io", "wrong")
    r = login(client, "doc@x.io", "Doctor12345")
    assert b"locked" in r.data


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
