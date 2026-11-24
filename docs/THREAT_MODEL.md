# Threat model: Doctor Sahyog

A STRIDE review of the health-card app: what we protect, where trust changes hands, what could go
wrong, the control that answers each threat, the test that proves it, and the risk that is left.

## Assets

| Asset | Why it matters |
|---|---|
| Medical fields (allergies, conditions, medications, diagnoses, prescriptions) | Sensitive personal health data; a leak is permanent |
| Contact data (phone, address) | Enables stalking or fraud |
| QR card token | Grants emergency read access to anyone holding the card |
| Patient PIN | Unlocks the full history from a card scan |
| Signing key (`SAHYOG_SECRET_KEY`) and field key (`SAHYOG_FIELD_KEY`) | Whoever holds them can forge QR tokens and sessions, or decrypt every record |
| Audit log | The patient's only way to see who opened their record |

## Trust boundaries

1. **Internet → app.** Anyone can reach the login page and the QR-scan route.
2. **Paramedic with a card → emergency view.** Possession of the card is the only credential.
3. **Patient PIN → full history.** A second factor on top of the card.
4. **Verified doctor → any record by Patient ID.** Highest-privilege human role apart from admin.
5. **App → database.** The database is assumed stealable; it must be useless without the keys.

## STRIDE

| | Threat | Control | Proven by test |
|---|---|---|---|
| **S**poofing | Forged or guessed QR link | HMAC-SHA256 signed token with no medical data; tampered tokens get 404 | `test_tampered_qr_rejected`, `test_every_genuine_qr_token_verifies` |
| | Forged sessions or QR tokens from a published default key | No fixed default: without `SAHYOG_SECRET_KEY` a random key is generated per install and kept out of git | `test_no_public_default_signing_key` |
| | Fake doctor | No record access until an admin verifies the registration number | `test_unverified_doctor_blocked` |
| | Password guessing | Salted scrypt/pbkdf2 hashes, strength rule, lockout after 5 failures, one generic error (no user enumeration) | `test_login_lockout_and_no_user_enumeration`, `test_weak_password_rejected` |
| **T**ampering | Editing or deleting audit entries to hide snooping | Append-only audit log; the ORM blocks updates and deletes | `test_audit_log_is_append_only` |
| | Cross-site request forgery | Flask-WTF CSRF tokens, `SameSite` cookies, CSP `form-action 'self'` | `test_hardened_csp_and_permissions_policy` |
| **R**epudiation | "I never opened that record" | Every view, scan, edit and failure is logged with actor, role, IP and time; patients can see it | `test_doctor_access_is_audited_and_opd_saved` |
| **I**nformation disclosure | Stolen database | Field-level Fernet encryption (AES-128-CBC + HMAC-SHA256); key outside the database | `test_register_creates_card_and_encrypts` |
| | Card scan shows too much | Scan shows emergency fields only; full history needs the PIN | `test_qr_scan_shows_only_emergency_info_and_pin_unlocks` |
| | Session theft over plain HTTP | `Secure` cookie and HSTS automatically on HTTPS deployments; `HttpOnly` always | `test_https_deployment_sets_secure_cookie_and_hsts` |
| | Clickjacking, content sniffing, cached pages | `X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`, `nosniff`, `Cache-Control: no-store` | `test_security_headers` |
| **D**enial of service | PIN brute force locks patients out or guesses the PIN | 5 wrong PINs → 15-minute lockout, every failure logged | `test_pin_lockout_after_5_failures` |
| **E**levation of privilege | Patient opens doctor or admin pages | Role-based access check on every route | `test_rbac_patient_cannot_open_doctor_pages` |
| | Lost card keeps working | Reissue bumps the card version; old QR codes return 410 Gone | `test_reissue_revokes_old_qr` |

## Residual risks (not solved here)

* **No rate limiting by IP.** Lockouts are per account and per card; a distributed attacker can still
  probe many accounts. A reverse proxy or Flask-Limiter would add this.
* **Key management is environment variables.** Production should use a secrets manager with key rotation;
  rotating the field key needs a re-encryption job, which is not written.
* **The card is a bearer credential.** Anyone holding it sees the emergency view. That is the intended
  trade-off for paramedics, but it is a trade-off.
* **No MFA for doctors.** A phished doctor password gives record access until an admin disables the account.
* **SQLite in the default setup** is for local runs only.
