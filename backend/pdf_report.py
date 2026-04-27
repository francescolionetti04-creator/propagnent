"""
HouseRadar — PDF Report Generator
Genera report professionali di valutazione immobiliare con dati OMI.
Usa ReportLab (puro Python, zero dipendenze di sistema).
"""

import io
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# ── Palette HouseRadar ────────────────────────────────────────────────────────
C_NAVY       = colors.HexColor('#185FA5')
C_TEAL       = colors.HexColor('#1D9E75')
C_TEAL_LIGHT = colors.HexColor('#E1F5EE')
C_BLUE_LIGHT = colors.HexColor('#EDF4FC')
C_AMBER_LIGHT= colors.HexColor('#FAEEDA')
C_BORDER     = colors.HexColor('#E5E5E0')
C_GRAY       = colors.HexColor('#888888')
C_DARK       = colors.HexColor('#1A1A1A')
C_WHITE      = colors.white
C_ROW_ALT    = colors.HexColor('#F5F9FF')


# ── Style factory ─────────────────────────────────────────────────────────────
def _S():
    return {
        'logo': ParagraphStyle(
            'Logo', fontName='Helvetica-Bold', fontSize=20,
            textColor=C_WHITE, leading=24),
        'hdr_right': ParagraphStyle(
            'HdrR', fontName='Helvetica', fontSize=9,
            textColor=C_WHITE, leading=14, alignment=TA_RIGHT),
        'title': ParagraphStyle(
            'Title', fontName='Helvetica-Bold', fontSize=20,
            textColor=C_DARK, leading=26, spaceAfter=2),
        'subtitle': ParagraphStyle(
            'Sub', fontName='Helvetica', fontSize=12,
            textColor=C_GRAY, leading=17, spaceAfter=0),
        'section': ParagraphStyle(
            'Sec', fontName='Helvetica-Bold', fontSize=9,
            textColor=C_NAVY, leading=13, spaceBefore=10, spaceAfter=4,
            textTransform='uppercase'),
        'lbl': ParagraphStyle(
            'Lbl', fontName='Helvetica', fontSize=8,
            textColor=C_GRAY, leading=12),
        'val': ParagraphStyle(
            'Val', fontName='Helvetica-Bold', fontSize=11,
            textColor=C_DARK, leading=14),
        'price': ParagraphStyle(
            'Price', fontName='Helvetica-Bold', fontSize=24,
            textColor=C_TEAL, leading=30),
        'price_lbl': ParagraphStyle(
            'PL', fontName='Helvetica-Bold', fontSize=8,
            textColor=C_WHITE, leading=12),
        'range': ParagraphStyle(
            'Range', fontName='Helvetica-Bold', fontSize=13,
            textColor=C_NAVY, leading=18),
        'src': ParagraphStyle(
            'Src', fontName='Helvetica-Bold', fontSize=9,
            textColor=C_NAVY, leading=13),
        'th': ParagraphStyle(
            'TH', fontName='Helvetica-Bold', fontSize=8,
            textColor=C_WHITE, leading=11),
        'td': ParagraphStyle(
            'TD', fontName='Helvetica', fontSize=8,
            textColor=C_DARK, leading=11),
        'note': ParagraphStyle(
            'Note', fontName='Helvetica-Oblique', fontSize=8,
            textColor=C_GRAY, leading=11),
        'footer': ParagraphStyle(
            'Foot', fontName='Helvetica', fontSize=8,
            textColor=C_GRAY, leading=11, alignment=TA_CENTER),
        'footer_r': ParagraphStyle(
            'FootR', fontName='Helvetica', fontSize=8,
            textColor=C_GRAY, leading=11, alignment=TA_RIGHT),
        'warn': ParagraphStyle(
            'Warn', fontName='Helvetica-Oblique', fontSize=10,
            textColor=colors.HexColor('#C07A10'), leading=15),
    }


def _euro(n) -> str:
    if n is None:
        return '—'
    return '€ ' + f'{int(n):,}'.replace(',', '.')


def genera_report(
    indirizzo: str,
    tipo: str,
    mq: Optional[int],
    zona: str,
    omi: Optional[dict],
    comparabili: list,
) -> bytes:
    """
    Genera il PDF di valutazione e restituisce i bytes.

    Parametri:
        indirizzo   — indirizzo completo dell'immobile
        tipo        — tipo (Appartamento, Villa, ...)
        mq          — superficie in m²
        zona        — zona HouseRadar (macro-zona, es. "Livorno Città")
        omi         — dict {min, max, anno, semestre, comune} da get_omi_zone_map()
        comparabili — lista di dict annunci comparabili dal DB (max 5)
    """
    buf = io.BytesIO()
    W = A4[0] - 3.6 * cm  # larghezza utile

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=1.8 * cm, leftMargin=1.8 * cm,
        topMargin=1.5 * cm, bottomMargin=2.0 * cm,
        title=f'Valutazione — {indirizzo}',
        author='HouseRadar',
    )

    S = _S()
    story = []
    oggi = datetime.now().strftime('%d/%m/%Y %H:%M')

    # ── HEADER BAND ───────────────────────────────────────────────────────────
    hdr = Table(
        [[
            Paragraph('HouseRadar', S['logo']),
            Paragraph(
                f'Valutazione Immobiliare<br/>'
                f'<font color="#5DCAA5">Generata il {oggi}</font>',
                S['hdr_right'],
            ),
        ]],
        colWidths=[W * 0.5, W * 0.5],
    )
    hdr.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), C_NAVY),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LEFTPADDING',   (0, 0), (0, -1),  14),
        ('RIGHTPADDING',  (-1, 0), (-1, -1), 14),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story += [hdr, Spacer(1, 0.5 * cm)]

    # ── TITOLO ────────────────────────────────────────────────────────────────
    story.append(Paragraph(indirizzo or '—', S['title']))
    story.append(Paragraph(f'{tipo or "Immobile"}  ·  {zona or "—"}', S['subtitle']))
    story.append(Spacer(1, 0.25 * cm))
    story.append(HRFlowable(width=W, thickness=2, color=C_TEAL, spaceAfter=8))

    # ── DATI IMMOBILE ─────────────────────────────────────────────────────────
    story.append(Paragraph('Dati Immobile', S['section']))
    prop = Table(
        [
            [Paragraph('Indirizzo', S['lbl']),
             Paragraph('Tipo immobile', S['lbl']),
             Paragraph('Superficie', S['lbl']),
             Paragraph('Zona', S['lbl'])],
            [Paragraph(indirizzo or '—', S['val']),
             Paragraph(tipo or '—', S['val']),
             Paragraph(f'{mq} m²' if mq else '—', S['val']),
             Paragraph(zona or '—', S['val'])],
        ],
        colWidths=[W * 0.35, W * 0.20, W * 0.15, W * 0.30],
    )
    prop.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), C_TEAL_LIGHT),
        ('BACKGROUND',    (0, 1), (-1, 1), C_WHITE),
        ('BOX',           (0, 0), (-1, -1), 0.5, C_BORDER),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, C_BORDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    story += [prop, Spacer(1, 0.4 * cm)]

    # ── STIMA VALORE ─────────────────────────────────────────────────────────
    story.append(Paragraph('Stima Valore di Mercato', S['section']))

    if omi and mq:
        fattore  = 1.2 if tipo in ('Villa', 'Rustico') else 1.0
        ppm_min  = round(omi['min'] * fattore)
        ppm_max  = round(omi['max'] * fattore)
        vmin     = ppm_min * mq
        vmax     = ppm_max * mq
        anno_tag = f"OMI {omi.get('anno', 2024)} S{omi.get('semestre', 2)}"
        range_s  = f"{_euro(ppm_min)}–{_euro(ppm_max)}/m²"

        val_tbl = Table(
            [
                [Paragraph('VALORE MINIMO', S['price_lbl']),
                 Paragraph('VALORE MASSIMO', S['price_lbl']),
                 Paragraph('RANGE €/m²', S['price_lbl']),
                 Paragraph('FONTE DATI', S['price_lbl'])],
                [Paragraph(_euro(vmin), S['price']),
                 Paragraph(_euro(vmax), S['price']),
                 Paragraph(range_s, S['range']),
                 Paragraph(
                     f'<b>{anno_tag}</b><br/>'
                     f'<font size="8" color="#888888">Agenzia delle Entrate<br/>'
                     f'Comune: {omi.get("comune", zona)}</font>',
                     S['src'],
                 )],
            ],
            colWidths=[W * 0.26, W * 0.26, W * 0.22, W * 0.26],
        )
        val_tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0), C_TEAL),
            ('BACKGROUND',    (0, 1), (-1, 1), C_TEAL_LIGHT),
            ('BOX',           (0, 0), (-1, -1), 1.5, C_TEAL),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, C_WHITE),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 10),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(val_tbl)
        story.append(Spacer(1, 0.2 * cm))

        nota_parts = [
            f'Stima calcolata su {anno_tag} — Quotazioni Immobiliari OMI, Agenzia delle Entrate.',
        ]
        if fattore > 1.0:
            nota_parts.append(
                'Coefficiente 1.2 applicato per Villa/Rustico rispetto alle Abitazioni civili.'
            )
        nota_parts.append('I valori rappresentano il range di mercato per immobili in stato normale.')
        story.append(Paragraph(' '.join(nota_parts), S['note']))
    else:
        msg = ('Dati OMI non disponibili per questa zona.'
               if not omi else
               'Superficie non specificata — impossibile calcolare il valore totale.')
        story.append(Paragraph(msg, S['warn']))

    story.append(Spacer(1, 0.4 * cm))

    # ── COMPARABILI ───────────────────────────────────────────────────────────
    story.append(Paragraph('Immobili Comparabili nel Database', S['section']))

    if comparabili:
        fonte_label = {
            'privato': 'Privato',
            'noescl':  'Non escl.',
            'agenzia': 'Agenzia',
        }
        header_row = [
            Paragraph(t, S['th']) for t in
            ['Indirizzo', 'Tipo', 'Sup.', 'Prezzo', '€/m²', 'gg online', 'Fonte']
        ]
        rows = [header_row]
        for c in comparabili[:5]:
            ppm_c = (round(c['prezzo'] / c['mq'])
                     if c.get('prezzo') and c.get('mq') else None)
            rows.append([
                Paragraph((c.get('indirizzo') or '—')[:42], S['td']),
                Paragraph(c.get('tipo') or '—', S['td']),
                Paragraph(f"{c['mq']} m²" if c.get('mq') else '—', S['td']),
                Paragraph(_euro(c.get('prezzo')), S['td']),
                Paragraph(_euro(ppm_c), S['td']),
                Paragraph(str(c.get('giorni_online', '—')), S['td']),
                Paragraph(fonte_label.get(c.get('fonte', ''), '—'), S['td']),
            ])

        comp = Table(
            rows,
            colWidths=[W * 0.28, W * 0.11, W * 0.08,
                       W * 0.14, W * 0.11, W * 0.10, W * 0.18],
        )
        comp_style = [
            ('BACKGROUND',    (0, 0), (-1, 0), C_NAVY),
            ('BOX',           (0, 0), (-1, -1), 0.5, C_BORDER),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, C_BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ]
        for i in range(1, len(rows)):
            bg = C_ROW_ALT if i % 2 == 0 else C_WHITE
            comp_style.append(('BACKGROUND', (0, i), (-1, i), bg))
        comp.setStyle(TableStyle(comp_style))
        story.append(comp)
    else:
        story.append(Paragraph(
            'Nessun immobile comparabile trovato nel database per questa zona e tipologia.',
            S['note'],
        ))

    # ── FOOTER ────────────────────────────────────────────────────────────────
    story += [Spacer(1, 0.5 * cm),
              HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=6)]

    foot = Table(
        [[
            Paragraph(
                'Fonte dati: <b>Agenzia delle Entrate — OMI 2024 S2</b><br/>'
                'Le stime OMI sono indicatori statistici di mercato, non perizie ufficiali.',
                S['footer'],
            ),
            Paragraph(
                f'Generato da <b>HouseRadar</b> · houseradar.it<br/>{oggi}',
                S['footer_r'],
            ),
        ]],
        colWidths=[W * 0.60, W * 0.40],
    )
    foot.setStyle(TableStyle([
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(foot)

    doc.build(story)
    buf.seek(0)
    return buf.read()
