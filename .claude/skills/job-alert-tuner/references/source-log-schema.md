# source-log — contratto dato (definito da job-alert-tuner, modulo 1.2.2)

Questo file È il contratto che la routine `job-watch` rispetta scrivendo il `source-log` a ogni run. Se i file non esistono, la routine non ha ancora girato (o l'ultima run è fallita prima di scrivere): `job-alert-tuner` lo gestisce come caso previsto (vedi SKILL.md).

## Dove vive

- Nel repo del sistema, cartella `source-log/`, un file per mese: `source-log/YYYY-MM.jsonl` (**rotazione mensile**). La rotazione partiziona; la **potatura** la fa la routine a ogni run (mensili più vecchi di 12 mesi eliminati — soglie complete nel passo Retention di `job-watch/SKILL.md`; la storia resta in git).
- Scritto in **append reale** dalla routine a ogni esecuzione: append di righe in fondo al file del mese corrente. Nel repo unico non serve più alcun workaround "leggi-tutto-riscrivi" (era un limite del vecchio storage Drive, che non aveva append) — il filesystem locale + git appendono nativamente.
- Scritto nello **stesso commit** di `state.json` (punto 8 della routine): nel repo unico la coerenza run↔log diventa quasi-atomica, un miglioramento rispetto al vecchio design a due storage.
- Committato e (per la routine cloud) pushato. Letto da `job-alert-tuner` (1.2.2).

## Formato

JSONL (JSON Lines), UTF-8: un oggetto JSON per riga, terminato da `\n`. Prima riga = primo record (nessun header, a differenza del CSV).

Perché JSONL e non CSV (scelta di progetto, D6):
- **Evoluzione dello schema senza rotture**: aggiungere una chiave nuova non invalida le righe vecchie né rompe il parsing (con un CSV a colonne fisse invece sì).
- **Robustezza sul testo libero**: titoli/aziende con virgole, virgolette, a-capo non richiedono quoting fragile.
- **Diff git puliti**: una riga per record = diff leggibili, append che non toccano le righe esistenti.
- **Parsing banale**: `pandas.read_json(path, lines=True)` o lettura riga-per-riga; una riga malformata non compromette le altre.

## Semantica: una riga = un annuncio osservato da una ricerca in una esecuzione

Se lo stesso annuncio è restituito da 3 ricerche diverse nella stessa run → 3 righe (è esattamente questo che rende calcolabile l'overlap). Include anche gli annunci poi scartati o già visti: il log fotografa cosa PORTA ogni ricerca, non cosa sopravvive alla pipeline.

## Chiavi (le vecchie colonne CSV, stessi nomi e semantica; JSON)

| Chiave | Obbligatoria | Tipo | Contenuto |
|---|---|---|---|
| `run_id` | sì | string | Timestamp ISO 8601 dell'esecuzione (es. `2026-07-05T06:00:00Z`). Identico per tutte le righe della stessa run. È SEMPRE l'istante **UTC reale** di inizio run (`date -u` o equivalente), MAI l'orario schedulato né l'ora locale col suffisso `Z`: un orario locale spacciato per UTC rompe l'ordinamento cronologico e i trend per-run del tuner. |
| `intento_id` | sì | string | `id` dell'intento (`searches/<intent-id>.yaml`) che ha generato la ricerca. NUOVO con D2: è la chiave che permette di aggregare/segmentare le metriche per intento e di rilevare l'overlap TRA intenti. |
| `fonte` | sì | enum | `indeed` \| `linkedin_alert` \| `indeed_alert` \| `career_page` (stessi valori di `fonti.nome` nell'intento). |
| `azienda_fonte` | solo se `fonte: career_page` | string | `id` dell'azienda in `searches/companies.yaml` la cui career page ha prodotto la riga (es. `generali-gruppo`). Assente per le altre fonti. È la chiave che permette al tuner di misurare la resa per-azienda e il cross-source overlap. |
| `ricerca_id` | sì | string | Identificatore STABILE della ricerca che ha prodotto la riga, **prefissato dall'intento**. Convenzione: `<intento_id>:<fonte>:<titolo>:<location>` tutto minuscolo (es. `data-engineering-eu:indeed:data engineer:milano`). Il prefisso d'intento preserva la stabilità e rende l'attribuzione univoca: la routine non cambia formato tra una run e l'altra. **Per `fonte: linkedin_alert`/`indeed_alert`** la ricerca è un avviso salvato sulla piattaforma: la convenzione è la **chiave canonica del registro** (`searches/alerts-registry.yaml`) `<intento_id>:linkedin_alert:<keywords-slug>:<geoId>` (es. `backend-fullstack-ecommerce:linkedin_alert:backend-developer-or-java-developer-or-full-stack-developer:103350119`), risolta da `searches/alerts-registry.yaml`; un alert non nel registro dà `<intento_id>:linkedin_alert:unmatched:<chiave>`. Per `fonte: career_page` la ricerca è "scarica il feed dell'azienda": convenzione `<intento_id>:career_page:<azienda_fonte>` (es. `backend-fullstack-ecommerce:career_page:generali-gruppo`). |
| `annuncio_id` | sì | string | Chiave canonica dell'annuncio — LO STESSO identificatore usato in `state.json` per il dedup. È la chiave che permette di calcolare l'overlap. Formato definitivo `<fonte>:<slug(azienda)>:<slug(titolo)>:<slug(location)>` (regola di slug in `job-watch/SKILL.md`, sezione dedup). |
| `esito` | sì | enum | Esito pipeline per questa run: `incluso_principale` \| `incluso_da_verificare` \| `scartato_lingua` \| `scartato_livello` (Head of/Director/stage o anti-target di `esclusioni.titoli_da_escludere`) \| `scartato_ruolo` (titolo non pertinente ai `ruoli_target` dell'intento — gate positivo di ruolo, prodotto SOLO dal canale `career_page`, che fetcha tutte le posizioni dell'azienda; distinto da `scartato_livello`, che è un anti-target dichiarato, mentre questo è "ruolo semplicemente estraneo": es. HR/actuarial/sales a Generali) \| `scartato_location` (fuori dalle `location_target` dell'intento — anch'esso SOLO `career_page`, che fetcha per-azienda e non per-location; gli altri canali hanno ruolo e location già nella query) \| `scartato_dedup` (già in state.json) \| `non_lavorato_cap` (tagliato dal cap max annunci). |
| `titolo` | no | string | Titolo annuncio, per leggibilità/debug. |
| `azienda` | no | string | Azienda, per leggibilità/debug. |
| `location` | no | string | Location dichiarata dall'annuncio. |

Chiavi aggiuntive per riga sono ammesse senza rompere nulla (è la proprietà che ha fatto scegliere JSONL): un parser che non le conosce le ignora.

## Esempio (`source-log/2026-07.jsonl`)

```jsonl
{"run_id":"2026-07-05T06:00:00Z","intento_id":"data-engineering-eu","fonte":"indeed","ricerca_id":"data-engineering-eu:indeed:data engineer:milano","annuncio_id":"indeed:azienda-x:data-engineer:milano","esito":"incluso_principale","titolo":"Data Engineer","azienda":"Azienda X","location":"Milano"}
{"run_id":"2026-07-05T06:00:00Z","intento_id":"data-engineering-eu","fonte":"indeed","ricerca_id":"data-engineering-eu:indeed:bi developer:milano","annuncio_id":"indeed:azienda-x:data-engineer:milano","esito":"scartato_dedup","titolo":"Data Engineer","azienda":"Azienda X","location":"Milano"}
{"run_id":"2026-07-05T06:00:00Z","intento_id":"data-engineering-eu","fonte":"linkedin_alert","ricerca_id":"data-engineering-eu:linkedin_alert:data-engineer-or-etl-developer:102890719","annuncio_id":"linkedin_alert:azienda-y:etl-developer:amsterdam","esito":"incluso_da_verificare","titolo":"ETL Developer","azienda":"Azienda Y","location":"Amsterdam"}
{"run_id":"2026-07-12T06:00:00Z","intento_id":"backend-fullstack-ecommerce","fonte":"career_page","azienda_fonte":"generali-gruppo","ricerca_id":"backend-fullstack-ecommerce:career_page:generali-gruppo","annuncio_id":"career_page:generali-italia:java-backend-developer:milano","esito":"incluso_principale","titolo":"Java Backend Developer","azienda":"Generali Italia SpA","location":"Milano"}
{"run_id":"2026-07-12T06:00:00Z","intento_id":"backend-fullstack-ecommerce","fonte":"career_page","azienda_fonte":"generali-gruppo","ricerca_id":"backend-fullstack-ecommerce:career_page:generali-gruppo","annuncio_id":"career_page:generali-italia:actuarial-analyst:trieste","esito":"scartato_ruolo","titolo":"Actuarial Analyst","azienda":"Generali Italia SpA","location":"Trieste"}
{"run_id":"2026-07-12T06:00:00Z","intento_id":"backend-fullstack-ecommerce","fonte":"career_page","azienda_fonte":"simcorp","ricerca_id":"backend-fullstack-ecommerce:career_page:simcorp","annuncio_id":"career_page:simcorp:principal-sales-manager:manila","esito":"scartato_location","titolo":"Principal Sales Manager","azienda":"SimCorp","location":"Manila"}
```

(Le ultime due righe mostrano i due filtri career_page-only, nell'ordine in cui
la routine li applica. **Ruolo prima**: "Actuarial Analyst" a Generali non
matcha nessun token distintivo dei `ruoli_target` backend/e-commerce →
`scartato_ruolo` (è il filtro che taglia il grosso: ~90 posizioni non-tech su
196). **Location poi**: "Principal Sales Manager" a SimCorp — Manila non è
compatibile con Milano/Roma/Remote Italia/Remote EU → `scartato_location`.)

(La seconda riga mostra il caso overlap: stesso `annuncio_id` da due ricerche; per la seconda risulta `scartato_dedup` perché già processato.)

## `source-log/runs.jsonl` — ledger delle run (osservabilità)

File JSONL append-only, accanto ai mensili, scritto SOLO dalla routine. Due
righe per run:

| Riga | Quando | Contenuto |
|---|---|---|
| start | Primo atto dopo il `git pull`, **committata+pushata da sola** prima di toccare le fonti | `{"run_id":"<UTC>","fase":"start"}` |
| end | In coda alla run, nel commit finale | `{"run_id":"<UTC>","fase":"end","esito":"ok\|parziale\|fallita","note":"<solo se non ok>"}` |

Semantica: **uno `start` senza `end` = run morta a metà** — è il segnale
diagnostico che il ledger esiste per produrre (prima una run fallita non
lasciava alcuna traccia). `esito: parziale` = run completata con degradazioni
(fonte saltata, invio digest fallito — exit 4 di `send_digest.py` —,
telemetria non scritta), dettagliate in `note`. Il ledger non ruota
mensilmente: due righe per run pesano nulla e la storia intera è utile;
resta comunque strato operativo, soggetto alle stesse regole di retention (vedi sopra).

Letto da: `job-alert-tuner` (frequenza reale delle run, run fallite/parziali)
e da chiunque debba diagnosticare "la routine sta girando?" dal solo repo.
Righe malformate: stesso trattamento dei mensili (scarta, conta, riporta).

## Note sull'implementazione nella routine

- Log da scrivere nello stesso turno del commit di `state.json` (punto 8 della routine), per non avere run loggate a metà.
- Rotazione mensile: la routine scrive nel file del mese corrente (`source-log/<anno>-<mese>.jsonl`), creandolo se non esiste.
- Se la scrittura del source-log fallisce ma il resto della run è andato: NON bloccare digest/stato — il log è telemetria, la pipeline è il prodotto. Segnalare l'anomalia nel digest.
- `scartato_dedup` è attribuibile per ricerca solo se il dedup avviene DOPO la raccolta per-ricerca (com'è oggi al punto 3 della routine): la routine sa quale ricerca/intento ha riportato l'ID già visto.
- **`run_id` storici del 2026-07-07:** le 4 run di quel giorno hanno scritto `run_id` in ora locale (CEST) col suffisso `Z` — per questo nel mensile la run "09:00:00Z" precede la run "08:28:00Z" in ordine di append. Si lasciano invariati (danno noto e circoscritto); dal 2026-07-08 vale la regola UTC reale della tabella sopra.
- **Formati storici di `annuncio_id` (migrazione 2026-07-08):** le prime run del 2026-07-07 hanno scritto `annuncio_id` in due formati diversi — il token `jk` (`indeed:<jk>`, prima run) e poi un surrogato `azienda:location:data` (dal commit `fa578bb`, senza titolo). Entrambi sono stati migrati al formato canonico definitivo (`<fonte>:<slug(azienda)>:<slug(titolo)>:<slug(location)>`) in un unico commit. Le metriche di overlap/novità di run precedenti il 2026-07-08 vanno lette tenendo conto che il join cross-run è stato reso possibile solo dopo questa migrazione (i due formati non si joinavano tra loro).
