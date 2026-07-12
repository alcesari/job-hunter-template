# Runbook — probe di ispezione di rete (operazione "aggiungi azienda")

Procedura passo-passo, riproducibile, per classificare un'azienda A/B/C e
compilare la sua voce in `searches/companies.yaml` (schema formale: sezione
`(c)` di `.claude/skills/agent-config/references/search-profile.schema.yaml`).
È la sequenza **realmente eseguita** su gogenerali.com il 2026-07-12,
generalizzata.

**Nota di ambiente (leggere prima)**: la probe richiede i **tool browser del
harness** (`preview_start`/`navigate`, `read_network_requests`,
`javascript_tool`) → è eseguibile solo in una **sessione interattiva Claude
Code Desktop**, NON dalla routine `job-watch` né da chat claude.ai pura
(connettore GitHub read-only, niente browser). Quando i tool browser non
rispondono, il Passo 3b è il fallback verificato (ispezione HTML/config via
`curl`).

**Regola d'oro**: `robots_ok: si` si scrive SOLO se la verifica robots.txt è
stata fatta davvero in questa conversazione. Se non riesci a completare la
probe (tool assenti, sito irraggiungibile), scrivi comunque la voce ma con
`robots_ok: da_verificare` — la routine la tratterà come tier C (tracciata,
non interrogata) — e dillo esplicitamente all'utente.

---

## Passo 1 — Discovery del careers vero (WebSearch + WebFetch)

Cerca `"<azienda> careers"` / `"<azienda> lavora con noi"`. Attenzione ai due
inganni noti: (a) il careers può stare su un dominio diverso dal corporate
(Generali → gogenerali.com); (b) i gruppi hanno più careers per entità legale
(Generali Group ≠ Generali Italia ≠ Generali Investments) → **chiedi
all'utente quale entità gli interessa** prima di procedere. Se l'utente
fornisce direttamente l'URL, questo passo si salta (l'URL diretto previene
l'ambiguità multi-entità). Output: `careers_url` candidato.

## Passo 2 — Riconoscimento vendor ATS (tier A, il caso veloce)

`WebFetch` del `careers_url` e guarda URL finale + link degli annunci. Pattern
che chiudono subito a **tier A** (estrai il token dall'URL):
`boards.greenhouse.io/<token>` o `job-boards.greenhouse.io/<token>`,
`jobs.lever.co/<company>`, `jobs.ashbyhq.com/<name>`,
`careers.smartrecruiters.com/<Company>`, `<company>.recruitee.com`,
`apply.workable.com/<account>`, `<company>.jobs.personio.de`. Trovato il
pattern → compila `adapter: {kind: ats_feed, ats: <vendor>, token: <token>}` e
salta al Passo 5 (verifica).

## Passo 3 — Ispezione di rete (tier B1, il caso gogenerali)

Nessun vendor riconosciuto → apri la pagina nel browser del harness e osserva
cosa chiama la SPA:
1. `preview_start {url: <careers_url>}` (o `navigate` se il browser è già aperto);
2. `computer {action: wait, duration: 3}` — lascia caricare la SPA (le XHR
   partono dopo il primo render);
3. `read_network_requests {urlPattern: "api"}` — se vuoto, riprova con pattern
   `"job"`, `"search"`, `"posting"`, `"vacan"`, `"position"`, e in ultima
   istanza senza filtro guardando le sole richieste `GET`/`POST` con risposta
   `200` verso lo stesso dominio;
4. Cerca la richiesta che *elenca* le posizioni (di solito ha parametri di
   paginazione tipo `fromRecord`/`offset`/`page` e viene ripetuta per
   categoria/filtro). Annota: URL, metodo, parametri.

**Pattern Workday noto (da provare presto per aziende enterprise)**: se
`careers_url` è del tipo `<tenant>.wdN.myworkdayjobs.com/<site>`, prova il
CXS non documentato: `POST .../wday/cxs/<tenant>/<site>/jobs` con body JSON
(paginazione via `offset`/`limit`). Verificato su SimCorp (285 posizioni).

## Passo 3b — Fallback quando il browser del harness non è disponibile

(Osservato realmente il 2026-07-12: `preview_start`/`navigate` in timeout.)
L'ispezione di rete via browser resta il metodo primario, ma non è l'unico:
1. `curl` l'HTML della pagina (`curl -sS <careers_url>`) e cerca nel sorgente
   config JS embedded (`grep -oE 'window\.__[A-Z_]+__[^<]*'`, `__NEXT_DATA__`,
   `__NUXT__`) — spesso contiene l'URL base dell'API anche se la chiamata vera
   avviene solo via JS (caso Arkemis: `window.__ENV__` ha rivelato `ARKE_URL`).
   Per Next.js: se compare un percorso tipo `/_next/data/<buildId>/…` nei tag
   `<script>`, prova `curl <careers_url>/_next/data/<buildId>/index.json` —
   spesso è il payload SSR completo (caso Bending Spoons: 39 posizioni
   complete in un colpo solo, JSON pulito nonostante nessun vendor noto).
2. Per applicazioni React/Next.js con rendering ibrido, cerca chunk RSC
   embedded (`grep -oE "self\.__next_f\.push"`) — a volte i dati sono già
   serializzati nell'HTML iniziale, niente chiamata separata da trovare
   (caso Arkemis: le 7 posizioni erano già in `<h2>` dentro `<a href="/jobs/…">`).
3. **Non indovinare path API alla cieca** (`/api/jobs`, `/api/positions`, …
   provati uno a uno senza indizio): non è ispezione, è brute-force, ed è
   il tipo di rumore che un WAF può scambiare per abuso. Se non emerge nulla
   dai passi 1–2, passa al Passo 3c prima di arrenderti al tier C.

## Passo 3c — Controlla `robots.txt` per un sitemap job-specifico (tier B2)

Anche senza API, `robots.txt` spesso dichiara un sitemap dedicato ai job
(pattern osservato: `Sitemap: https://<dominio>/jobsindex.xml` o simili — caso
Akkodis: sitemap-index con 23 sotto-sitemap per paese/lingua, quello italiano
con 313 URL e `lastmod` aggiornato al giorno corrente). Se c'è: è un segnale di
permesso esplicito al crawling **più forte** di un generico allow implicito —
usalo come `adapter.kind: html_list, list_source: sitemap`. Se manca il
sitemap ma la pagina lista è HTML statico con markup prevedibile (niente
framework JS pesante, i titoli/link sono già nell'HTML scaricato con `curl`,
caso Arkemis) → `list_source: static_page`, annota il selettore.

## Passo 4 — Verifica dello shape (fetch diretto dell'endpoint sospetto)

Chiama l'endpoint fuori dal flusso della pagina:
1. dal browser: `javascript_tool` con `fetch(<endpoint>).then(r => r.json())` —
   attenzione: niente `await` top-level nel tool, usa la catena `.then()`;
2. **conferma no-cookie (obbligatoria)**: ripeti da contesto pulito con
   `curl -sS -H 'Accept: application/json' '<endpoint>'` in Bash — se risponde
   `200` con gli stessi dati, l'endpoint è pubblico; se risponde `401/403` o
   dati vuoti, è session-bound → **tier C**, non B;
3. verifica che la risposta contenga, per ogni posizione, ALMENO: un id nativo,
   il titolo, la location, e (idealmente) descrizione + data + stato di
   pubblicazione. Annota i nomi esatti dei campi → `field_map`. Se c'è un campo
   stato (es. `currentStatus`), annota il valore "pubblicato" → `published_filter`.

## Passo 5 — Verifica robots.txt + ToS (per A e B)

`curl -sS https://<dominio>/robots.txt` e controlla le direttive per il path
dell'endpoint (`Disallow:` vuoto = tutto permesso, com'è per gogenerali). Se il
path dell'endpoint è disallowed → **la voce nasce con `robots_ok: no` e la
routine non la interrogherà** (equivale a tier C), qualunque cosa dica la
tecnica. Segnala all'utente l'esistenza di eventuali ToS del sito da leggere.

## Passo 6 — Compila la voce e chiudi

Scrivi la voce in `companies.yaml` secondo lo schema formale (sezione `(c)`):
tier, adapter completo, `robots_ok`, `verificato: <oggi>`, `apply_url_template`
se ricostruibile dall'id nativo (cerca nel sito il pattern URL del singolo
annuncio, es. `/home/job/{contestId}/Job`). Mostra all'utente il diff e la
classificazione ottenuta **prima** di committare (flusso standard di
job-search-profile, passo 3). Se l'esito è **tier C**: dillo esplicitamente
("la routine non saprà leggere questa azienda; resterà tracciata nel digest e
candidabile via link diretto") — mai far credere che funzionerà.

## Esiti anomali noti

- Pagina che richiede login anche per il *listing* → tier C per regola ToS
  (niente automazione dietro login), non tentare bypass.
- Endpoint che risponde solo con header particolari (CSRF token, `Referer`) →
  trattalo come session-bound → tier C nel prototipo (un adapter con header
  custom è complessità da Fase 2, se mai).
- Cloudflare/anti-bot challenge sul fetch pulito → tier C.
