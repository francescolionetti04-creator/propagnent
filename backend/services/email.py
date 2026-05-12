"""
HouseRadar — Email transazionali via Resend.

ENV vars:
  RESEND_API_KEY     — chiave API Resend
  EMAIL_FROM         — mittente (default: HouseRadar <onboarding@resend.dev>)
                       finché DNS Aruba non sono configurati per houseradar.it

Tutte le funzioni sono "best-effort": loggano errori ma non sollevano,
così un fallimento email non blocca signup/reset/etc.
"""

import os

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "HouseRadar <onboarding@resend.dev>")

_BLUE  = "#185FA5"
_GREEN = "#5DCAA5"


def _send(to: str, subject: str, html: str) -> bool:
    """Wrapper Resend. Ritorna True se inviato, False altrimenti."""
    if not RESEND_API_KEY:
        print(f"[Email] RESEND_API_KEY mancante — skip invio a {to} ({subject!r})")
        return False
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resp = resend.Emails.send({
            "from":    EMAIL_FROM,
            "to":      [to],
            "subject": subject,
            "html":    html,
        })
        print(f"[Email] inviato a {to}: {subject!r} (id={resp.get('id') if isinstance(resp, dict) else 'ok'})")
        return True
    except Exception as e:
        print(f"[Email] errore invio a {to}: {e}")
        return False


def _wrap(content_html: str, preheader: str = "") -> str:
    """Wrapper HTML coerente con il brand HouseRadar."""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<span style="display:none;visibility:hidden;color:transparent">{preheader}</span>
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f5f5f3;padding:40px 20px">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" border="0" style="background:#fff;border-radius:14px;border:1px solid #D3D1C7;overflow:hidden">
      <tr><td style="background:{_BLUE};padding:28px;text-align:center">
        <span style="display:inline-block;color:#fff;font-size:22px;font-weight:700;letter-spacing:-.01em">
          🏠 HouseRadar
        </span>
      </td></tr>
      <tr><td style="padding:36px 36px 28px;color:#1a1a1a;line-height:1.6;font-size:15px">
        {content_html}
      </td></tr>
      <tr><td style="padding:18px 36px;border-top:1px solid #f0f0eb;color:#888;font-size:12px;text-align:center">
        © 2026 HouseRadar · Made in Italy<br>
        <a href="https://houseradar.it" style="color:{_BLUE}">houseradar.it</a>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _btn(url: str, label: str) -> str:
    return f"""
<div style="text-align:center;margin:28px 0">
  <a href="{url}" style="display:inline-block;background:{_BLUE};color:#fff;
     padding:14px 28px;border-radius:10px;font-weight:600;text-decoration:none;font-size:15px">
    {label}
  </a>
</div>"""


# ─── Public API ──────────────────────────────────────────────────────────────

def send_verification_email(to: str, link: str, nome: str | None = None) -> bool:
    saluto = f"Ciao {nome}," if nome else "Ciao,"
    body = f"""
<h2 style="margin:0 0 18px;font-size:22px;font-weight:700">Conferma il tuo account</h2>
<p>{saluto}</p>
<p>Grazie per esserti registrato a HouseRadar. Per attivare il tuo account
clicca sul bottone qui sotto:</p>
{_btn(link, "Verifica email")}
<p style="font-size:13px;color:#666">
  Se il bottone non funziona, copia questo link nel browser:<br>
  <a href="{link}" style="color:{_BLUE};word-break:break-all">{link}</a>
</p>
<p style="font-size:13px;color:#666;margin-top:24px">
  Se non hai richiesto tu la registrazione, ignora questo messaggio.
</p>"""
    return _send(to, "Conferma il tuo account HouseRadar", _wrap(body, "Conferma il tuo account"))


def send_password_reset_email(to: str, link: str, nome: str | None = None) -> bool:
    saluto = f"Ciao {nome}," if nome else "Ciao,"
    body = f"""
<h2 style="margin:0 0 18px;font-size:22px;font-weight:700">Reimposta la tua password</h2>
<p>{saluto}</p>
<p>Hai richiesto di reimpostare la password del tuo account HouseRadar.
Clicca qui sotto per scegliere una nuova password:</p>
{_btn(link, "Reimposta password")}
<p style="font-size:13px;color:#666">
  Il link è valido <strong>1 ora</strong>. Se non hai richiesto tu il reset,
  ignora questa email — la tua password non verrà cambiata.
</p>"""
    return _send(to, "Reimposta la tua password HouseRadar", _wrap(body, "Reset password"))


def send_compratore_match_email(to: str, nome: str | None,
                                 match_count: int, top_matches: list,
                                 lead_id: int | None = None) -> bool:
    """top_matches: lista di dict con keys indirizzo/zona/tipo/mq/prezzo/url_originale."""
    saluto = f"Ciao {nome}," if nome else "Ciao,"

    def _eu(p):
        try:
            return f"€ {int(p):,}".replace(",", ".")
        except Exception:
            return "—"

    cards = []
    for m in (top_matches or [])[:5]:
        url = m.get("url_originale") or m.get("url") or "https://houseradar.it/compratore/dashboard"
        cards.append(f"""
<a href="{url}" style="display:block;text-decoration:none;color:#1a1a1a;
   background:#fff;border:1px solid #D3D1C7;border-radius:12px;padding:16px;margin:10px 0">
  <div style="font-size:16px;font-weight:700;margin-bottom:4px">{m.get('indirizzo') or '—'}</div>
  <div style="color:#666;font-size:13px;margin-bottom:6px">
    {m.get('zona') or ''} · {m.get('tipo') or ''}
    {(' · ' + str(m['mq']) + ' m²') if m.get('mq') else ''}
    {(' · ' + str(m['camere']) + ' camere') if m.get('camere') else ''}
  </div>
  <div style="color:{_BLUE};font-size:18px;font-weight:800">{_eu(m.get('prezzo'))}</div>
</a>""")
    cards_html = "".join(cards) or '<p style="color:#666">Nessun match in evidenza.</p>'

    body = f"""
<h2 style="margin:0 0 12px;font-size:22px;font-weight:700">🏡 {match_count} nuovi annunci match per te</h2>
<p>{saluto}</p>
<p>Abbiamo trovato <strong>{match_count}</strong> nuovi annunci che corrispondono alle tue preferenze:</p>
{cards_html}
{_btn("https://houseradar.it/compratore/dashboard", "Vedi tutti i match")}
<p style="font-size:12px;color:#888;margin-top:24px;text-align:center">
  Non vuoi più ricevere queste email?
  <a href="https://houseradar.it/compratore/dashboard" style="color:{_BLUE}">Disattiva dalle preferenze</a>
</p>"""
    return _send(to, f"🏡 {match_count} nuovi annunci match per te su HouseRadar",
                 _wrap(body, f"{match_count} nuovi annunci match"))


def send_agency_invite_email(
    to: str,
    link: str,
    agency_name: str,
    owner_name: str | None = None,
    invitee_name: str | None = None,
) -> bool:
    saluto = f"Ciao {invitee_name}," if invitee_name else "Ciao,"
    chi = owner_name or "Il titolare"
    body = f"""
<h2 style="margin:0 0 18px;font-size:22px;font-weight:700">Sei stato invitato in agenzia</h2>
<p>{saluto}</p>
<p>{chi} ti ha invitato a far parte di <strong>{agency_name or 'HouseRadar Agenzia'}</strong>
su HouseRadar. Avrai accesso completo alla dashboard agenti, agli annunci aggregati
e a tutti gli strumenti del piano Agenzia — senza pagare nulla.</p>
{_btn(link, "Accetta l'invito")}
<p style="font-size:13px;color:#666">
  Se il bottone non funziona, copia questo link nel browser:<br>
  <a href="{link}" style="color:{_BLUE};word-break:break-all">{link}</a>
</p>
<p style="font-size:13px;color:#666;margin-top:24px">
  Il link è valido 14 giorni. Se non riconosci questo invito, ignora questa email.
</p>"""
    return _send(to, "Sei stato invitato in agenzia su HouseRadar",
                 _wrap(body, f"Invito da {chi}"))


def send_welcome_email(to: str, role: str, nome: str | None = None) -> bool:
    saluto = f"Benvenuto {nome}!" if nome else "Benvenuto in HouseRadar!"
    role_msg = {
        "agente":     "Sei pronto a trovare i tuoi prossimi mandati prima della concorrenza. Inizia subito a esplorare gli annunci aggregati da 6 portali.",
        "consulente": "Hai accesso completo alla dashboard agenti. Trova i tuoi prossimi mandati con il radar HouseRadar.",
        "privato":    "Stai per vendere casa con i migliori agenti della tua zona. Riceverai presto le prime proposte.",
        "compratore": "Stai per ricevere alert sui nuovi annunci nella tua zona. Configura le tue preferenze e lascia che HouseRadar trovi la tua prossima casa.",
    }.get(role, "Benvenuto in HouseRadar.")
    body = f"""
<h2 style="margin:0 0 18px;font-size:22px;font-weight:700">{saluto} 👋</h2>
<p>Il tuo account è ora attivo.</p>
<p>{role_msg}</p>
{_btn("https://houseradar.it/app", "Apri la dashboard")}
<p style="font-size:13px;color:#666">
  Hai domande? Rispondi a questa email — saremo felici di aiutarti.
</p>"""
    return _send(to, "Benvenuto in HouseRadar 👋", _wrap(body, "Benvenuto"))


def send_profilo_contatta_email(
    to: str,
    nome_agente: str,
    nome_mittente: str,
    telefono_mittente: str | None,
    messaggio: str,
) -> bool:
    """Notifica all'agente: un visitatore del profilo pubblico ha inviato un messaggio."""
    import html as _html
    saluto = f"Ciao {nome_agente.strip()}," if nome_agente.strip() else "Ciao,"
    tel_html = (f'<p><strong>Telefono:</strong> '
                f'<a href="tel:{_html.escape(telefono_mittente)}" '
                f'style="color:{_BLUE}">{_html.escape(telefono_mittente)}</a></p>') \
                if telefono_mittente else ""
    body = f"""
<h2 style="margin:0 0 18px;font-size:22px;font-weight:700">📞 Nuova richiesta dal tuo profilo pubblico</h2>
<p>{saluto}</p>
<p>Hai ricevuto una nuova richiesta di contatto tramite il tuo profilo pubblico su HouseRadar.</p>
<div style="background:#f5f5f3;border:1px solid #D3D1C7;border-radius:10px;padding:16px;margin:18px 0">
  <p><strong>Nome:</strong> {_html.escape(nome_mittente)}</p>
  {tel_html}
  <p style="margin-top:10px"><strong>Messaggio:</strong></p>
  <p style="white-space:pre-wrap;color:#333">{_html.escape(messaggio)}</p>
</div>
<p style="font-size:13px;color:#666;margin-top:24px">
  Rispondi direttamente a questo contatto — non lasciare che la concorrenza ti freghi il lead!
</p>"""
    return _send(to, f"📞 Nuova richiesta da {nome_mittente} su HouseRadar",
                 _wrap(body, "Nuova richiesta profilo"))
