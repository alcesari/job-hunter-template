#!/usr/bin/env python3
"""verify_cv_facts.py — gate deterministico anti-invenzione sui materiali generati.

Confronta i **claim numerici** di un materiale generato (CV, cover letter, DM)
con `master-profile.yaml` e segnala quelli che non sono tracciabili al profilo.

Perche' esiste (il punto che giustifica lo script): il presidio gia' presente e'
il *diff-report master↔generato*, che pero' e' prodotto **dallo stesso modello,
nella stessa sessione, che ha appena scritto il CV** — un'autocertificazione, che
fallisce proprio nel caso che deve coprire (se il modello ha allucinato una
metrica non "sa" di averlo fatto, e la classifichera' come riformulazione). Questo
script non ha contesto, non ha scritto il documento e non puo' essere convinto:
e' l'unico controllo del sistema indipendente dal modello.

Uso:
  python3 scripts/verify_cv_facts.py <file-generato> [--profile master-profile.yaml]
                                     [--config cv-facts.yaml] [--format text|json]

Formati di input accettati: .md, .txt, .html, .tex (i tag HTML/LaTeX e i blocchi
<style>/<script> vengono rimossi prima dell'estrazione — senza questo, i numeri
del markup, es. `<div class="col-12">`, sarebbero falsi positivi).

Exit code semantici (stessa disciplina di fetch_careers.py / send_digest.py):
  0 = nessun claim non tracciabile (gate VERDE)
  5 = trovati claim non tracciabili o frasi vietate (gate ROSSO)
  3 = saltato: file generato o profilo assenti/illeggibili — NON fatale

LIMITE DICHIARATO (leggilo prima di fidarti del verde): il match e' volutamente
permissivo — un valore e' "tracciabile" se il numero normalizzato compare
**ovunque** nel profilo, non necessariamente nel contesto giusto. Quindi lo
script intercetta le **grandezze inventate** ("ho ridotto i costi del 40%" quando
nel profilo non c'e' nessun 40), non le **attribuzioni sbagliate** (un numero
reale del profilo spostato su un'esperienza a cui non appartiene). E' un gate
contro l'allucinazione, non un fact-checker semantico: il diff-report (passo 7b
di cv-tailoring) resta necessario e non e' sostituito da questo script.
La permissivita' e' deliberata: un falso positivo blocca la consegna e fa perdere
tempo, quindi si preferisce sbagliare verso il silenzio sui casi ambigui.
"""
import sys
import re
import json
import argparse
import unicodedata
from pathlib import Path

EXIT_OK = 0
EXIT_SKIPPED = 3
EXIT_VIOLATION = 5

# ---------------------------------------------------------------------------
# Classi di claim estratte (contratto §1.2a della specifica)
# ---------------------------------------------------------------------------
# Ogni pattern cattura in gruppo 1 la parte NUMERICA da normalizzare; il match
# completo e' cio' che viene mostrato all'utente come "claim".
CLAIM_PATTERNS = [
    ("percentuale", re.compile(r"(\d+(?:[.,]\d+)?)\s*%")),
    ("importo", re.compile(
        r"(?:[€$£]\s*(\d[\d.,]*)\s*(?:k|K|mln|M|mila)?"
        r"|(\d[\d.,]*)\s*(?:k|K|mln|M|mila)?\s*(?:€|\$|£|EUR|euro))", re.I)),
    ("durata", re.compile(
        r"(\d+)\s*\+?\s*(?:anni|anno|mesi|mese|years?|months?)\b", re.I)),
    ("grandezza", re.compile(
        r"(\d[\d.,]*)\s*(?:persone|utenti|clienti|users|customers|"
        r"sviluppatori|developers|membri|dipendenti|transazioni|records?|righe)\b", re.I)),
    ("moltiplicatore", re.compile(r"(\d+(?:[.,]\d+)?)\s*x\b", re.I)),
]

# Token che, se il claim e' interamente dentro un contesto di questo tipo, non
# sono metriche di merito ma riferimenti tecnici/temporali: si ignorano per non
# generare rumore (es. "OAuth2", "Log4j2", "v6.1", "Java 17").
NOISE_CONTEXT = re.compile(
    r"\b(?:v\d|version|versione|java|python|node|php|http|oauth|log4j|sql|"
    r"spring|angular|react|vue|jdk|jre|api|utf|iso|rfc)\b", re.I)


def strip_markup(text, suffix):
    """Rimuove markup che porterebbe numeri spuri (classi CSS, misure, macro)."""
    if suffix in (".html", ".htm", ".xhtml"):
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", text,
                      flags=re.S | re.I)
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
    elif suffix == ".tex":
        text = re.sub(r"%.*", " ", text)                       # commenti LaTeX
        text = re.sub(r"\\usepackage(\[[^\]]*\])?\{[^}]*\}", " ", text)
        text = re.sub(r"\\(?:documentclass|geometry|setlength|vspace|hspace|"
                      r"fontsize|includegraphics)(\[[^\]]*\])?(\{[^}]*\})*",
                      " ", text)
        text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)           # altre macro
    # Markdown: le sole strutture che portano numeri non-semantici sono i link
    # e le immagini; il testo visibile si tiene.
    text = re.sub(r"\]\([^)]*\)", "] ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return text


def normalize_number(raw):
    """'1.234' → '1234' · '10k' → '10000' · '2,5' → '2.5'. Ritorna un set di
    forme plausibili: il profilo puo' scrivere lo stesso valore diversamente."""
    s = raw.strip().lower().replace(" ", "")
    forms = {s}

    # Separatori: in IT il punto e' migliaia, la virgola e' decimale.
    if "," in s and "." in s:
        cleaned = s.replace(".", "").replace(",", ".")
    elif "," in s:
        cleaned = s.replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        cleaned = s.replace(".", "")       # 1.234 = migliaia
    else:
        cleaned = s
    forms.add(cleaned)

    try:
        val = float(cleaned)
    except ValueError:
        return {f for f in forms if f}

    if val.is_integer():
        n = int(val)
        forms.add(str(n))
        forms.add(f"{n:,}".replace(",", "."))   # 35000 → 35.000
        forms.add(f"{n:,}")                     # 35000 → 35,000
        if n >= 1000 and n % 1000 == 0:
            forms.add(f"{n // 1000}k")          # 35000 → 35k
    else:
        forms.add(str(val))
        forms.add(str(val).replace(".", ","))
    return {f for f in forms if f}


def flatten_profile(text):
    """Testo del profilo appiattito e normalizzato per la ricerca."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()


# Token del PROFILO che contengono cifre ma non sono mai la fonte legittima di
# una metrica in un CV: date, voti, versioni, recapiti. Vanno tolti prima di
# costruire l'indice, altrimenti "coprono" claim inventati per pura collisione
# — es. `2026-12` (scadenza di una certificazione) renderebbe "tracciabile" un
# claim "12x" mai visto prima. Verificato su un caso reale in fase di taratura.
PROFILE_NOISE = re.compile(
    r"\d{4}-\d{2}(?:-\d{2})?"          # date ISO: 2026-12, 2022-10-01
    r"|\b\d{1,3}\s*/\s*\d{1,3}\b"      # voti: 86/110
    r"|\bv?\d+\.\d+(?:\.\d+)?\b"       # versioni: v6.1, 2.5.7
    r"|\+?\d[\d\s().-]{7,}\d",         # numeri di telefono
    re.I)


def profile_number_forms(flat):
    """Tutte le forme numeriche presenti nel profilo, gia' normalizzate.

    Serve a riconoscere che '35.000' nel profilo copre '35000' nel generato:
    si confrontano insiemi di forme, non stringhe grezze.

    I token rumorosi (date/voti/versioni/telefoni) sono rimossi prima: la loro
    presenza rendeva "tracciabili" claim inventati per collisione accidentale."""
    cleaned = PROFILE_NOISE.sub(" ", flat)
    forms = set()
    for tok in re.findall(r"\d[\d.,]*", cleaned):
        forms |= normalize_number(tok)
    return forms


# ---------------------------------------------------------------------------
# Loader YAML minimale per cv-facts.yaml (stessa scelta di fetch_careers.py:
# PyYAML non e' disponibile nell'ambiente della routine).
# Struttura attesa:
#   allow_metrics:
#     - valore: "4 anni"
#       motivo: "..."
#   forbidden_phrases:
#     - "Fortune 500"
# ---------------------------------------------------------------------------
def load_cv_facts(path):
    allow, forbidden = [], []
    if not path or not Path(path).exists():
        return allow, forbidden
    section = None
    current = None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].rstrip() if not raw.strip().startswith("#") else ""
        if not line.strip():
            continue
        if re.match(r"^allow_metrics\s*:", line):
            section, current = "allow", None
            continue
        if re.match(r"^forbidden_phrases\s*:", line):
            section, current = "forbidden", None
            continue
        if re.match(r"^[a-zA-Z_]+\s*:", line):       # altra chiave di root
            section, current = None, None
            continue
        stripped = line.strip()
        if section == "forbidden" and stripped.startswith("- "):
            forbidden.append(_unquote(stripped[2:].strip()))
        elif section == "allow":
            if stripped.startswith("- "):
                current = {}
                allow.append(current)
                stripped = stripped[2:].strip()
            if current is not None and ":" in stripped:
                k, v = stripped.split(":", 1)
                current[k.strip()] = _unquote(v.strip())
    return [a for a in allow if a.get("valore")], [f for f in forbidden if f]


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


# ---------------------------------------------------------------------------
def forbidden_hit(phrase, lower_text):
    """Match di una frase vietata, tollerante alla flessione italiana.

    Una lista letterale mancherebbe `pluripremiata` avendo scritto
    `pluripremiato` (verificato in taratura). Per le frasi di UNA sola parola
    che finiscono in vocale si accetta qualunque desinenza o/a/i/e; le frasi
    multi-parola restano letterali, perche' li' la flessione e' ambigua e il
    rischio di falso positivo cresce."""
    p = phrase.lower().strip()
    if not p:
        return False
    if " " not in p and p[-1] in "oaie":
        return re.search(r"\b" + re.escape(p[:-1]) + r"[oaie]\b", lower_text) is not None
    return p in lower_text


def extract_claims(text):
    """Estrae i claim numerici con un po' di contesto, deduplicati."""
    claims = []
    seen = set()
    for kind, pattern in CLAIM_PATTERNS:
        for m in pattern.finditer(text):
            number = next((g for g in m.groups() if g), None)
            if not number:
                continue
            start, end = m.span()
            context = text[max(0, start - 60):min(len(text), end + 60)]
            context = " ".join(context.split())
            if NOISE_CONTEXT.search(text[max(0, start - 25):end + 10]):
                continue
            key = (kind, m.group(0).strip().lower())
            if key in seen:
                continue
            seen.add(key)
            claims.append({
                "tipo": kind,
                "claim": " ".join(m.group(0).split()),
                "numero": number,
                "contesto": context,
            })
    return claims


def verify(target_path, profile_path, config_path):
    target = Path(target_path)
    profile = Path(profile_path)
    if not target.exists():
        return EXIT_SKIPPED, {"stato": "saltato",
                              "motivo": f"file generato non trovato: {target}"}
    if not profile.exists():
        return EXIT_SKIPPED, {"stato": "saltato",
                              "motivo": f"profilo non trovato: {profile}"}

    raw = target.read_text(encoding="utf-8", errors="replace")
    text = strip_markup(raw, target.suffix.lower())
    flat_profile = flatten_profile(profile.read_text(encoding="utf-8",
                                                     errors="replace"))
    prof_forms = profile_number_forms(flat_profile)

    allow_metrics, forbidden_phrases = load_cv_facts(config_path)
    allow_norm = {}
    for entry in allow_metrics:
        for form in normalize_number(
                re.sub(r"[^\d.,]", "", entry.get("valore", "")) or "\x00"):
            allow_norm[form] = entry
    allow_literal = {a.get("valore", "").strip().lower() for a in allow_metrics}

    risultati = []
    for claim in extract_claims(text):
        forms = normalize_number(claim["numero"])
        if forms & prof_forms:
            verdetto, nota = "tracciabile", "valore presente nel profilo"
        elif claim["claim"].strip().lower() in allow_literal or (forms & set(allow_norm)):
            entry = allow_norm.get(next(iter(forms & set(allow_norm)), ""), {})
            verdetto = "allowlisted"
            nota = entry.get("motivo", "in cv-facts.yaml")
        else:
            verdetto, nota = "NON TRACCIABILE", "assente dal profilo e da cv-facts.yaml"
        claim.update({"verdetto": verdetto, "nota": nota})
        risultati.append(claim)

    lower_text = text.lower()
    frasi = [{"frase": p, "verdetto": "VIETATA"}
             for p in forbidden_phrases if forbidden_hit(p, lower_text)]

    non_tracciabili = [r for r in risultati if r["verdetto"] == "NON TRACCIABILE"]
    esito = EXIT_VIOLATION if (non_tracciabili or frasi) else EXIT_OK
    return esito, {
        "stato": "rosso" if esito == EXIT_VIOLATION else "verde",
        "file": str(target),
        "claim_totali": len(risultati),
        "non_tracciabili": len(non_tracciabili),
        "frasi_vietate": len(frasi),
        "claim": risultati,
        "frasi": frasi,
    }


def render_text(report):
    if report.get("stato") == "saltato":
        return f"⏭  SALTATO — {report['motivo']}"
    lines = []
    icona = "🟢" if report["stato"] == "verde" else "🔴"
    lines.append(f"{icona} Gate veridicita': {report['stato'].upper()} — {report['file']}")
    lines.append(f"   claim numerici estratti: {report['claim_totali']} · "
                 f"non tracciabili: {report['non_tracciabili']} · "
                 f"frasi vietate: {report['frasi_vietate']}")
    for f in report["frasi"]:
        lines.append(f"   ⛔ frase vietata: «{f['frase']}»")
    for c in report["claim"]:
        if c["verdetto"] == "NON TRACCIABILE":
            lines.append(f"   ⛔ {c['claim']}  [{c['tipo']}] — {c['nota']}")
            lines.append(f"      contesto: …{c['contesto']}…")
    if report["stato"] == "rosso":
        lines.append("")
        lines.append("   Ogni claim segnalato va RIMOSSO, CORRETTO, oppure — se e'")
        lines.append("   legittimo — aggiunto a cv-facts.yaml con la motivazione,")
        lines.append("   DALL'UTENTE. Un agente che si autoassolve allargando")
        lines.append("   l'allowlist annulla il senso di questo gate.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Gate deterministico anti-invenzione sui materiali generati.")
    ap.add_argument("target", help="file generato da verificare (.md/.html/.tex/.txt)")
    ap.add_argument("--profile", default="master-profile.yaml")
    ap.add_argument("--config", default="cv-facts.yaml")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    code, report = verify(args.target, args.profile, args.config)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
