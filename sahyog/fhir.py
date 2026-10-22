"""Export a patient's record as a FHIR R4 Bundle, so it can move to another hospital or app.

A health card only helps if the record can travel. India's Ayushman Bharat Digital Mission (ABDM)
exchanges health records as HL7 FHIR R4, so the patient can download everything in that format:

    Patient                 demographics, Doctor Sahyog Patient ID, contact details
    Observation             blood group (LOINC 882-1) and per-visit vitals (BP 85354-9, pulse 8867-4,
                            temperature 8310-5, weight 29463-7)
    AllergyIntolerance      one per listed allergy
    Condition               chronic conditions, and each visit's diagnosis (linked to the visit)
    MedicationStatement     current medications
    Encounter               one per OPD visit (ambulatory), with complaints as the reason
    MedicationRequest       each visit's prescription
    Practitioner            the doctors who saw the patient, with their registration numbers

This is plain FHIR R4 (type "collection"). Sharing through ABDM would additionally need the
NRCeS India profiles (e.g. an OPConsultRecord document bundle) and an ABHA-linked consent flow.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

ID_SYSTEM = "https://doctor-sahyog.example/patient-id"
REG_SYSTEM = "https://doctor-sahyog.example/medical-council-registration"
LOINC = "http://loinc.org"
UNITS = "http://unitsofmeasure.org"
GENDER = {"male": "male", "m": "male", "female": "female", "f": "female", "other": "other"}


def _ref(prefix: str, key) -> str:
    """Stable urn:uuid for a resource, so references inside the bundle resolve."""
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'sahyog/{prefix}/{key}')}"


def _items(text: str | None) -> list[str]:
    return [t.strip() for t in re.split(r"[,;\n]", text or "") if t.strip() and t.strip().lower() not in ("none", "nil", "-")]


def _quantity(code, display, value, unit, ucum, patient_ref, enc_ref, when):
    return {"resourceType": "Observation", "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                      "code": "vital-signs"}]}],
            "code": {"coding": [{"system": LOINC, "code": code, "display": display}], "text": display},
            "subject": {"reference": patient_ref}, "encounter": {"reference": enc_ref}, "effectiveDateTime": when,
            "valueQuantity": {"value": value, "unit": unit, "system": UNITS, "code": ucum}}


def patient_bundle(p) -> dict:
    pref = _ref("patient", p.patient_id)
    entries = []

    def add(resource, key):
        full = _ref(resource["resourceType"].lower(), key)
        entries.append({"fullUrl": full, "resource": resource})
        return full

    patient = {"resourceType": "Patient",
               "identifier": [{"system": ID_SYSTEM, "value": p.patient_id}],
               "name": [{"text": p.user.name}]}
    if p.gender:
        patient["gender"] = GENDER.get(p.gender.strip().lower(), "unknown")
    if p.dob and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.dob):
        patient["birthDate"] = p.dob
    if p.phone:
        patient["telecom"] = [{"system": "phone", "value": p.phone}]
    if p.address:
        patient["address"] = [{"text": p.address}]
    if p.emergency_contact_name:
        patient["contact"] = [{"name": {"text": p.emergency_contact_name},
                               **({"telecom": [{"system": "phone", "value": p.emergency_contact_phone}]}
                                  if p.emergency_contact_phone else {})}]
    entries.append({"fullUrl": pref, "resource": patient})

    if p.blood_group:
        add({"resourceType": "Observation", "status": "final",
             "code": {"coding": [{"system": LOINC, "code": "882-1", "display": "ABO and Rh group [Type] in Blood"}],
                      "text": "Blood group"},
             "subject": {"reference": pref}, "valueString": p.blood_group}, f"{p.patient_id}/blood")
    for i, a in enumerate(_items(p.allergies)):
        add({"resourceType": "AllergyIntolerance", "patient": {"reference": pref}, "code": {"text": a},
             "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                                            "code": "active"}]}}, f"{p.patient_id}/allergy/{i}")
    for i, c in enumerate(_items(p.chronic_conditions)):
        add({"resourceType": "Condition", "subject": {"reference": pref}, "code": {"text": c},
             "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                            "code": "active"}]},
             "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                       "code": "problem-list-item"}]}]}, f"{p.patient_id}/chronic/{i}")
    for i, m in enumerate(_items(p.current_medications)):
        add({"resourceType": "MedicationStatement", "status": "active", "subject": {"reference": pref},
             "medicationCodeableConcept": {"text": m}}, f"{p.patient_id}/med/{i}")

    practitioners = {}
    for v in p.visits:
        d = v.doctor
        if d.id not in practitioners:
            prac = {"resourceType": "Practitioner", "name": [{"text": d.name}]}
            if d.registration_no:
                prac["identifier"] = [{"system": REG_SYSTEM, "value": d.registration_no}]
            practitioners[d.id] = add(prac, f"doctor/{d.id}")
        when = (v.visit_date if v.visit_date.tzinfo else v.visit_date.replace(tzinfo=timezone.utc)).isoformat()
        enc = {"resourceType": "Encounter", "status": "finished",
               "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB",
                         "display": "ambulatory"},
               "subject": {"reference": pref}, "period": {"start": when},
               "participant": [{"individual": {"reference": practitioners[d.id], "display": d.name}}]}
        if v.complaints:
            enc["reasonCode"] = [{"text": v.complaints}]
        eref = add(enc, f"visit/{v.id}")
        if v.diagnosis:
            add({"resourceType": "Condition", "subject": {"reference": pref}, "encounter": {"reference": eref},
                 "code": {"text": v.diagnosis}, "recordedDate": when,
                 "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category",
                                           "code": "encounter-diagnosis"}]}]}, f"visit/{v.id}/dx")
        if v.prescription:
            add({"resourceType": "MedicationRequest", "status": "completed", "intent": "order",
                 "subject": {"reference": pref}, "encounter": {"reference": eref}, "authoredOn": when,
                 "requester": {"reference": practitioners[d.id]},
                 "medicationCodeableConcept": {"text": v.prescription},
                 "dosageInstruction": [{"text": v.prescription}]}, f"visit/{v.id}/rx")
        bp = re.fullmatch(r"\s*(\d{2,3})\s*/\s*(\d{2,3})\s*", v.bp or "")
        if bp:
            add({"resourceType": "Observation", "status": "final",
                 "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                           "code": "vital-signs"}]}],
                 "code": {"coding": [{"system": LOINC, "code": "85354-9", "display": "Blood pressure panel"}],
                          "text": "Blood pressure"},
                 "subject": {"reference": pref}, "encounter": {"reference": eref}, "effectiveDateTime": when,
                 "component": [
                     {"code": {"coding": [{"system": LOINC, "code": "8480-6", "display": "Systolic blood pressure"}]},
                      "valueQuantity": {"value": int(bp.group(1)), "unit": "mmHg", "system": UNITS, "code": "mm[Hg]"}},
                     {"code": {"coding": [{"system": LOINC, "code": "8462-4", "display": "Diastolic blood pressure"}]},
                      "valueQuantity": {"value": int(bp.group(2)), "unit": "mmHg", "system": UNITS, "code": "mm[Hg]"}}]},
                f"visit/{v.id}/bp")
        if v.pulse:
            add(_quantity("8867-4", "Heart rate", v.pulse, "beats/minute", "/min", pref, eref, when), f"visit/{v.id}/pulse")
        if v.temperature_c:
            add(_quantity("8310-5", "Body temperature", v.temperature_c, "°C", "Cel", pref, eref, when), f"visit/{v.id}/temp")
        if v.weight_kg:
            add(_quantity("29463-7", "Body weight", v.weight_kg, "kg", "kg", pref, eref, when), f"visit/{v.id}/weight")

    return {"resourceType": "Bundle", "type": "collection",
            "identifier": {"system": ID_SYSTEM, "value": f"{p.patient_id}-export"},
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "entry": entries}
