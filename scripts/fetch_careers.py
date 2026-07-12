#!/usr/bin/env python3
"""fetch_careers.py — canale-fonte "career_page" della routine job-watch.

Legge `searches/companies.yaml`, interroga le career page delle aziende idonee
(`attiva: true`, `access_tier` A|B, `robots_ok: si`) e stampa su stdout un JSON
con le offerte NORMALIZZATE per azienda. Implementa i tre `adapter.kind`:
  - ats_feed  (tier A): feed pubblico di un ATS noto (Greenhouse/Lever/…).
  - json_api  (tier B1): endpoint JSON scoperto via probe (GET o POST), con
              risoluzione del buildId per gli endpoint Next.js build_dependent.
  - html_list (tier B2): sitemap dichiarato in robots.txt, o lista HTML statica.

Uso:  python scripts/fetch_careers.py [companies.yaml] [--limit N] [--only ID]
Env:  (nessuna) — stdlib only (urllib). PyYAML NON è richiesto: l'ambiente
      della routine non lo espone, quindi qui c'è un loader YAML minimale per
      il sottoinsieme usato da companies.yaml.

Regola di proprietà (D5): la routine NON scrive companies.yaml — lo LEGGE
soltanto. Questo script non scrive nulla su disco.

Semantica strict di robots_ok (voluta): solo `si` sblocca il fetch; `no` e
`da_verificare` (o assente) sono trattati IDENTICI = azienda saltata, come
tier C. Nessun default permissivo.

Exit code semantici (tutti NON fatali per la routine, che non fallisce MAI per
una fonte — decide solo cosa loggare/segnalare nel digest):
  0 = eseguito: JSON su stdout. Gli errori per-azienda vivono DENTRO il payload
      (`status: error|empty|skipped|invalid`), non nell'exit code — così la
      routine distingue "endpoint rotto" da "0 posizioni legittime" (§1 analisi).
  3 = niente da fare: file assente/non parsabile, o nessuna azienda idonea.

Il payload per-azienda porta `status` + `reason` + `offers[]`; la routine lo
mappa su `state.json.career_page_health.<id>` (consecutive_failures/empty).
"""
import sys
import json
import re
import ssl
import argparse
import html as _htmllib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_SKIPPED = 3

TIMEOUT = 25
UA = "job-hunter-careers/1.0 (+career_page channel; contact via repo owner)"

# access_tier ↔ adapter.kind concordi (schema companies.yaml, sezione (c)).
TIER_KINDS = {"A": {"ats_feed"}, "B": {"json_api", "html_list"}, "C": {"manual"}}
# Chiavi di primo livello dove cercare l'array di posizioni in una risposta JSON.
LIST_KEYS = ("response", "data", "jobPostings", "results", "jobs", "list",
             "postings", "items", "openings", "vacancies")


# ---------------------------------------------------------------------------
# Loader YAML minimale (sottoinsieme di companies.yaml)
# ---------------------------------------------------------------------------
# Gestisce: mapping/sequence a indentazione, `key: value`, `- item`, flow
# mapping `{}` / sequence `[]`, stringhe quotate, bool/int/null, commenti `#`.
# NON è un parser YAML generale — è tarato sul contratto di companies.yaml.

def _strip_comment(line):
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(tok):
    tok = tok.strip()
    if tok == "" or tok == "~" or tok == "null":
        return None
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ('"', "'"):
        return tok[1:-1]
    low = tok.lower()
    if low in ("true", "si", "yes"):
        # NB: nel contesto companies.yaml `si` è un valore di robots_ok, NON un
        # booleano — resta stringa. Qui trasformiamo in bool solo true/yes.
        return True if low in ("true", "yes") else tok
    if low == "false" or low == "no":
        return False if low == "false" else tok
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    if re.fullmatch(r"-?\d+\.\d+", tok):
        return float(tok)
    return tok


def _parse_flow(tok):
    """Parsa un flow collection JSON-ish: {a: 1, b: "x"} oppure [a, b]."""
    tok = tok.strip()
    # Trasforma in JSON: chiavi non quotate → quotate; `: ` mantenuto.
    # Approccio pragmatico: gestisci i casi reali ({}, [] e liste semplici).
    if tok == "{}":
        return {}
    if tok == "[]":
        return []
    if tok.startswith("[") and tok.endswith("]"):
        inner = tok[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in _split_flow(inner)]
    if tok.startswith("{") and tok.endswith("}"):
        inner = tok[1:-1].strip()
        d = {}
        for part in _split_flow(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                d[k.strip().strip('"\'')] = _flow_value(v.strip())
        return d
    return _scalar(tok)


def _flow_value(v):
    if v.startswith(("{", "[")):
        return _parse_flow(v)
    return _scalar(v)


def _split_flow(s):
    """Split su virgole di primo livello, rispettando {} [] e le virgolette."""
    parts, depth, quote, cur = [], 0, None, []
    for ch in s:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            cur.append(ch)
        elif ch in "{[":
            depth += 1
            cur.append(ch)
        elif ch in "}]":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p]


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def yaml_load(text):
    lines = []
    for raw in text.splitlines():
        s = _strip_comment(raw)
        if s.strip() == "":
            continue
        lines.append((_indent(s), s.strip(), s))
    pos = [0]

    def parse_block(min_indent):
        # Determina se è una sequence o un mapping guardando la prima riga.
        if pos[0] >= len(lines):
            return None
        indent, stripped, _ = lines[pos[0]]
        if indent < min_indent:
            return None
        if stripped.startswith("- "):
            return parse_seq(indent)
        return parse_map(indent)

    def parse_seq(indent):
        seq = []
        while pos[0] < len(lines):
            cur_indent, stripped, _ = lines[pos[0]]
            if cur_indent != indent or not stripped.startswith("- "):
                if cur_indent < indent:
                    break
                if cur_indent > indent:
                    break
                if not stripped.startswith("- "):
                    break
            body = stripped[2:].strip()
            pos[0] += 1
            if body == "":
                seq.append(parse_block(indent + 1))
            elif body.startswith(("{", "[")):
                seq.append(_parse_flow(body))
            elif ":" in body and not body.split(":", 1)[1].strip().startswith("//"):
                # Primo campo di un mapping inline dentro l'item: rientra e
                # continua a leggere le chiavi allo stesso livello logico.
                key, val = body.split(":", 1)
                item = {}
                _assign(item, key.strip(), val.strip(), indent + 2)
                # Le chiavi successive dell'item hanno indent > indent.
                while pos[0] < len(lines):
                    ci, cs, _ = lines[pos[0]]
                    if ci <= indent:
                        break
                    if cs.startswith("- ") and ci == indent:
                        break
                    k2, v2 = _next_kv()
                    if k2 is None:
                        break
                    _assign(item, k2, v2[0], v2[1])
                seq.append(item)
            else:
                seq.append(_scalar(body))
        return seq

    def _next_kv():
        indent, stripped, _ = lines[pos[0]]
        if ":" not in stripped:
            return None, None
        key, val = stripped.split(":", 1)
        pos[0] += 1
        return key.strip(), (val.strip(), indent + 1)

    def parse_map(indent):
        d = {}
        while pos[0] < len(lines):
            cur_indent, stripped, _ = lines[pos[0]]
            if cur_indent < indent:
                break
            if cur_indent > indent:
                break
            if stripped.startswith("- "):
                break
            if ":" not in stripped:
                break
            key, val = stripped.split(":", 1)
            pos[0] += 1
            _assign(d, key.strip(), val.strip(), indent + 1)
        return d

    def _assign(d, key, val, child_indent):
        key = key.strip().strip('"\'')
        if val == "":
            child = parse_block(child_indent)
            d[key] = child if child is not None else {}
        elif val.startswith(("{", "[")):
            d[key] = _parse_flow(val)
        else:
            d[key] = _scalar(val)

    root = parse_block(0)
    return root if root is not None else {}


# ---------------------------------------------------------------------------
# HTTP (stdlib)
# ---------------------------------------------------------------------------

def _ctx():
    return ssl.create_default_context()


def http_get(url, as_json=True, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json, */*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx()) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8", "replace")) if as_json else raw.decode("utf-8", "replace")


def http_post_json(url, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": UA, "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx()) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# Normalizzazione campi
# ---------------------------------------------------------------------------

def _coerce_text(v):
    """Riduce un valore (scalare/dict/list) a stringa leggibile."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        for k in ("title", "name", "text", "label", "value"):
            if k in v and isinstance(v[k], (str, int, float)):
                return str(v[k])
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        parts = [_coerce_text(x) for x in v]
        return ", ".join(p for p in parts if p)
    return str(v)


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def normalize_item(raw, field_map, company, apply_url_template, careers_url):
    out = {"company": company.get("nome")}
    for norm_key, api_key in (field_map or {}).items():
        val = raw.get(api_key) if isinstance(raw, dict) else None
        if norm_key == "native_id":
            out["native_id"] = _coerce_text(_first(val))
        elif norm_key in ("description_html", "description_text"):
            out[norm_key] = val if isinstance(val, str) else _coerce_text(val)
        else:
            out[norm_key] = _coerce_text(val)
    # apply_url: sostituisci ogni {campo} col valore RAW dell'item.
    apply_url = None
    if apply_url_template:
        try:
            apply_url = re.sub(
                r"\{(\w+)\}",
                lambda m: urllib.parse.quote(str(raw.get(m.group(1), "")), safe="/:?=&%"),
                apply_url_template,
            )
            if "{" in apply_url or "}" in apply_url or "//" not in apply_url.split(":", 1)[-1]:
                apply_url = apply_url  # best effort; lasciamo comunque il valore
        except Exception:
            apply_url = None
    jd = out.get("jd") or apply_url or careers_url
    out["jd"] = jd
    out["apply_url"] = apply_url or jd or careers_url
    return out


# ---------------------------------------------------------------------------
# Localizza l'array di posizioni in una risposta JSON
# ---------------------------------------------------------------------------

def find_postings(obj):
    if isinstance(obj, dict):
        for k in LIST_KEYS:
            v = obj.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        # fallback: la più lunga lista-di-dict ovunque nell'albero
        best = []
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                stack.extend(cur.values())
            elif isinstance(cur, list):
                if cur and isinstance(cur[0], dict):
                    if len(cur) > len(best):
                        best = cur
                else:
                    stack.extend(cur)
        return best
    if isinstance(obj, list):
        return obj
    return []


# ---------------------------------------------------------------------------
# Adapter: json_api
# ---------------------------------------------------------------------------

def resolve_build_id(careers_url):
    html = http_get(careers_url, as_json=False, headers={"Accept": "text/html"})
    m = re.search(r'"buildId":"([^"]+)"', html)
    if not m:
        raise ValueError("buildId non trovato nell'HTML di careers_url")
    return m.group(1)


def adapter_json_api(company, limit):
    a = company["adapter"]
    endpoint = a["list_endpoint"]
    if a.get("endpoint_stability") == "build_dependent" and "{buildId}" in endpoint:
        endpoint = endpoint.replace("{buildId}", resolve_build_id(company["careers_url"]))
    method = (a.get("http_method") or "GET").upper()
    query = dict(a.get("query") or {})
    pag = a.get("paginate_by") or []
    field_map = a.get("field_map") or {}
    pub = a.get("published_filter") or {}
    careers_url = company.get("careers_url")
    apply_tpl = company.get("apply_url_template")

    raw_items, offset = [], 0
    off_p = pag[0] if len(pag) == 2 else None
    lim_p = pag[1] if len(pag) == 2 else None
    page_size = int(query.get(lim_p, 50)) if lim_p else 50
    for _ in range(10):  # cap difensivo sul numero di pagine
        q = dict(query)
        if off_p:
            q[off_p] = offset
        if method == "POST":
            data = http_post_json(endpoint, q)
        else:
            url = endpoint + ("?" + urllib.parse.urlencode(q, doseq=True) if q else "")
            data = http_get(url)
        page = find_postings(data)
        if not page:
            break
        raw_items.extend(page)
        if len(raw_items) >= limit or not off_p or len(page) < page_size:
            break
        offset += page_size

    offers = []
    for raw in raw_items[: limit if limit else None]:
        if pub and not all(_coerce_text(raw.get(k)) == str(v) for k, v in pub.items()):
            continue
        offers.append(normalize_item(raw, field_map, company, apply_tpl, careers_url))
    return offers


# ---------------------------------------------------------------------------
# Adapter: html_list (sitemap | static_page)
# ---------------------------------------------------------------------------

def _looks_like_id(s):
    """Segmento 'id' tipo 2024-32730, R-212290, 12345 — non un titolo leggibile."""
    return bool(re.fullmatch(r"\d{2,}(-\d+)?", s) or re.fullmatch(r"[A-Za-z]{1,3}-?\d+", s))


def _slug_parts(url):
    """Ritorna (native_id, title_slug) da un URL job.

    Alcune fonti mettono l'id come ULTIMO segmento e lo slug descrittivo come
    penultimo (Akkodis: .../<slug-descrittivo>/2024-32730); altre hanno lo slug
    descrittivo come ultimo segmento (Arkemis: .../jobs/backend-developer).
    """
    segs = [s for s in urllib.parse.urlparse(url).path.strip("/").split("/") if s]
    if not segs:
        return None, None
    native_id = segs[-1]
    if _looks_like_id(segs[-1]) and len(segs) >= 2:
        title_slug = segs[-2]
    else:
        title_slug = segs[-1]
    return native_id, title_slug


def _humanize(slug):
    if not slug:
        return None
    return re.sub(r"[-_]+", " ", slug).title()


def _origin(url):
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _strip_tags(s):
    if not isinstance(s, str):
        return s
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _jsonld_jobposting(page_html):
    """Ritorna il primo blocco JSON-LD di tipo JobPosting, o None."""
    for b in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html, re.S | re.I,
    ):
        try:
            data = json.loads(b.strip())
        except Exception:  # noqa: BLE001 — un blocco malformato non deve fermare il resto
            continue
        for it in (data if isinstance(data, list) else [data]):
            if isinstance(it, dict) and "JobPosting" in str(it.get("@type", "")):
                return it
    return None


def _detail_extract(page_html, selector):
    """Estrae un valore dalla pagina di dettaglio con un selettore semplice.

    Forme supportate (stdlib-only, regex mirato — NON un parser HTML completo):
      - tag semplice: `h1`, `h2` → inner HTML del primo match.
      - `jsonld:<campo>`: campo dello schema JobPosting JSON-LD; `jsonld:location`
        estrae jobLocation.address.addressLocality|location|addressRegion
        (unisce più sedi con ", ").
      - `meta:<property>`: content del <meta property|name="<property>"> (es. og:description).
    """
    sel = (selector or "").strip()
    if not sel:
        return None
    if sel.startswith("jsonld:"):
        field = sel.split(":", 1)[1]
        jp = _jsonld_jobposting(page_html)
        if not jp:
            return None
        if field == "location":
            locs = jp.get("jobLocation")
            locs = locs if isinstance(locs, list) else [locs]
            vals = []
            for loc in locs:
                if isinstance(loc, dict):
                    addr = loc.get("address") or {}
                    v = (addr.get("addressLocality") or addr.get("location")
                         or addr.get("addressRegion")) if isinstance(addr, dict) else None
                    if v:
                        vals.append(str(v).strip())
            return ", ".join(dict.fromkeys(vals)) if vals else None
        v = jp.get(field)
        return _htmllib.unescape(v) if isinstance(v, str) else v
    if sel.startswith("meta:"):
        prop = sel.split(":", 1)[1]
        m = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\'](.*?)["\']',
            page_html, re.S | re.I,
        )
        return _htmllib.unescape(m.group(1)).strip() if m else None
    m = re.search(rf"<{re.escape(sel)}\b[^>]*>(.*?)</{re.escape(sel)}>", page_html, re.S | re.I)
    return m.group(1) if m else None


def _apply_detail(offer, page_html, detail_field_map):
    """Applica detail_field_map all'offerta (in place). Coercizione per-campo."""
    for norm_key, selector in (detail_field_map or {}).items():
        raw = _detail_extract(page_html, selector)
        if raw in (None, ""):
            continue
        if norm_key in ("title", "location", "company"):
            offer[norm_key] = _strip_tags(_htmllib.unescape(raw)) if isinstance(raw, str) else raw
        elif norm_key in ("description_html", "description_text"):
            offer[norm_key] = raw  # già HTML/testo, mantieni
        else:
            offer[norm_key] = raw


def adapter_html_list(company, limit):
    a = company["adapter"]
    src = a.get("list_source")
    careers_url = company.get("careers_url")
    apply_tpl = company.get("apply_url_template")
    urls = []

    if src == "sitemap":
        idx_xml = http_get(a["list_url"], as_json=False)
        sub = re.findall(r"<loc>([^<]+)</loc>", idx_xml)
        filt = a.get("sitemap_filter")
        targets = [u for u in sub if (filt in u)] if filt else sub
        if not targets:  # list_url era già la sitemap foglia
            targets = [a["list_url"]]
        for sm in targets:
            job_xml = http_get(sm, as_json=False)
            for loc in re.findall(r"<loc>([^<]+)</loc>", job_xml):
                if loc not in urls:
                    urls.append(loc)
                if len(urls) >= limit:
                    break
            if len(urls) >= limit:
                break
    elif src == "static_page":
        html = http_get(a["list_url"], as_json=False)
        pattern = a.get("url_pattern", "")
        m = re.search(r'href\^?="([^"]+)"', pattern)
        prefix = m.group(1) if m else "/"
        origin = _origin(a["list_url"])
        seen = set()
        for href in re.findall(r'href="([^"]+)"', html):
            if href.startswith(prefix) and href not in seen:
                seen.add(href)
                urls.append(href if href.startswith("http") else origin + href)
            if len(urls) >= limit:
                break

    # Fetch di dettaglio (costo O(N annunci), NON O(1) per azienda): per ogni
    # URL raccolto si apre la pagina e si applica detail_field_map. Il numero di
    # detail-fetch è limitato a `limit` (`urls[:limit]`) — così Akkodis, con 313
    # URL nel sitemap, non scarica 313 pagine a ogni run ma solo le prime `limit`
    # (default 50). Un fallimento del dettaglio è per-offerta e non fatale:
    # l'offerta resta col titolo derivato dallo slug e `detail_pending: true`.
    detail_map = a.get("detail_field_map") or {}
    do_detail = bool(a.get("detail_fetch_required")) and bool(detail_map)
    offers = []
    for u in urls[:limit]:
        native_id, title_slug = _slug_parts(u)
        offer = {
            "company": company.get("nome"),
            "native_id": native_id,
            "title": _humanize(title_slug),
            "location": None,
            "jd": u,
            "apply_url": u,
            "detail_pending": bool(a.get("detail_fetch_required")),
        }
        if do_detail:
            try:
                page = http_get(u, as_json=False, headers={"Accept": "text/html"})
                _apply_detail(offer, page, detail_map)
                offer["detail_pending"] = False
            except Exception:  # noqa: BLE001 — degradazione elegante per-offerta
                offer["detail_pending"] = True  # ritenta al run successivo
        offers.append(offer)
    return offers


# ---------------------------------------------------------------------------
# Adapter: ats_feed (tier A — vendor noti)
# ---------------------------------------------------------------------------

def adapter_ats_feed(company, limit):
    a = company["adapter"]
    ats = a.get("ats")
    token = a.get("token")
    careers_url = company.get("careers_url")
    offers = []
    if ats == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
        data = http_get(url)
        for j in (data.get("jobs") or [])[:limit]:
            offers.append({
                "company": company.get("nome"),
                "native_id": str(j.get("id")),
                "title": j.get("title"),
                "location": _coerce_text(j.get("location")),
                "published_at": j.get("updated_at"),
                "jd": j.get("absolute_url"),
                "apply_url": j.get("absolute_url"),
            })
    elif ats == "lever":
        url = f"https://api.lever.co/v0/postings/{token}?mode=json"
        data = http_get(url)
        for j in (data if isinstance(data, list) else [])[:limit]:
            offers.append({
                "company": company.get("nome"),
                "native_id": str(j.get("id")),
                "title": j.get("text"),
                "location": _coerce_text((j.get("categories") or {}).get("location")),
                "published_at": j.get("createdAt"),
                "jd": j.get("hostedUrl"),
                "apply_url": j.get("applyUrl") or j.get("hostedUrl"),
            })
    else:
        raise ValueError(f"ats '{ats}' non ancora implementato in Fase 1 "
                         f"(supportati: greenhouse, lever)")
    return offers


# ---------------------------------------------------------------------------
# Validazione a runtime + dispatch
# ---------------------------------------------------------------------------

REQUIRED = {
    "ats_feed": ("ats", "token"),
    "json_api": ("list_endpoint", "field_map"),
    "html_list": ("list_source", "list_url", "detail_fetch_required"),
    "manual": (),
}


def validate(company):
    """Ritorna (ok, status, reason). Non interroga: solo controlli strutturali."""
    tier = company.get("access_tier")
    adapter = company.get("adapter") or {}
    kind = adapter.get("kind")
    if not company.get("attiva", False):
        return False, "skipped", "attiva:false (congelata)"
    if tier == "C" or kind == "manual":
        return False, "skipped", "tier C / adapter manual — tracciata, non interrogata"
    if tier not in TIER_KINDS or kind not in TIER_KINDS.get(tier, set()):
        return False, "invalid", f"access_tier '{tier}' incoerente con adapter.kind '{kind}'"
    missing = [f for f in REQUIRED.get(kind, ()) if f not in adapter]
    if missing:
        return False, "invalid", f"campi obbligatori mancanti per kind {kind}: {missing}"
    if company.get("robots_ok") != "si":
        return False, "skipped", (f"robots_ok='{company.get('robots_ok')}' "
                                  "(solo 'si' sblocca il fetch) — in attesa di verifica")
    return True, None, None


DISPATCH = {
    "ats_feed": adapter_ats_feed,
    "json_api": adapter_json_api,
    "html_list": adapter_html_list,
}


def run(companies, limit, only):
    results = []
    for company in companies:
        cid = company.get("id", "?")
        if only and cid != only:
            continue
        ok, status, reason = validate(company)
        if not ok:
            results.append({"id": cid, "nome": company.get("nome"),
                            "status": status, "reason": reason, "offers": []})
            continue
        kind = company["adapter"]["kind"]
        try:
            offers = DISPATCH[kind](company, limit)
            results.append({
                "id": cid, "nome": company.get("nome"),
                "access_tier": company.get("access_tier"),
                "adapter_kind": kind,
                "status": "ok" if offers else "empty",
                "reason": None if offers else "0 posizioni (200 OK, lista vuota)",
                "count": len(offers),
                "offers": offers,
            })
        except Exception as e:  # noqa: BLE001 — degradazione elegante per-azienda
            results.append({
                "id": cid, "nome": company.get("nome"),
                "access_tier": company.get("access_tier"),
                "adapter_kind": kind,
                "status": "error",
                "reason": f"{type(e).__name__}: {e}",
                "offers": [],
            })
    return results


NETWORK_EXC = (
    "URLError", "HTTPError", "ConnectionResetError", "ConnectionRefusedError",
    "ConnectionAbortedError", "TimeoutError", "socket.timeout", "gaierror",
    "SSLError", "SSLCertVerificationError", "OSError",
)


def _exc_type(reason):
    """Estrae il nome dell'eccezione dal `reason` ('TipoErrore: messaggio')."""
    return (reason or "").split(":", 1)[0].strip()


def diagnose(results):
    """Verdetto aggregato leggibile a colpo d'occhio (per la sezione 'Anomalie'
    del digest): distingue un fallimento isolato (una fonte rotta) da un
    pattern sistemico (probabile blocco dell'egress HTTPS nell'ambiente —
    stessa classe di problema già vista con l'SMTP diretto in cloud, vedi
    send_digest.py). NON decide nulla da sola: è un aiuto alla lettura, la
    routine resta libera di interpretare diversamente se ha altro contesto.
    """
    attempted = [r for r in results if r["status"] in ("ok", "empty", "error")]
    errors = [r for r in attempted if r["status"] == "error"]
    if not attempted:
        return {"verdetto": "nessuna azienda idonea interrogata in questo run"}
    if not errors:
        return {"verdetto": "nessun errore — canale career_page operativo"}
    exc_types = [_exc_type(r["reason"]) for r in errors]
    from collections import Counter
    counts = Counter(exc_types)
    top_exc, top_n = counts.most_common(1)[0]
    is_network = any(n in top_exc for n in NETWORK_EXC)
    # Firma specifica del blocco per-dominio del sandbox Claude Code (distinto
    # da un generico errore di rete: timeout/DNS non sono "il dominio manca
    # dall'allowlist", sono guasti diversi con rimedi diversi). Riconosciuta
    # empiricamente il 2026-07-12 (v. companies.yaml, tutte e 5 le aziende).
    sandbox_signature = sum(
        1 for r in errors
        if "tunnel connection failed" in (r.get("reason") or "").lower()
        and "403" in (r.get("reason") or "")
    )
    if len(attempted) < 2:
        verdetto = ("campione insufficiente (1 sola azienda idonea in questo run) "
                    "per distinguere un blocco ambientale da un problema isolato")
    elif sandbox_signature == len(errors) and sandbox_signature >= 1:
        verdetto = (f"BLOCCO SANDBOX PER DOMINIO (firma nota): {sandbox_signature} "
                    "aziende falliscono con 'Tunnel connection failed: 403 Forbidden' — "
                    "è la firma specifica del proxy di rete del sandbox Claude Code che "
                    "nega un dominio non presente in sandbox.network.allowedDomains "
                    "(.claude/settings.json), NON un endpoint rotto. Rimedio: verifica "
                    "che i domini delle aziende in errore siano in quella lista (il "
                    "runbook di aggiunta azienda — job-search-profile, Passo 6-bis — "
                    "dovrebbe averli già aggiunti: se mancano, è un'azienda aggiunta "
                    "senza quel passo).")
    elif top_n == len(attempted) and is_network:
        verdetto = (f"BLOCCO AMBIENTALE PROBABILE: tutte le {len(attempted)} aziende "
                    f"interrogate falliscono con lo stesso errore di rete ({top_exc}) — "
                    "pattern coerente con un egress HTTPS bloccato nell'ambiente, "
                    "non con un endpoint rotto isolato, ma SENZA la firma nota del "
                    "blocco per-dominio del sandbox (altrimenti sarebbe il caso sopra) — "
                    "verifica comunque sandbox.network.allowedDomains per primo, poi "
                    "considera altre cause (rete generale, DNS). Segnala esplicitamente "
                    "nel digest, sezione anomalie.")
    elif top_n >= max(2, len(attempted) // 2) and is_network:
        verdetto = (f"possibile blocco parziale: {top_n}/{len(attempted)} aziende "
                    f"falliscono con lo stesso errore di rete ({top_exc}) — non "
                    "conclusivo, ma da segnalare nel digest per un secondo run di conferma.")
    else:
        verdetto = (f"fallimenti isolati ({len(errors)}/{len(attempted)}), errori "
                    f"eterogenei o non di rete (più frequente: {top_exc} x{top_n}) — "
                    "probabile problema per-azienda (endpoint cambiato), non ambientale.")
    return {"verdetto": verdetto, "errori_per_tipo": dict(counts),
            "aziende_in_errore": [r["id"] for r in errors]}


def main():
    ap = argparse.ArgumentParser(description="Fetch career page → JSON normalizzato")
    ap.add_argument("companies", nargs="?", default="searches/companies.yaml")
    ap.add_argument("--limit", type=int, default=50,
                    help="max offerte per azienda (default 50)")
    ap.add_argument("--only", default=None, help="interroga solo l'azienda con questo id")
    args = ap.parse_args()

    path = Path(args.companies)
    if not path.exists():
        print(json.dumps({"error": f"companies.yaml non trovato: {path}",
                          "companies": []}, ensure_ascii=False))
        return EXIT_SKIPPED
    try:
        doc = yaml_load(path.read_text(encoding="utf-8"))
        companies = (doc or {}).get("companies") or []
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"parsing companies.yaml fallito: {e!r}",
                          "companies": []}, ensure_ascii=False))
        return EXIT_SKIPPED

    eligible = [c for c in companies if c.get("attiva") and c.get("access_tier") in ("A", "B")]
    if not eligible:
        print(json.dumps({"note": "nessuna azienda idonea (attiva + tier A|B)",
                          "companies": []}, ensure_ascii=False))
        return EXIT_SKIPPED

    results = run(companies, args.limit, args.only)
    summary = {
        "ok": sum(1 for r in results if r["status"] == "ok"),
        "empty": sum(1 for r in results if r["status"] == "empty"),
        "error": sum(1 for r in results if r["status"] == "error"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "invalid": sum(1 for r in results if r["status"] == "invalid"),
        "total_offers": sum(len(r["offers"]) for r in results),
    }
    print(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "diagnosis": diagnose(results),
        "companies": results,
    }, ensure_ascii=False, indent=2))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
