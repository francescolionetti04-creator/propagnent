"""
HouseRadar — wrapper bcrypt diretto (no passlib).

passlib < 1.7.4 + bcrypt 4.x è rotto: passlib cerca `bcrypt.__about__.__version__`
che bcrypt ha rimosso → AttributeError + warning, e tutti gli hash falliscono
con il messaggio fuorviante "password cannot be longer than 72 bytes".

Usiamo direttamente la libreria `bcrypt` (mantenuta, semplice, stabile).
"""

import bcrypt

BCRYPT_ROUNDS = 12  # default sicuro 2025
MAX_PW_BYTES  = 72  # limite hard di bcrypt


def hash_password(password: str) -> str:
    """Genera hash bcrypt di una password. Tronca input a 72 byte."""
    pw_bytes = password.encode("utf-8")[:MAX_PW_BYTES]
    salt     = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verifica password contro hash bcrypt. Robusto a hash invalidi."""
    if not password or not hashed:
        return False
    try:
        pw_bytes = password.encode("utf-8")[:MAX_PW_BYTES]
        return bcrypt.checkpw(pw_bytes, hashed.encode("utf-8"))
    except Exception:
        return False
