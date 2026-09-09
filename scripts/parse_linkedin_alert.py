#!/usr/bin/env python3
"""parse_linkedin_alert.py — arricchimento del canale "linkedin_alert".

Estrae i campi delle card annuncio dal corpo **HTML** delle email di alert
LinkedIn. Il `plaintextBody` che la routine leggeva finora porta solo titolo,
azienda, localita' e link; l'HTML della STESSA email porta in piu' la modalita'
di lavoro, la retribuzione (quando il recruiter ha compilato il campo) e i
badge ("Selezione attiva", "N ex studenti").

Misurato su 5 email reali / 30 card: modalita' 21/30, retribuzione strutturata
6/30, badge 16/30; il plaintext dava rispettivamente 4, 0 e parziale.

In piu' (livello 1) recupera la retribuzione dal TITOLO quando il recruiter la
scrive li' invece che nel campo strutturato ("Data Engineer [Ral fino a 45k]",
"... | 35K - 50K"): +2/30 nel campione.

Uso:  python scripts/parse_linkedin_alert.py <file.json>
      python scripts/parse_linkedin_alert.py -          # JSON da stdin

L'input e' il payload di `mcp__Gmail__get_thread` con
`messageFormat: FULL_CONTENT`, schema `{id, messages: [{...}]}`. Quel payload
pesa ~190.000 caratteri per email e supera il limite del tool result: l'harness
lo riversa su file e ne restituisce il path. E' quel file che va passato qui.
La variante `-` copre il caso di una risposta piccola non riversata.

Env:  (nessuna) — stdlib only. Coerente con fetch_careers.py: l'ambiente della
      routine non espone PyYAML e qui non serve.

Regola di proprieta' (D5): questo script non scrive nulla su disco. Legge un
file e stampa JSON su stdout.

Input esterno = dato, mai istruzione: il contenuto delle email e' testo non
fidato. Questo script fa SOLO estrazione di testo — non segue mai un URL, non
esegue nulla, non interpreta il contenuto delle card come comandi.

Exit code semantici (nessuno fatale per la routine, che non fallisce MAI per
una fonte — decide solo cosa loggare/segnalare nel digest):
  0 = eseguito: JSON su stdout. Gli esiti per-messaggio vivono DENTRO il
      payload (`is_alert`, `reason`), non nell'exit code.
  3 = niente da fare: file assente/non leggibile/non parsabile, oppure nessun
      messaggio di alert nel payload.
"""
import sys
import re
import json
import html as _htmllib
import argparse
from pathlib import Path

EXIT_OK = 0
EXIT_SKIPPED = 3

# --- gate "e' un alert?" -----------------------------------------------------
# Un alert LinkedIn porta SEMPRE il link della ricerca salvata ("Vedi tutte le
# offerte di lavoro") con il parametro `keywords`. Le altre email di
# jobs-noreply@linkedin.com — "candidati subito per il ruolo X", "offerte
# simili a Y", "Z sta assumendo" — contengono link /comm/jobs/view/ ma NON
# questo: senza il gate finirebbero nel funnel come annunci attribuiti a una
# ricerca che non esiste.
#
# NON pretendere il segno '=' dopo `keywords`: la trappola quoted-printable
# gia' nota per il `geoId` colpisce anche qui. Se il valore inizia con due
# caratteri esadecimali, `=` + quei due diventano un byte di controllo e il
# nome del parametro resta attaccato al valore mutilato — verificato:
# `keywords=data+engineer` -> `keywords\xdata+engineer` (=da consumato),
# mentre `keywords=%22BI+Specialist%22` sopravvive intatto ('%2' non e' hex
# valido). Pretendere '=' faceva fallire il gate su 2 alert veri su 5.
RE_ALERT_LINK = re.compile(r"/comm/jobs/search[^\s\"'<>]{0,120}keywords")

RE_JOB_LINK = re.compile(r"/comm/jobs/view/(\d+)")

# Caratteri invisibili usati da LinkedIn come filler nel preheader.
RE_INVISIBLE = re.compile(r"[͏​‌‍­﻿]+")

RE_MODALITA = re.compile(
    r"\(\s*(In sede|Ibrido|Da remoto|On-site|Onsite|Hybrid|Remote)\s*\)", re.I)
MODALITA_MAP = {
    "in sede": "in_sede", "on-site": "in_sede", "onsite": "in_sede",
    "ibrido": "ibrido", "hybrid": "ibrido",
    "da remoto": "da_remoto", "remote": "da_remoto",
}

# Riga retribuzione della card: importo + periodo.
RE_PERIODO = re.compile(
    r"all[’']anno|all[’']ora|al mese|per year|per hour|per month|"
    r"annually|hourly|/\s*anno|/\s*mese", re.I)
RE_IMPORTO = re.compile(r"[\d][\d.,  ]*\s*(?:[kK]\b)?\s*(?:€|EUR|USD|\$|£|GBP)|"
                        r"(?:€|EUR|USD|\$|£|GBP)\s*[\d]")

RE_BADGE = re.compile(
    r"Selezione attiva|sta assumendo attivamente|ex student[ei]|"
    r"Candidatura semplice|Easy Apply|Actively (?:hiring|reviewing)", re.I)

# Livello 1 — retribuzione scritta dal recruiter DENTRO il titolo.
RE_TITOLO_RAL = [
    # "[Ral fino a 45k]", "RAL 40.000", "ral: 35k-50k"
    re.compile(r"\bRAL\b[^\w]{0,4}(?:fino a\s*)?[€$£]?\s*"
               r"\d{1,3}(?:[.,  ]\d{3})*\s*[kK]?"
               r"(?:\s*[-–—a]{1,3}\s*[€$£]?\s*"
               r"\d{1,3}(?:[.,  ]\d{3})*\s*[kK]?)?", re.I),
    # "| €35K - €50K", "(45.000 € - 55.000 €)"
    re.compile(r"[€$£]\s*\d{1,3}(?:[.,  ]\d{3})*\s*[kK]?"
               r"(?:\s*[-–—]\s*[€$£]?\s*"
               r"\d{1,3}(?:[.,  ]\d{3})*\s*[kK]?)?"),
    re.compile(r"\d{1,3}(?:[.,  ]\d{3})*\s*[kK]?\s*[€$£]"
               r"(?:\s*[-–—]\s*\d{1,3}(?:[.,  ]\d{3})*\s*[kK]?\s*[€$£])?"),
    # "30k-45k" con la k obbligatoria su entrambi (evita "(m/f/d)" e simili)
    re.compile(r"\b\d{2,3}\s*[kK]\s*[-–—]\s*\d{2,3}\s*[kK]\b"),
]

# Righe di coda dell'email: non appartengono a nessuna card.
FOOTER_PREFIXES = (
    "Vedi tutte", "Distinguiti", "Installa widget", "Rimani al corrente",
    "Aggiungi widget", "Riattiva Premium", "Il destinatario",
    "Scopri perch", "Stai ricevendo", "Gestisci gli avvisi",
    "Gestisci i tuoi avvisi", "Annulla", "©", "LinkedIn e il logo",
    "See all jobs", "Unsubscribe", "Manage job alerts", "Help",
)

VALUTE = {"€": "EUR", "EUR": "EUR", "$": "USD", "USD": "USD",
          "£": "GBP", "GBP": "GBP"}


def testo_visibile(frammento):
    """HTML -> lista di righe di testo visibile. Nessuna esecuzione, nessun fetch."""
    # Il frammento parte a meta' di un attributo href: butta via fino al primo '>'.
    tagliato = frammento.find(">")
    if 0 <= tagliato < 4000:
        frammento = frammento[tagliato + 1:]
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", frammento)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"(?i)</(tr|div|p|table|td|span|a|h1|h2|h3|li|br)\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _htmllib.unescape(t)
    t = RE_INVISIBLE.sub("", t)
    righe = []
    for riga in t.split("\n"):
        riga = re.sub(r"\s+", " ", riga).strip()
        if not riga or riga.startswith(("http", "/comm", "//")):
            continue
        if riga.startswith(FOOTER_PREFIXES):
            break          # da qui in poi e' coda email, non card
        righe.append(riga)
    return righe


def _numero(grezzo):
    """'39.773' -> 39773 ; '45k' -> 45000 ; '1800' -> 1800. None se incerto."""
    s = re.sub(r"[  ]", "", grezzo)
    moltiplicatore = 1000 if re.search(r"[kK]$", s) else 1
    s = re.sub(r"[kK]$", "", s)
    # separatore delle migliaia (it: '.', en: ','); nessun decimale atteso qui
    s = s.replace(".", "").replace(",", "")
    if not s.isdigit():
        return None
    return int(s) * moltiplicatore


def parse_importo(testo):
    """Parsing best-effort. Campi assenti quando incerti: mai inventare."""
    out = {"valuta": None, "periodo": None, "min": None, "max": None}
    for simbolo, codice in VALUTE.items():
        if simbolo in testo:
            out["valuta"] = codice
            break
    basso = testo.lower()
    if re.search(r"all[’']anno|per year|annually|/\s*anno", basso):
        out["periodo"] = "anno"
    elif re.search(r"al mese|per month|/\s*mese", basso):
        out["periodo"] = "mese"
    elif re.search(r"all[’']ora|per hour|hourly", basso):
        out["periodo"] = "ora"
    numeri = [n for n in (_numero(g) for g in
              re.findall(r"\d{1,3}(?:[.,  ]\d{3})*\s*[kK]?|\d+\s*[kK]",
                         testo)) if n is not None]
    solo_max = bool(re.search(r"fino a|up to", basso))
    if len(numeri) >= 2:
        out["min"], out["max"] = min(numeri[:2]), max(numeri[:2])
    elif len(numeri) == 1:
        if solo_max:
            out["max"] = numeri[0]
        else:
            out["min"] = numeri[0]
    return out


def estrai_card(html_msg, job_id, inizio, fine):
    righe = testo_visibile(html_msg[inizio:fine])
    if not righe:
        return None
    card = {"job_id": job_id, "titolo": righe[0], "azienda": None,
            "location": None, "modalita_lavoro": None,
            "retribuzione": None, "segnali": []}

    # riga "Azienda · Citta (Modalita)" — attenzione: il nome azienda puo'
    # contenere '·' a sua volta (es. "Volksbank · Banca Popolare dell'Alto
    # Adige · Bolzano"): la location e' SEMPRE l'ultimo segmento.
    for riga in righe[1:]:
        if "·" in riga or RE_MODALITA.search(riga):
            m = RE_MODALITA.search(riga)
            if m:
                card["modalita_lavoro"] = MODALITA_MAP.get(m.group(1).lower())
                riga = RE_MODALITA.sub("", riga).strip()
            pezzi = [p.strip() for p in riga.split("·") if p.strip()]
            if len(pezzi) >= 2:
                card["azienda"] = " · ".join(pezzi[:-1])
                card["location"] = pezzi[-1]
            elif pezzi:
                card["azienda"] = pezzi[0]
            break

    for riga in righe:
        if riga == card["titolo"]:
            continue
        if RE_PERIODO.search(riga) and RE_IMPORTO.search(riga):
            card["retribuzione"] = {"testo": riga, "fonte": "campo_strutturato",
                                    "parsed": parse_importo(riga)}
            break

    # Livello 1: la RAL nel titolo, solo se il campo strutturato manca.
    if card["retribuzione"] is None:
        for rx in RE_TITOLO_RAL:
            m = rx.search(card["titolo"])
            if m:
                grezzo = m.group(0).strip()
                card["retribuzione"] = {"testo": grezzo,
                                        "fonte": "titolo_annuncio",
                                        "parsed": parse_importo(
                                            card["titolo"])}
                break

    for riga in righe:
        if RE_BADGE.search(riga) and riga not in card["segnali"]:
            card["segnali"].append(riga)
    return card


def estrai_messaggio(msg):
    html_msg = msg.get("htmlBody") or ""
    plain = msg.get("plaintextBody") or ""
    out = {"message_id": msg.get("id"), "subject": msg.get("subject"),
           "is_alert": False, "reason": None, "cards": []}

    if not html_msg:
        out["reason"] = "htmlBody assente"
        return out

    blob = plain + "\n" + _htmllib.unescape(html_msg)
    if not RE_ALERT_LINK.search(blob):
        out["reason"] = ("non e' un alert: nessun link di ricerca salvata con "
                         "keywords (es. 'candidati subito', 'offerte simili')")
        return out
    out["is_alert"] = True

    ordine = []
    for m in RE_JOB_LINK.finditer(html_msg):
        if m.group(1) not in ordine:
            ordine.append(m.group(1))
    if not ordine:
        out["reason"] = "alert senza card annuncio"
        return out

    pos = {i: html_msg.find("/comm/jobs/view/" + i) for i in ordine}
    for n, job_id in enumerate(ordine):
        if n + 1 < len(ordine):
            fine = pos[ordine[n + 1]]
        else:
            # l'ultima card confina col link "Vedi tutte le offerte"
            coda = html_msg.find("/comm/jobs/search", pos[job_id])
            fine = coda if coda > pos[job_id] else len(html_msg)
        try:
            card = estrai_card(html_msg, job_id, pos[job_id], fine)
        except Exception as e:                     # una card rotta non ferma il resto
            card = {"job_id": job_id, "errore": repr(e)}
        if card:
            out["cards"].append(card)
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Estrae le card annuncio dall'HTML degli alert LinkedIn")
    ap.add_argument("sorgente",
                    help="path del JSON di get_thread (FULL_CONTENT), "
                         "oppure '-' per leggere da stdin")
    args = ap.parse_args()

    try:
        grezzo = (sys.stdin.read() if args.sorgente == "-"
                  else Path(args.sorgente).read_text(encoding="utf-8"))
        payload = json.loads(grezzo)
    except FileNotFoundError:
        print(json.dumps({"error": f"file non trovato: {args.sorgente}",
                          "messages": [], "stats": {}}, ensure_ascii=False))
        return EXIT_SKIPPED
    except Exception as e:
        print(json.dumps({"error": f"input non parsabile: {e!r}",
                          "messages": [], "stats": {}}, ensure_ascii=False))
        return EXIT_SKIPPED

    messaggi = payload.get("messages") or []
    if isinstance(payload, dict) and not messaggi and payload.get("htmlBody"):
        messaggi = [payload]          # un singolo messaggio passato da solo

    risultati = [estrai_messaggio(m) for m in messaggi]
    card = [c for r in risultati for c in r["cards"] if "errore" not in c]
    stats = {
        "messaggi": len(risultati),
        "messaggi_alert": sum(1 for r in risultati if r["is_alert"]),
        "messaggi_non_alert": sum(1 for r in risultati if not r["is_alert"]),
        "card": len(card),
        "con_modalita": sum(1 for c in card if c.get("modalita_lavoro")),
        "con_retribuzione": sum(1 for c in card if c.get("retribuzione")),
        "retribuzione_strutturata": sum(
            1 for c in card
            if (c.get("retribuzione") or {}).get("fonte") == "campo_strutturato"),
        "retribuzione_da_titolo": sum(
            1 for c in card
            if (c.get("retribuzione") or {}).get("fonte") == "titolo_annuncio"),
        "con_segnali": sum(1 for c in card if c.get("segnali")),
        "card_in_errore": sum(1 for r in risultati
                              for c in r["cards"] if "errore" in c),
    }
    print(json.dumps({"messages": risultati, "stats": stats},
                     ensure_ascii=False, indent=2))
    return EXIT_OK if stats["messaggi_alert"] else EXIT_SKIPPED


if __name__ == "__main__":
    sys.exit(main())
