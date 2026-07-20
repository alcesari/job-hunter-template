#!/usr/bin/env python3
"""check_liveness.py — verifica se gli annunci in staging sono ancora aperti.

Perche' esiste: lo staging cresce in modo monotono. La retention (passo 9 di
`job-watch/SKILL.md`) non tocca MAI le voci `pending` — giustamente, sono lavoro
in attesa di un umano — quindi l'unica uscita e' una decisione umana. Se quella
decisione tarda, la coda si riempie di annunci ormai chiusi e l'unico modo per
accorgersene e' cliccare. Questo script accerta un FATTO (l'annuncio non esiste
piu'), non emette un GIUDIZIO: e' cio' che permette alla routine di marcare una
voce `expired` senza mai decidere al posto dell'utente (D3 intatta).

Uso:
  python3 scripts/check_liveness.py [--staging staging/] [--max N]
                                    [--status pending] [--format text|json]
                                    [--settings .claude/settings.json]

Output (JSON): [{"id", "verdetto", "motivo", "url", "fonte", "checked_at"}]
  verdetto ∈ {vivo, chiuso, indeterminato}

Exit code: SEMPRE 0. Come fetch_careers.py, questo script non fa mai fallire la
run: gli esiti per-voce vivono dentro il payload, non nell'exit code.

REGOLA DI PRUDENZA (non negoziabile, simmetrica alla conservativita' del matcher
di entity resolution): `chiuso` si assegna SOLO su evidenza positiva —
HTTP 404/410, redirect alla lista posizioni, marker testuale esplicito. Timeout,
403, 5xx, errore di rete, dominio non allowlistato, URL assente → SEMPRE
`indeterminato`, MAI `chiuso`. Un falso `chiuso` nasconde in silenzio
un'opportunita' reale; un falso `indeterminato` costa solo una voce in piu' da
guardare. L'asimmetria e' voluta e va preservata da chiunque tocchi questo file.

PERIMETRO (limite dichiarato, non un bug): sono verificabili solo le fonti con
URL fetchabile e dominio allowlistato — in pratica `career_page`. LinkedIn e'
dietro login (vincolo V5) e non e' fetchabile; Indeed va verificato dall'agente
via connettore (`get_job_details`), non da qui. Quelle voci escono
`indeterminato` con un motivo esplicito. La copertura e' PARZIALE per costruzione.

SOFT-404 (verificato in taratura, 2026-07-20): alcune career page rispondono
**200 anche su URL inesistenti** (catch-all SPA) — es. gogenerali.com. Per quei
domini il verdetto sara' `vivo` anche per un annuncio rimosso, a meno che la
pagina non esponga un marker testuale. E' un falso `vivo`, cioe' l'errore nella
direzione INNOCUA (la voce resta in coda invece di essere marcata `expired`).
Non "risolverlo" con euristiche aggressive tipo confronto di lunghezza del body:
il rischio sarebbe di iniziare a produrre falsi `chiuso`, che e' il danno che
questo script e' costruito per non fare mai.
"""
import sys
import re
import ssl
import json
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
TIMEOUT = 20
UA = "job-hunter-liveness/1.0 (+liveness check; contact via repo owner)"

# Marker testuali di chiusura. Devono essere SPECIFICI: un marker generico
# ("not found") su una pagina 200 produrrebbe falsi `chiuso`, che e' la
# direzione pericolosa. Nel dubbio, non aggiungerne.
CLOSED_MARKERS = [
    "no longer accepting applications",
    "no longer available",
    "this job is no longer",
    "this position is no longer",
    "position has been filled",
    "posting is closed",
    "job posting has expired",
    "vacancy is closed",
    "annuncio non e' piu' disponibile",
    "annuncio non piu' disponibile",
    "posizione non e' piu' disponibile",
    "posizione chiusa",
    "offerta scaduta",
    "selezione chiusa",
    "candidature chiuse",
]

# Path che, se raggiunti dopo un redirect, indicano "sei finito sulla lista
# generale, l'annuncio specifico non c'e' piu'".
LIST_PATH_HINTS = ("/jobs", "/careers", "/carriere", "/lavora-con-noi",
                   "/opportunities", "/positions", "/search", "/openings")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_marker(s):
    """Minuscolo + apostrofi/accenti normalizzati, per confronto tollerante."""
    s = s.lower()
    for a, b in (("’", "'"), ("è", "e'"), ("é", "e'"),
                 ("ù", "u'"), ("à", "a'"), ("ì", "i'"),
                 ("ò", "o'")):
        s = s.replace(a, b)
    return s


# ---------------------------------------------------------------------------
# Loader YAML minimale: serve solo a leggere pochi scalari e la lista sources[]
# di staging.yaml. Come in fetch_careers.py, PyYAML non e' disponibile
# nell'ambiente della routine.
# ---------------------------------------------------------------------------
def read_staging(path):
    """Estrae {id, status, run_id, sources:[{fonte,jd,apply_url}]} da staging.yaml."""
    text = path.read_text(encoding="utf-8", errors="replace")
    out = {"id": None, "status": None, "run_id": None, "sources": []}
    current = None
    in_sources = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()

        if indent == 0:
            in_sources = line.startswith("sources:")
            current = None
            m = re.match(r"^(id|status|run_id|source|annuncio_id)\s*:\s*(.*)$", line)
            if m and m.group(1) in ("id", "status", "run_id"):
                out[m.group(1)] = _unquote(m.group(2))
            continue

        if in_sources:
            if line.startswith("- "):
                current = {}
                out["sources"].append(current)
                line = line[2:].strip()
            if current is not None and ":" in line:
                k, v = line.split(":", 1)
                current[k.strip()] = _unquote(v.strip())
    # fallback: alcune voci mono-fonte hanno solo links.jd a livello root
    if not out["sources"]:
        m = re.search(r"^\s*jd\s*:\s*(\S+)", text, re.M)
        if m:
            out["sources"] = [{"fonte": _root_scalar(text, "source") or "?",
                               "jd": _unquote(m.group(1))}]
    return out


def _root_scalar(text, key):
    m = re.search(r"^%s\s*:\s*(.*)$" % re.escape(key), text, re.M)
    return _unquote(m.group(1)) if m else None


def _unquote(s):
    s = s.strip()
    if s.endswith("#") or " #" in s:
        s = s.split(" #")[0].strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def load_allowed_domains(settings_path):
    """Domini che la sandbox autorizza. Un dominio fuori da qui NON si contatta:
    il tentativo fallirebbe comunque (gate di rete V4) e produrrebbe un errore
    indistinguibile da un annuncio chiuso."""
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
        return set(data.get("sandbox", {}).get("network", {})
                   .get("allowedDomains", []) or [])
    except Exception:
        return set()


def host_allowed(url, allowed):
    if not allowed:
        return False
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except Exception:
        return False
    host = host.lower().lstrip(".")
    return any(host == d.lower() or host.endswith("." + d.lower())
               for d in allowed)


# ---------------------------------------------------------------------------
def probe(url):
    """Ritorna (verdetto, motivo). Vedi la regola di prudenza in testa al file."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            final = resp.geturl()
            body = resp.read(200_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return "chiuso", f"HTTP {e.code} sull'annuncio"
        # 403/429/5xx: non e' evidenza di chiusura, e' un ostacolo.
        return "indeterminato", f"HTTP {e.code} (non e' evidenza di chiusura)"
    except urllib.error.URLError as e:
        return "indeterminato", f"errore di rete: {getattr(e, 'reason', e)}"
    except Exception as e:                                   # noqa: BLE001
        return "indeterminato", f"errore imprevisto: {type(e).__name__}"

    # Redirect verso una pagina-lista: l'annuncio specifico non c'e' piu'.
    if _is_list_redirect(url, final):
        return "chiuso", f"redirect alla lista posizioni ({final})"

    lowered = normalize_marker(re.sub(r"<[^>]+>", " ", body))
    for marker in CLOSED_MARKERS:
        if normalize_marker(marker) in lowered:
            return "chiuso", f"marker esplicito: «{marker}»"

    return "vivo", "annuncio raggiungibile, nessun marker di chiusura"


def _is_list_redirect(original, final):
    if final.rstrip("/") == original.rstrip("/"):
        return False
    try:
        o = urllib.parse.urlsplit(original)
        f = urllib.parse.urlsplit(final)
    except Exception:
        return False
    if o.hostname != f.hostname:
        return False          # cambio host: troppo ambiguo per dire "chiuso"
    fp = f.path.rstrip("/").lower()
    # Il redirect conta solo se ATTERRA su una lista E il path si e' accorciato
    # (l'annuncio specifico era piu' profondo).
    return (len(fp) < len(o.path.rstrip("/"))
            and any(fp.endswith(h) or fp == h for h in LIST_PATH_HINTS))


def pick_url(entry):
    """URL da sondare + fonte. Preferisce la JD; apply_url e' il ripiego."""
    for src in entry.get("sources", []):
        for key in ("jd", "apply_url"):
            url = (src.get(key) or "").strip()
            if url.startswith("http"):
                return url, src.get("fonte", "?")
    return None, (entry.get("sources") or [{}])[0].get("fonte", "?")


def main():
    ap = argparse.ArgumentParser(
        description="Verifica se gli annunci in staging sono ancora aperti.")
    ap.add_argument("--staging", default="staging")
    ap.add_argument("--max", type=int, default=20,
                    help="quante voci sondare (default 20, le piu' vecchie prima)")
    ap.add_argument("--status", default="pending",
                    help="filtra per status; 'tutti' per non filtrare")
    ap.add_argument("--settings", default=".claude/settings.json")
    ap.add_argument("--format", choices=["text", "json"], default="json")
    args = ap.parse_args()

    root = Path(args.staging)
    if not root.is_dir():
        print(json.dumps([]) if args.format == "json"
              else f"staging non trovato: {root}")
        return EXIT_OK

    allowed = load_allowed_domains(args.settings)

    entries = []
    for sy in sorted(root.glob("*/staging.yaml")):
        try:
            e = read_staging(sy)
        except Exception:                                    # noqa: BLE001
            continue
        e["id"] = e.get("id") or sy.parent.name
        if args.status != "tutti" and e.get("status") != args.status:
            continue
        entries.append(e)

    # Le piu' vecchie prima: sono quelle con piu' probabilita' di essere morte
    # e quelle che il digest chiede di revisionare da piu' tempo.
    entries.sort(key=lambda e: e.get("run_id") or "")
    entries = entries[:args.max]

    results = []
    for e in entries:
        url, fonte = pick_url(e)
        if not url:
            verdetto, motivo = "indeterminato", "nessun URL utilizzabile nella voce"
        elif "linkedin.com" in url:
            verdetto, motivo = ("indeterminato",
                                "LinkedIn dietro login (V5): non verificabile da script")
        elif not host_allowed(url, allowed):
            verdetto, motivo = ("indeterminato",
                                "dominio non in sandbox.network.allowedDomains: non contattato")
        else:
            verdetto, motivo = probe(url)
        results.append({"id": e["id"], "verdetto": verdetto, "motivo": motivo,
                        "url": url, "fonte": fonte, "checked_at": now_iso()})

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        conteggi = {}
        for r in results:
            conteggi[r["verdetto"]] = conteggi.get(r["verdetto"], 0) + 1
        print(f"Liveness su {len(results)} voci: "
              + " · ".join(f"{k}: {v}" for k, v in sorted(conteggi.items())))
        for r in results:
            if r["verdetto"] != "vivo":
                icona = "⛔" if r["verdetto"] == "chiuso" else "❔"
                print(f"  {icona} {r['id']} [{r['fonte']}] — {r['motivo']}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
