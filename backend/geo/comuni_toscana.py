"""
HouseRadar — Mapping comuni toscani → provincia.

Lista esaustiva dei 273 comuni delle 10 province toscane (codice ISTAT 2024).
Provincia: codice 2 lettere ufficiale targa auto.

Usato per:
- Normalizzare il campo `citta` + `provincia` degli annunci scraperati
- Filtri dropdown cascade dashboard agente

API:
- COMUNI_TOSCANA: dict comune_lowercase → "XX"
- PROVINCE_TOSCANA: dict "XX" → "Nome provincia"
- estrai_citta_da_indirizzo(indirizzo) -> str | None
- provincia_from_citta(citta) -> str | None
- normalizza_annuncio(indirizzo, zona) -> (citta, provincia)
"""

import re
from typing import Optional, Tuple


PROVINCE_TOSCANA = {
    "AR": "Arezzo",
    "FI": "Firenze",
    "GR": "Grosseto",
    "LI": "Livorno",
    "LU": "Lucca",
    "MS": "Massa-Carrara",
    "PI": "Pisa",
    "PT": "Pistoia",
    "PO": "Prato",
    "SI": "Siena",
}


# ─── 273 comuni toscani (ISTAT 2024) ────────────────────────────────────────
# Chiavi: nome originale (case-insensitive lookup via .lower())
COMUNI_TOSCANA = {
    # ── Provincia di LIVORNO (LI) — 19 comuni
    "Bibbona": "LI",
    "Campiglia Marittima": "LI",
    "Campo nell'Elba": "LI",
    "Capoliveri": "LI",
    "Capraia Isola": "LI",
    "Castagneto Carducci": "LI",
    "Cecina": "LI",
    "Collesalvetti": "LI",
    "Livorno": "LI",
    "Marciana": "LI",
    "Marciana Marina": "LI",
    "Piombino": "LI",
    "Porto Azzurro": "LI",
    "Portoferraio": "LI",
    "Rio": "LI",
    "Rosignano Marittimo": "LI",
    "San Vincenzo": "LI",
    "Sassetta": "LI",
    "Suvereto": "LI",

    # ── Provincia di PISA (PI) — 37 comuni
    "Bientina": "PI",
    "Buti": "PI",
    "Calci": "PI",
    "Calcinaia": "PI",
    "Capannoli": "PI",
    "Casale Marittimo": "PI",
    "Casciana Terme Lari": "PI",
    "Cascina": "PI",
    "Castelfranco di Sotto": "PI",
    "Castellina Marittima": "PI",
    "Castelnuovo di Val di Cecina": "PI",
    "Chianni": "PI",
    "Crespina Lorenzana": "PI",
    "Fauglia": "PI",
    "Guardistallo": "PI",
    "Lajatico": "PI",
    "Montecatini Val di Cecina": "PI",
    "Montescudaio": "PI",
    "Monteverdi Marittimo": "PI",
    "Montopoli in Val d'Arno": "PI",
    "Orciano Pisano": "PI",
    "Palaia": "PI",
    "Peccioli": "PI",
    "Pisa": "PI",
    "Pomarance": "PI",
    "Ponsacco": "PI",
    "Pontedera": "PI",
    "Riparbella": "PI",
    "San Giuliano Terme": "PI",
    "San Miniato": "PI",
    "Santa Croce sull'Arno": "PI",
    "Santa Luce": "PI",
    "Santa Maria a Monte": "PI",
    "Terricciola": "PI",
    "Vecchiano": "PI",
    "Vicopisano": "PI",
    "Volterra": "PI",

    # ── Provincia di FIRENZE (FI) — 41 comuni
    "Bagno a Ripoli": "FI",
    "Barberino di Mugello": "FI",
    "Barberino Tavarnelle": "FI",
    "Borgo San Lorenzo": "FI",
    "Calenzano": "FI",
    "Campi Bisenzio": "FI",
    "Capraia e Limite": "FI",
    "Castelfiorentino": "FI",
    "Cerreto Guidi": "FI",
    "Certaldo": "FI",
    "Dicomano": "FI",
    "Empoli": "FI",
    "Fiesole": "FI",
    "Figline e Incisa Valdarno": "FI",
    "Firenze": "FI",
    "Firenzuola": "FI",
    "Fucecchio": "FI",
    "Gambassi Terme": "FI",
    "Greve in Chianti": "FI",
    "Impruneta": "FI",
    "Lastra a Signa": "FI",
    "Londa": "FI",
    "Marradi": "FI",
    "Montaione": "FI",
    "Montelupo Fiorentino": "FI",
    "Montespertoli": "FI",
    "Palazzuolo sul Senio": "FI",
    "Pelago": "FI",
    "Pontassieve": "FI",
    "Reggello": "FI",
    "Rignano sull'Arno": "FI",
    "Rufina": "FI",
    "San Casciano in Val di Pesa": "FI",
    "San Godenzo": "FI",
    "Scandicci": "FI",
    "Scarperia e San Piero": "FI",
    "Sesto Fiorentino": "FI",
    "Signa": "FI",
    "Vaglia": "FI",
    "Vicchio": "FI",
    "Vinci": "FI",

    # ── Provincia di PISTOIA (PT) — 20 comuni
    "Abetone Cutigliano": "PT",
    "Agliana": "PT",
    "Buggiano": "PT",
    "Chiesina Uzzanese": "PT",
    "Lamporecchio": "PT",
    "Larciano": "PT",
    "Marliana": "PT",
    "Massa e Cozzile": "PT",
    "Monsummano Terme": "PT",
    "Montale": "PT",
    "Montecatini-Terme": "PT",
    "Pescia": "PT",
    "Pieve a Nievole": "PT",
    "Pistoia": "PT",
    "Ponte Buggianese": "PT",
    "Quarrata": "PT",
    "Sambuca Pistoiese": "PT",
    "San Marcello Piteglio": "PT",
    "Serravalle Pistoiese": "PT",
    "Uzzano": "PT",

    # ── Provincia di PRATO (PO) — 7 comuni
    "Cantagallo": "PO",
    "Carmignano": "PO",
    "Montemurlo": "PO",
    "Poggio a Caiano": "PO",
    "Prato": "PO",
    "Vaiano": "PO",
    "Vernio": "PO",

    # ── Provincia di LUCCA (LU) — 33 comuni
    "Altopascio": "LU",
    "Bagni di Lucca": "LU",
    "Barga": "LU",
    "Borgo a Mozzano": "LU",
    "Camaiore": "LU",
    "Camporgiano": "LU",
    "Capannori": "LU",
    "Careggine": "LU",
    "Castelnuovo di Garfagnana": "LU",
    "Castiglione di Garfagnana": "LU",
    "Coreglia Antelminelli": "LU",
    "Fabbriche di Vergemoli": "LU",
    "Forte dei Marmi": "LU",
    "Fosciandora": "LU",
    "Gallicano": "LU",
    "Lucca": "LU",
    "Massarosa": "LU",
    "Minucciano": "LU",
    "Molazzana": "LU",
    "Montecarlo": "LU",
    "Pescaglia": "LU",
    "Piazza al Serchio": "LU",
    "Pietrasanta": "LU",
    "Pieve Fosciana": "LU",
    "Porcari": "LU",
    "San Romano in Garfagnana": "LU",
    "Seravezza": "LU",
    "Sillano Giuncugnano": "LU",
    "Stazzema": "LU",
    "Vagli Sotto": "LU",
    "Viareggio": "LU",
    "Villa Basilica": "LU",
    "Villa Collemandina": "LU",

    # ── Provincia di MASSA-CARRARA (MS) — 17 comuni
    "Aulla": "MS",
    "Bagnone": "MS",
    "Carrara": "MS",
    "Casola in Lunigiana": "MS",
    "Comano": "MS",
    "Filattiera": "MS",
    "Fivizzano": "MS",
    "Fosdinovo": "MS",
    "Licciana Nardi": "MS",
    "Massa": "MS",
    "Montignoso": "MS",
    "Mulazzo": "MS",
    "Podenzana": "MS",
    "Pontremoli": "MS",
    "Tresana": "MS",
    "Villafranca in Lunigiana": "MS",
    "Zeri": "MS",

    # ── Provincia di GROSSETO (GR) — 28 comuni
    "Arcidosso": "GR",
    "Campagnatico": "GR",
    "Capalbio": "GR",
    "Castel del Piano": "GR",
    "Castell'Azzara": "GR",
    "Castiglione della Pescaia": "GR",
    "Cinigiano": "GR",
    "Civitella Paganico": "GR",
    "Follonica": "GR",
    "Gavorrano": "GR",
    "Grosseto": "GR",
    "Isola del Giglio": "GR",
    "Magliano in Toscana": "GR",
    "Manciano": "GR",
    "Massa Marittima": "GR",
    "Monte Argentario": "GR",
    "Monterotondo Marittimo": "GR",
    "Montieri": "GR",
    "Orbetello": "GR",
    "Pitigliano": "GR",
    "Roccalbegna": "GR",
    "Roccastrada": "GR",
    "Santa Fiora": "GR",
    "Scansano": "GR",
    "Scarlino": "GR",
    "Seggiano": "GR",
    "Semproniano": "GR",
    "Sorano": "GR",

    # ── Provincia di SIENA (SI) — 35 comuni
    "Abbadia San Salvatore": "SI",
    "Asciano": "SI",
    "Buonconvento": "SI",
    "Casole d'Elsa": "SI",
    "Castellina in Chianti": "SI",
    "Castelnuovo Berardenga": "SI",
    "Castiglione d'Orcia": "SI",
    "Cetona": "SI",
    "Chianciano Terme": "SI",
    "Chiusdino": "SI",
    "Chiusi": "SI",
    "Colle di Val d'Elsa": "SI",
    "Gaiole in Chianti": "SI",
    "Montalcino": "SI",
    "Montepulciano": "SI",
    "Monteriggioni": "SI",
    "Monteroni d'Arbia": "SI",
    "Monticiano": "SI",
    "Murlo": "SI",
    "Piancastagnaio": "SI",
    "Pienza": "SI",
    "Poggibonsi": "SI",
    "Radda in Chianti": "SI",
    "Radicofani": "SI",
    "Radicondoli": "SI",
    "Rapolano Terme": "SI",
    "San Casciano dei Bagni": "SI",
    "San Gimignano": "SI",
    "San Quirico d'Orcia": "SI",
    "Sarteano": "SI",
    "Siena": "SI",
    "Sinalunga": "SI",
    "Sovicille": "SI",
    "Torrita di Siena": "SI",
    "Trequanda": "SI",

    # ── Provincia di AREZZO (AR) — 36 comuni
    "Anghiari": "AR",
    "Arezzo": "AR",
    "Badia Tedalda": "AR",
    "Bibbiena": "AR",
    "Bucine": "AR",
    "Capolona": "AR",
    "Caprese Michelangelo": "AR",
    "Castel Focognano": "AR",
    "Castel San Niccolò": "AR",
    "Castelfranco Piandiscò": "AR",
    "Castiglion Fibocchi": "AR",
    "Castiglion Fiorentino": "AR",
    "Cavriglia": "AR",
    "Chitignano": "AR",
    "Chiusi della Verna": "AR",
    "Civitella in Val di Chiana": "AR",
    "Cortona": "AR",
    "Foiano della Chiana": "AR",
    "Laterina Pergine Valdarno": "AR",
    "Loro Ciuffenna": "AR",
    "Lucignano": "AR",
    "Marciano della Chiana": "AR",
    "Montemignaio": "AR",
    "Monterchi": "AR",
    "Monte San Savino": "AR",
    "Montevarchi": "AR",
    "Ortignano Raggiolo": "AR",
    "Pieve Santo Stefano": "AR",
    "Poppi": "AR",
    "Pratovecchio Stia": "AR",
    "San Giovanni Valdarno": "AR",
    "Sansepolcro": "AR",
    "Sestino": "AR",
    "Subbiano": "AR",
    "Talla": "AR",
    "Terranuova Bracciolini": "AR",
}


# Lookup case-insensitive
_COMUNI_LC = {k.lower(): (k, v) for k, v in COMUNI_TOSCANA.items()}


# ─── Mapping zone HouseRadar → comune principale (fallback) ──────────────────
# Quando l'annuncio non ha un comune riconoscibile in indirizzo ma ha solo "zona"
# (es. "Costa Livornese") usiamo questa mappa come heuristic finale.
ZONA_TO_DEFAULT_COMUNE = {
    "Livorno Città":      ("Livorno",       "LI"),
    "Costa Livornese":    ("Cecina",        "LI"),
    "Val di Cornia":      ("Piombino",      "LI"),
    "Isola d'Elba":       ("Portoferraio",  "LI"),
    "Hinterland Livorno": ("Collesalvetti", "LI"),
    "Pisa Città":         ("Pisa",          "PI"),
    "Valdera":            ("Pontedera",     "PI"),
    "Valdicecina":        ("Volterra",      "PI"),
    "Litorale Pisano":    ("Pisa",          "PI"),   # Marina di Pisa è frazione → Pisa
    "Valdarno Pisano":    ("San Miniato",   "PI"),
}


def _build_comune_regex():
    """Costruisce un regex unico con tutti i comuni, ordinati per lunghezza
    decrescente (così i nomi composti come "Castagneto Carducci" vincono su "Castagneto")."""
    names = sorted(COMUNI_TOSCANA.keys(), key=lambda x: (-len(x), x))
    # Escape per regex; le parole con apostrofi/spazi sono già gestite.
    escaped = [re.escape(n) for n in names]
    return re.compile(r"(?<![A-Za-zÀ-ÿ])(" + "|".join(escaped) + r")(?![A-Za-zÀ-ÿ])",
                      re.IGNORECASE)


_COMUNE_RE = _build_comune_regex()


def estrai_citta_da_indirizzo(indirizzo: Optional[str]) -> Optional[str]:
    """Cerca il comune nell'indirizzo. Ritorna il nome canonico (es. "Cecina")
    oppure None se non trovato. Match case-insensitive con word boundary.
    Preferisce il match più lungo (es. "Castagneto Carducci" su "Castagneto")."""
    if not indirizzo:
        return None
    matches = _COMUNE_RE.findall(indirizzo)
    if not matches:
        return None
    # Prendi il match più lungo (gestisce ambiguità tipo "San Casciano in Val di Pesa" vs "San Casciano dei Bagni")
    best = max(matches, key=len)
    canon = _COMUNI_LC.get(best.lower())
    return canon[0] if canon else None


def provincia_from_citta(citta: Optional[str]) -> Optional[str]:
    """Ritorna il codice provincia (LI/PI/FI/...) dato il nome del comune."""
    if not citta:
        return None
    found = _COMUNI_LC.get(citta.strip().lower())
    return found[1] if found else None


def normalizza_annuncio(
    indirizzo: Optional[str],
    zona: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Restituisce (citta, provincia) per un annuncio.

    Strategia:
      1. Match per nome comune nell'indirizzo (case-insensitive, word boundary)
      2. Fallback: mapping zona HouseRadar → comune principale
      3. Se zona è già un comune toscano (es. zona="Cecina"), usalo direttamente
    """
    # Step 1: cerca nell'indirizzo
    citta = estrai_citta_da_indirizzo(indirizzo)
    if citta:
        return citta, provincia_from_citta(citta)

    # Step 2: la zona è già un nome di comune?
    citta_da_zona = estrai_citta_da_indirizzo(zona)
    if citta_da_zona:
        return citta_da_zona, provincia_from_citta(citta_da_zona)

    # Step 3: mapping zona HouseRadar → comune default
    if zona and zona in ZONA_TO_DEFAULT_COMUNE:
        c, p = ZONA_TO_DEFAULT_COMUNE[zona]
        return c, p

    return None, None
