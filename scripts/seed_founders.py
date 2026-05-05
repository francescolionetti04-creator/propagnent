"""
HouseRadar — Seed founder accounts.

Eseguito automaticamente al boot se la tabella users è vuota
(vedi backend/main.py @startup_event).

Crea 4 founder con:
  - is_founder=True (bypassa paywall)
  - is_email_verified=True
  - password placeholder (richiede reset al primo login)

Per accedere la prima volta: usa /forgot-password con la tua email
e segui il link che ricevi via Resend.
"""

import os
import sys
import secrets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from auth.users_db import create_user, get_user_by_email, count_users
from passlib.context import CryptContext


pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


FOUNDERS = [
    # (email, role, nome, cognome)
    ("info@houseradar.it",              "agente",     "HouseRadar",    None),
    ("francescolionetti04@gmail.com",   "privato",    "Francesco",     "Lionetti"),
    ("jmk.condor@libero.it",            "privato",    None,            None),
    ("gianlucacelli02@gmail.com",       "consulente", "Gianluca",      "Celli"),
    # Tommaso — slot riservato, attivare quando avremo l'email definitiva
    # ("tommaso.placeholder@example.com", "agente", "Tommaso", None),
]


def run() -> int:
    """Crea i founder mancanti. Ritorna n. record creati."""
    creati = 0
    for email, role, nome, cognome in FOUNDERS:
        if get_user_by_email(email):
            print(f"[seed] {email} già presente — skip")
            continue
        # Password placeholder casuale (32 char) — l'utente farà reset
        placeholder = secrets.token_urlsafe(24)
        try:
            create_user(
                email=email,
                password_hash=pwd.hash(placeholder),
                role=role,
                nome=nome,
                cognome=cognome,
                is_founder=True,
                is_email_verified=True,
            )
            creati += 1
            print(f"[seed] ✓ founder creato: {email} (role={role})")
        except Exception as e:
            print(f"[seed] errore creazione {email}: {e}")
    return creati


def run_if_empty() -> int:
    """Esegue il seed solo se la tabella users è vuota (boot iniziale)."""
    n = count_users()
    if n > 0:
        print(f"[seed] users esistenti: {n} — skip seed founders")
        return 0
    print("[seed] tabella users vuota — eseguo seed founders")
    return run()


if __name__ == "__main__":
    run()
