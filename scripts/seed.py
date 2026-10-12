"""Seeds the database with a SYNTHETIC demo dataset (no real patients).

Creates: 1 admin, 4 verified doctors, 1 doctor awaiting verification,
N patients with realistic Indian OPD visits, and exports a de-identified
CSV of the visits to data/synthetic_opd_visits.csv.

    python scripts/seed.py --patients 60
"""
import argparse
import csv
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from faker import Faker  # noqa: E402

from sahyog import create_app  # noqa: E402
from sahyog.models import db, User, Patient, OPDVisit, Appointment  # noqa: E402
from sahyog.security import new_patient_id  # noqa: E402

CASES = [  # (complaint, diagnosis, prescription)
    ("Fever, body ache 3 days", "Viral fever", "Tab Paracetamol 650 mg TDS x 3 days; fluids"),
    ("High fever with chills, headache", "Suspected dengue – NS1 ordered", "Tab Paracetamol 650 mg SOS; CBC + NS1; avoid NSAIDs"),
    ("Burning micturition", "Urinary tract infection", "Tab Nitrofurantoin 100 mg BD x 5 days"),
    ("Cough with sputum 1 week", "Acute bronchitis", "Syp Ambroxol 10 ml TDS; steam inhalation"),
    ("Routine check-up, high sugar on test", "Type 2 diabetes mellitus", "Tab Metformin 500 mg BD after meals; HbA1c in 3 months"),
    ("Headache, giddiness", "Essential hypertension", "Tab Amlodipine 5 mg OD; salt restriction"),
    ("Loose stools 2 days", "Acute gastroenteritis", "ORS; Tab Ofloxacin+Ornidazole BD x 3 days"),
    ("Joint pain, morning stiffness", "Osteoarthritis knee", "Tab Aceclofenac 100 mg SOS; physiotherapy"),
    ("Sneezing, running nose", "Allergic rhinitis", "Tab Levocetirizine 5 mg HS x 7 days"),
    ("Fatigue, breathlessness on exertion", "Iron deficiency anaemia", "Tab Ferrous sulphate 200 mg OD; Hb in 6 weeks"),
    ("Epigastric burning after meals", "Gastritis / GERD", "Cap Pantoprazole 40 mg OD before breakfast x 14 days"),
    ("Itchy circular rash", "Tinea corporis", "Clotrimazole cream BD x 4 weeks; Tab Fluconazole 150 mg weekly"),
]
ALLERGIES = ["", "", "", "Penicillin", "Sulfa drugs", "Peanuts", "Dust mites", "NSAIDs"]
CHRONIC = ["", "", "", "Type 2 diabetes", "Hypertension", "Asthma", "Hypothyroidism"]
BLOOD = ["O+"] * 9 + ["B+"] * 8 + ["A+"] * 6 + ["AB+"] * 2 + ["O-", "B-", "A-"]


def seed(n_patients=60, seed=7):
    fake = Faker("en_IN")
    Faker.seed(seed)
    random.seed(seed)
    app = create_app()
    rows = []
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(email="admin@sahyog.local", name="Admin", role="admin")
        admin.set_password("Admin@12345")
        db.session.add(admin)
        docs = []
        for i, spec in enumerate(["General Physician", "Cardiologist", "Pulmonologist", "Endocrinologist"]):
            d = User(email=f"doctor{i + 1}@sahyog.local", name=fake.name(), role="doctor",
                     registration_no=f"MMC-{random.randint(100000, 999999)}", specialization=spec,
                     doctor_verified=True)
            d.set_password("Doctor@12345")
            docs.append(d)
            db.session.add(d)
        pending = User(email="newdoctor@sahyog.local", name=fake.name(), role="doctor",
                       registration_no="MMC-000000", specialization="Dermatologist")
        pending.set_password("Doctor@12345")
        db.session.add(pending)
        db.session.flush()

        now = datetime.now(timezone.utc)
        for k in range(n_patients):
            u = User(email=f"patient{k + 1}@sahyog.local", name=fake.name(), role="patient")
            u.set_password("Patient@12345")
            db.session.add(u)
            age = random.randint(4, 85)
            chronic = random.choice(CHRONIC) if age >= 30 else random.choice(['', '', 'Asthma'])
            base_wt = min(14 + 2.6 * age, random.uniform(52, 82)) if age < 18 else random.uniform(48, 88)
            p = Patient(user=u, patient_id=new_patient_id(),
                        dob=(now - timedelta(days=365 * age + random.randint(0, 364))).date().isoformat(),
                        gender=random.choice(["Female", "Male"]), blood_group=random.choice(BLOOD),
                        emergency_contact_name=fake.name())
            p.set_pin("123456")
            p.phone = fake.phone_number()
            p.address = fake.address().replace("\n", ", ")
            p.allergies = random.choice(ALLERGIES)
            p.chronic_conditions = chronic
            p.current_medications = {"Type 2 diabetes": "Metformin 500 mg BD", "Hypertension": "Amlodipine 5 mg OD",
                                     "Asthma": "Budesonide inhaler", "Hypothyroidism": "Thyroxine 50 mcg OD"}.get(chronic, "")
            p.emergency_contact_phone = fake.phone_number()
            db.session.add(p)
            for _ in range(random.randint(0, 5)):
                c, dx, rx = random.choice(CASES if age >= 30 else [x for x in CASES if "diabetes" not in x[1]
                                                                   and "hypertension" not in x[1].lower()
                                                                   and "Osteo" not in x[1]])
                fever = "fever" in c.lower()
                v = OPDVisit(patient=p, doctor=random.choice(docs),
                             visit_date=now - timedelta(days=random.randint(1, 720)),
                             bp=(f"{random.randint(95, 115)}/{random.randint(58, 75)}" if age < 18 else f"{random.randint(108, 158 if chronic == 'Hypertension' else 138)}/{random.randint(70, 98)}"),
                             pulse=random.randint(64, 108), weight_kg=round(base_wt + random.uniform(-1.5, 1.5), 1),
                             temperature_c=round(random.uniform(38.0, 39.8) if fever else random.uniform(36.4, 37.2), 1))
                v.complaints, v.diagnosis, v.prescription = c, dx, rx
                db.session.add(v)
                rows.append({"patient_ref": f"P{k + 1:04d}", "age": age, "gender": p.gender,
                             "blood_group": p.blood_group, "chronic": chronic, "visit_date": v.visit_date.date(),
                             "bp": v.bp, "pulse": v.pulse, "temperature_c": v.temperature_c,
                             "weight_kg": v.weight_kg, "complaint": c, "diagnosis": dx})
            if k < 8:
                db.session.add(Appointment(patient=p, doctor=random.choice(docs),
                                           slot=(now + timedelta(days=k + 1)).strftime("%Y-%m-%dT10:30"),
                                           reason="Follow-up"))
        db.session.commit()
        first = Patient.query.first()
        print(f"Seeded {n_patients} patients, {len(rows)} OPD visits.")
        print(f"Example patient: patient1@sahyog.local / Patient@12345 – ID {first.patient_id}, PIN 123456")
    out = Path(__file__).resolve().parents[1] / "data" / "synthetic_opd_visits.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["visit_date"]))
    print("De-identified CSV:", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=60)
    seed(ap.parse_args().patients)
