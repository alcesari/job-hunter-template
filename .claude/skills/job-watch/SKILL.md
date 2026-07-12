---
name: job-watch
description: >-
  La routine batch del sistema Job Hunter: raccoglie le offerte per ogni
  intento di ricerca attivo, deduplica, filtra, valuta il fit, pre-genera i
  materiali per i fit migliori in staging e consegna un digest. Gira come
  sessione Claude Code schedulata (Desktop scheduled task o routine cloud),
  ma è invocabile anche a mano ("fai partire la ricerca ora", "esegui la
  routine", "cerca nuove offerte adesso"). Scrive SOLO lo strato operativo
  (source-log/, state.json, staging/, digests/, PIPELINE.md) e legge i
  profili e applications/. NON invia candidature, NON scrive profili o
  valutazioni definitive. Usa questa skill per l'esecuzione periodica del
  sourcing, non per valutare una singola JD incollata (→ role-fit) né per
  modificare i criteri di ricerca (→ job-search-profile).
---

# job-watch

La routine di sourcing del progetto Job Hunter (Modulo 1.3). È il "motore"
autonomo: gira a intervalli, trasforma alert e ricerche in un **digest
valutato** e in un'area di **staging** pronta per la revisione umana. Non è il
prodotto: il prodotto è la pipeline che valuti tu in chat. La routine è
telemetria + pre-lavoro.

**Regola di proprietà (D5) — la più importante di questa skill**: la routine
scrive SOLO lo strato operativo append-only — `source-log/`, `state.json`,
`staging/`, `digests/`, `PIPELINE.md`. NON scrive `master-profile.yaml`,
`searches/`, `role-fit/` né `applications/` (questi li scrivono le sessioni
interattive). `applications/` la routine lo **legge** soltanto, per le
scadenze del digest. Le valutazioni che la routine produce vivono in
`staging/`, non in `role-fit/`: diventano `role-fit/` solo se la revisione
umana promuove la candidatura (allora è una sessione interattiva a scriverle).

## Dove gira e come è schedulata

- **Sessione Claude Code** (Desktop o cloud): serve accesso git in scrittura.
  Da chat claude.ai pura non può girare (connettore read-only).
- **Scheduling v1 (default dichiarato)**: Desktop scheduled task di Claude
  Code. **Upgrade**: routine cloud, con la disciplina push qui sotto.
- **Cadenza raccomandata a regime (F16)**: 1 run/giorno, dichiarata in
  `routine-config.yaml → cadenza_dichiarata` (radice del repo, F5). È una
  raccomandazione da confermare con `job-alert-tuner` dopo un periodo di
  osservazione reale (frequenza effettiva delle run via `runs.jsonl`, rumore
  prodotto) — non un cambiamento operativo imposto qui.
- **Disciplina push**: la routine cloud vede solo lo stato committato *e
  pushato*. All'inizio di ogni run fai `git pull` (da `main`); alla fine committa
  e pusha. Una modifica ai profili fatta in chat ma non pushata è invisibile alla run.
- **Il commit deve ATTERRARE SU `main`** (non su un branch orfano). `state.json`
  è il dedup: se la telemetria di una run resta su un branch non mergiato, il giro
  successivo riparte da uno stato vecchio e ri-propone le stesse offerte. Lo strato
  operativo è append-only e non richiede revisione umana, quindi il percorso a zero
  conferme è il **push diretto su `main`** (coperto dall'allowlist — vedi sezione
  autonomia sotto). PR+auto-merge NON è il percorso di default: richiederebbe `gh`,
  che non è (volutamente) allowlistato. Usalo solo se l'ambiente cloud ti impone di
  lavorare su un branch di servizio e non concede push diretto su `main`; in quel
  caso abilita l'auto-merge della PR nella config della routine (l'alternativa,
  lasciare il branch non mergiato, romperebbe il dedup del giro successivo).

## Autonomia della run (zero conferme umane) e enforcement D5

La routine deve girare **dall'inizio alla fine senza un solo prompt di
conferma**, in sessione fresca (l'ambiente cloud non eredita alcun
`settings.local.json`). Due pezzi la garantiscono, entrambi committati:

1. **Allowlist in `.claude/settings.json`**: copre ESATTAMENTE le azioni di
   questo contratto — git (`pull`/`add`/`commit`/`push` + `status`/`diff`/`log`,
   più `git rm` scoped ai soli path operativi per la retention), `date`,
   `python[3] scripts/send_digest.py`, i tool MCP Gmail
   (`list_labels`, `search_threads`, `get_thread`, `get_message`,
   `create_draft`) e Indeed (`search_jobs`, `get_job_details`) — questi ultimi
   hanno **ID legati all'account**: dove presenti in allowlist la routine li
   invoca senza conferma, in un clone fresco (es. dal template) vanno approvati
   quando colleghi i connettori, non sono committati — e le scritture
   Edit/Write sui soli path dello strato operativo (`source-log/**`,
   `staging/**`, `digests/**`, `state.json`, `PIPELINE.md`). **Disciplina
   conseguente**: per i file usa SEMPRE i tool Write/Edit (mai redirezioni
   shell tipo `echo >>`, che non matchano l'allowlist); per le eliminazioni
   della retention usa `git rm` nelle forme scoped (`git rm digests/…`,
   `git rm source-log/…`, `git rm -r staging/…`), MAI `rm`; invoca i comandi
   nella forma esatta documentata qui, dalla radice del repo. Il flusso di
   pubblicazione a zero conferme è il **push diretto su `main`**: il flusso
   alternativo PR+auto-merge richiederebbe `gh`, che non è (volutamente)
   allowlistato.
   **Career page (Fase 1, in attesa del socket test cloud)**: la riga
   `python[3] scripts/fetch_careers.py` NON è ancora in allowlist —
   deliberatamente. Il socket test HTTPS è verificato solo su Desktop; finché
   non passa anche in cloud (procedura in `.docs/analisi/analisi-career-pages-…`,
   "Stato di prontezza", vincolo 1), il canale career_page resta **Desktop-only**
   e in cloud la routine gira senza fetch career page (nessuna conferma richiesta
   perché lo script non viene invocato lì). Quando il test cloud passa, aggiungi
   `Bash(python scripts/fetch_careers.py *)` e `Bash(python3 scripts/fetch_careers.py *)`
   all'allowlist (stesso pattern di `send_digest.py`).
2. **Hook di enforcement `.claude/hooks/protect-files.sh`** (PreToolUse su
   Edit|Write): nelle sessioni della routine **blocca meccanicamente** ogni
   scrittura su `master-profile.yaml`, `searches/`, `role-fit/`,
   `applications/` (proprietà interattiva, D5). Si attiva con la variabile
   d'ambiente **`JOB_HUNTER_ROUTINE=1`**, che la config dell'ambiente cloud
   della routine DEVE impostare (è il contratto che distingue
   sessione-routine da sessione-interattiva). Trade-off dichiarato: i permessi
   committati valgono per qualunque sessione sul repo; l'hook è la rete di
   sicurezza che impedisce alla routine di scrivere fuori dal suo perimetro —
   e l'allowlist, non concedendo Edit/Write sui path di proprietà
   interattiva, fa da seconda barriera anche se la variabile mancasse.

## Precondizioni

- Repo clonato, git funzionante, sessione Claude Code.
- **`JOB_HUNTER_ROUTINE=1`** nell'ambiente (vedi sezione sopra).
- **Gmail** (`tool_search` "Gmail") — per leggere gli alert e inviare il digest.
- **Indeed** (`tool_search` "Indeed jobs") — per la ricerca diretta.
- Se una fonte manca: NON fallire la run — salta quella fonte, procedi con le
  altre, e segnala il buco nel digest (degradazione elegante, mai pipeline che
  si bloccano).
- Almeno un intento `attivo` in `searches/`: se non ce n'è, niente da fare —
  scrivi un digest minimo che lo dice e fermati.

## Fonti dati (modulo sostituibile — unico punto di design aperto)

v1 usa i due canali legittimi disponibili oggi (le piattaforme spingono i dati, zero rischio ToS):
1. **Indeed via connettore** — ricerca diretta per ruolo × location dell'intento.
2. **Alert email via Gmail** — LinkedIn (`jobs-noreply@linkedin.com`,
   `jobalerts-noreply@linkedin.com`) e Indeed (`alert@indeed.com`,
   `noreply@indeed.com`) nella finestra `finestra_temporale_ore`. Alcuni alert
   LinkedIn contengono più annunci per email e senza descrizione: comportamento
   noto, gestito qui.
   **Strategia di query Gmail**: cerca per mittente + `newer_than:<finestra>`.
   La ricerca Gmail include di default anche la posta ARCHIVIATA, quindi
   l'utente può filtrare/archiviare gli alert per tenere pulita la Inbox senza
   renderli invisibili alla routine. Se `routine-config.yaml` (radice del
   repo, F5) dichiara una **`gmail_label`**, preferisci restringere la query a
   quella (`label:<id>` — risolvi il nome → ID con `list_labels`), con
   fallback sui mittenti se il file manca o il campo è vuoto. Non restringere
   mai la query alla sola Inbox (`in:inbox` escluderebbe gli archiviati).
3. **Career page aziendali** — per ogni azienda in `searches/companies.yaml`
   con `attiva: true`, `access_tier: A|B` e `robots_ok: si` (STRETTO: `no` e
   `da_verificare` sono equivalenti, entrambi NON interrogati — vedi contratto
   companies.yaml): una GET/POST del feed/endpoint registrato nell'`adapter`
   (contratto in `agent-config/references/search-profile.schema.yaml`,
   sezione companies). Prima di interrogare, verifica la completezza dei campi
   obbligatori per il `kind` dichiarato e la coerenza `access_tier`↔`kind`:
   voce incompleta o incoerente → scarta, segnala nel digest ("voce
   companies.yaml incompleta/incoerente per `<id>`"), non fallire l'intera run.
   Fascia C o `robots_ok` non `si`: NON interrogare — conta le aziende saltate
   e segnalale nel digest ("N aziende richiedono check manuale/verifica").
   Il fetch strutturato lo fa `python scripts/fetch_careers.py` (stdlib
   `urllib`, exit code semantici non-fatali come `send_digest.py`): la routine
   passa `searches/companies.yaml` e riceve JSON normalizzato su stdout, mai
   fa fallire la run per un feed rotto.

   **Distinzione errore vs zero-risultati** (stato in `state.json.
   career_page_health.<id>`, non in companies.yaml — è telemetria, non
   criterio di ricerca): errore HTTP/timeout/JSON non parsabile →
   `consecutive_failures += 1`, nota nel digest solo se ≥ 3 consecutivi;
   successo con lista vuota → NON è un errore, confronta con
   `last_nonzero_count`: se l'azienda aveva posizioni ed è a zero da ≥ 2 run
   consecutivi, nota soft nel digest ("possibile 0 legittimo o adapter da
   ri-verificare"); sotto soglia in entrambi i casi, registra silenziosamente
   e riprova al run successivo. Successo con risultati → azzera i contatori
   e aggiorna `last_nonzero_count`. Le soglie (3, 2) sono default di partenza,
   regolabili in Fase 2 sul rumore osservato.

   **Perimetro d'ambiente (stato Fase 1)**: il socket test HTTPS è ✅ **GO su
   Desktop** (fetch reali verso Greenhouse e gogenerali) ma ⏳ **non ancora
   eseguito in cloud** (`JOB_HUNTER_ROUTINE=1`), dove SMTP è bloccato e HTTPS
   *potrebbe* esserlo. Finché il test cloud non passa, il canale career_page è
   **Desktop-only** e la sua riga di allowlist per `scripts/fetch_careers.py`
   NON è ancora in `.claude/settings.json` (vedi "Autonomia della run"): la
   routine cloud continua con aggregatori + canale di candidatura diretta (§3
   dell'analisi), il fetch career page gira solo nelle run Desktop.

Il modulo-fonte è deliberatamente isolato: aggiungere aggregatori legittimi
(Adzuna, Jooble, career-site Greenhouse/Lever) o — accettandone i trade-off —
scraper terzi, è un cambio confinato a questo passo, che non tocca contratti a
valle. NON automatizzare azioni su LinkedIn/Indeed dietro login (ToS): le
offerte entrano solo via connettore o via email che le piattaforme già spingono.

## Flusso della run

### 1. Setup
`git pull`. Leggi `master-profile.yaml` e tutti i `searches/<id>.yaml` con
`stato: attivo` (più `searches/defaults.yaml`; applica gli `override` di ogni
intento). Leggi `state.json` (gli `annuncio_id` già visti). Leggi
`routine-config.yaml` (radice del repo, F5) per `gmail_label` — se il file
manca, procedi col fallback sui mittenti (vedi "Fonti dati"), non è un motivo
per fermare la run. Determina la finestra temporale (max dei
`finestra_temporale_ore` degli intenti attivi).
Fissa il `run_id` della run: è SEMPRE l'istante **UTC reale** di inizio run
(`date -u` o equivalente), MAI l'orario schedulato né l'ora locale col suffisso
`Z` — un `run_id` locale spacciato per UTC rompe ordinamento e trend per-run
nel source-log (le 4 run del 2026-07-07 hanno questo difetto: noto, si lasciano
invariate; vedi la nota storica nel contratto del source-log).

**Ledger delle run (osservabilità — primo atto dopo il pull)**: appendi a
`source-log/runs.jsonl` la riga di start
(`{"run_id":"<run_id>","fase":"start"}`) e **committa+pusha SUBITO, da sola**,
prima di toccare qualsiasi fonte. È l'unico modo per cui una run morta a metà
lasci una traccia diagnosticabile: uno `start` senza `end` corrispondente =
run fallita, visibile dal solo repo. In coda alla run (passo 8, dopo il digest)
appendi la riga di end con l'esito
(`{"run_id":"<run_id>","fase":"end","esito":"ok|parziale|fallita","note":"<solo se non ok>"}`
— `parziale` = una o più degradazioni: fonte saltata, invio digest fallito,
telemetria non scritta; `fallita` la scrivi solo se sei ancora vivo per
scriverla, altrimenti la dice lo start orfano). Contratto completo del ledger
nel contratto del source-log.

### 2. Raccolta per intento e per ricerca
Per ogni intento attivo, per ogni fonte attiva, per ogni combinazione
ruolo × location: raccogli gli annunci. Ogni "ricerca" ha un `ricerca_id`
stabile prefissato dall'intento (vedi `job-alert-tuner/references/source-log-schema.md`).
Tieni traccia di **quale ricerca** ha portato ogni annuncio: serve al passo 3.

### 3. Dedup e novità (dopo la raccolta per-ricerca, non prima)
Confronta gli `annuncio_id` raccolti con `state.json`. Il dedup avviene DOPO la
raccolta per-ricerca, così ogni occorrenza è attribuibile alla sua ricerca:
lo stesso annuncio portato da 3 ricerche = 3 righe di log (una `incluso_*`, le
altre `scartato_dedup`). È ciò che rende calcolabile l'overlap in `job-alert-tuner`.

**Chiave canonica dell'`annuncio_id`** (formato DEFINITIVO — non deduplicare
mai sull'URL grezzo, che porta parametri di tracking variabili):

```
<fonte>:<slug(azienda)>:<slug(titolo)>:<slug(location)>
```

dove `slug(s)` = minuscolo → rimozione accenti (NFKD → ASCII) → ogni sequenza
di caratteri non `[a-z0-9]` diventa un singolo `-` → trim dei `-` iniziali/finali.
Esempio: `indeed:acme:java-backend-developer:lombardia`. La regola di slug va
applicata **identica a ogni run**, altrimenti le run nuove non si joinano con le
precedenti nel source-log (è ciò che rompe overlap/novità in `job-alert-tuner`).

**Perché non il token `jk` / l'ID URL della piattaforma:** verificato
empiricamente (commit `fa578bb`, 10 offerte ricomparse) che il token
`to.indeed.com/<id>` restituito dal connettore **non è stabile** tra chiamate
per lo stesso annuncio — quindi inutilizzabile come chiave di dedup. Si usa
sempre la chiave surrogata `azienda+titolo+location`.

**Limite noto (residuo), da tenere presente:** il titolo può variare
leggermente tra run (es. un suffisso `... in presenza` o `(Healthcare
Platform)` aggiunto da Indeed): in quei casi lo stesso annuncio genera due
chiavi e può risultare "nuovo" una seconda volta. È il trade-off della chiave
surrogata; la data di pubblicazione (usata in un formato storico intermedio,
vedi nota sotto) era peggiore perché faceva **collidere** annunci diversi della
stessa azienda/zona nello stesso giorno. In dubbio, meglio due chiavi che una
collisione silenziosa.

**Nota storica (migrazione):** prima del 2026-07-08 alcune run hanno usato
formati diversi per `annuncio_id` — il token `jk` (prima run) e poi un
surrogato `azienda:location:data` (commit `fa578bb`, senza titolo, collision-prone).
Entrambi sono stati migrati al formato definitivo qui sopra in un unico commit
(`state.json`, `source-log/2026-07.jsonl`, `staging/*/staging.yaml`); conteggio
degli annunci univoci in `state.json` invariato (22→22).

**Novità vs freschezza** (rifinitura): la novità di un'offerta è data da
`state.json` (mai vista prima), NON da quando è stata pubblicata. La finestra
`finestra_temporale_ore` (48h) vale per gli **alert email** (che arrivano nuovi
e possono ripetersi), non per la **ricerca diretta**, dove un ruolo aperto
postato settimane fa è ancora valido: filtrarlo a 48h taglierebbe candidati
buoni. Per il direct-search, usa `state.json` per la novità e tratta l'età solo
come segnale soft (es. >60 giorni = deprioritizza/segnala, non scarta).

### 4. Filtri a valle per intento
Sulle offerte non-dedup, applica i filtri che gli alert non possono applicare,
usando i valori effettivi dell'intento (defaults + override): esclusioni titoli
(`esito: scartato_livello`), tipo contratto, lingue dell'annuncio
(`esito: scartato_lingua`). `eccezione_se_ambiguo: true` → non scartare, segnala.

**Filtro location — SOLO per `fonte: career_page`.** Gli altri canali hanno la
location già nella query a monte (Indeed cerca per ruolo × location, gli alert
sono configurati per location): lì NON si applica questo filtro. Il canale
career_page invece fetcha **per-azienda**, non per-location, quindi riceve tutte
le posizioni globali dell'azienda (verificato: SimCorp/Bending Spoons
restituiscono Manila, Copenhagen, London, Hong Kong… mischiate alle italiane) —
serve un filtro esplicito. Confronta la location normalizzata dell'offerta con
le `location_target` dell'intento usando la **stessa tabella di alias IT/EU**
del matcher (`references/entity-resolution.md`, sezione "Tabella alias
location") — non inventarne una seconda. Regole:
- un **token remote** (`remote`/`remoto`/`smart-working`/…) è compatibile con
  qualsiasi `location_target` che dichiari `accetta_remoto: true`;
- una città è compatibile se uguale a un target o inclusa in una sua
  regione/paese secondo la tabella;
- se la location dell'offerta **elenca più sedi** (es. "Milan (Italy), Madrid
  (Spain), Warsaw (Poland)"), basta che **UNA** sia compatibile per tenerla.

Offerta la cui location non è compatibile con NESSUNA `location_target`
dell'intento (e non è un token remote accettato) → `esito: scartato_location`
(nuovo esito, vedi `job-alert-tuner/references/source-log-schema.md`).
**Location assente/non estratta** (es. una posizione html_list il cui detail
non espone la sede — Arkemis in Fase 1 — o un adapter senza campo location):
**NON scartare** — l'assenza del dato non è prova di fuori-scope; l'offerta
prosegue e sarà la valutazione di fit a pesarla (stessa conservatività del
matcher). Non applicare MAI questo filtro a indeed/linkedin_alert/indeed_alert.

### 5. Valutazione del fit (output in staging, MAI in role-fit/)
Sulle sopravvissute, fino a `max_annunci_per_esecuzione`, valuta il fit contro
il `master-profile` con lo **stile e lo schema di `role-fit`** (bullet pesati,
score ordinale `forte|buono|parziale|debole`, niente numeri). L'output va in
`staging/`, non in `role-fit/` (regola di proprietà): sarà la promozione umana a
persisterlo in `role-fit/`. Le offerte oltre il cap: log `non_lavorato_cap`.

### 5-bis. Fusione cross-fonte (entity resolution, solo intra-run)
Sulle offerte sopravvissute, riconosci quelle che sono la STESSA posizione
vista da fonti diverse. **Contratto operativo completo** (matrice di decisione,
soglie `token_set_ratio` 0.90/0.75, lista suffissi societari, suffissi titolo,
tabella alias location, merge policy) in `references/entity-resolution.md`: gate
rigido sull'azienda, location compatibile, similarità titolo. **Location assente
(null) su un lato → mai `merge`** (al più `suspect`, di norma `distinct`):
l'assenza di dato non è prova di identità — stessa conservatività del gate.
Esiti: `merge` (un solo record staging con `sources[]` multiplo e merge
per-campo), `suspect` (record separati + `possible_duplicate_of`), `distinct`.
La fusione avviene DOPO il source-log (che resta una riga per fonte — è ciò che
rende misurabile il cross-source overlap nel tuner) e non tocca MAI
state.json/annuncio_id.

### 6. Gate + pre-generazione materiali
Per ogni offerta valutata crea/aggiorna `staging/<id>/` col contratto in
`references/staging-schema.md` (`staging.yaml` + `fit.yaml`). **Gate**: solo per
i fit `forte` e `buono` **che non siano palesemente sotto il floor RAL**
dell'aspettativa (rifinitura) pre-genera i materiali (CV + cover + DM) riusando
la pipeline di `cv-tailoring`, li scrive in `staging/<id>/materials/` e produce
il `diff-report.md` master↔generato (D3). Un fit `buono` con RAL dichiarata
chiaramente sotto `retribuzione.aspettativa.valore_min` resta in staging come
sola valutazione con nota (materiali on-demand): pre-generare per un ruolo che
l'utente probabilmente non perseguirà è proprio lo spreco che il gate evita. I
fit `parziale`/`debole` restano sola valutazione, senza materiali, finché non li
chiedi tu.

### 7. Telemetria (stesso commit)
Appendi TUTTE le righe osservate (incluse scarti e dedup) a
`source-log/<anno>-<mese>.jsonl` (crea il file del mese se non esiste). Aggiorna
`state.json` con i nuovi `annuncio_id`. Committa telemetria + staging insieme:
nel repo unico la coerenza run↔log è quasi-atomica. Se la scrittura del
source-log fallisce ma il resto è andato: non bloccare digest/stato, segnala
l'anomalia nel digest (il log è telemetria, la pipeline è il prodotto).
Le righe da fonte career_page portano anche `azienda_fonte` (contratto
source-log). La fusione NON riduce le righe: un annuncio per fonte, sempre.

### 8. Digest (contratto in references/digest-schema.md)
Componi il digest (vedi contratto): offerte nuove valutate, cosa è in staging in
attesa di revisione, **scadenze** da `applications/*/application.yaml`
(`next_action.due`), **sintesi pipeline** con rigenerazione di `PIPELINE.md`, e
le anomalie della run. Scrivi `digests/<YYYY-MM-DD>.md`, rigenera `PIPELINE.md`,
e **consegna il digest via Gmail** all'utente. Commit + push.
**Ownership di `PIPELINE.md`**: è un artefatto rigenerabile **co-scritto** —
lo rigenera la routine qui, e lo rigenera anche `application-tracker` su
richiesta in sessione interattiva (eccezione dichiarata alla regola di
proprietà D5, innocua perché il file non è mai fonte di verità). Chi lo tocca
lo rigenera SEMPRE integralmente da `applications/`, mai con merge manuale;
in caso di conflitto git vince la rigenerazione più recente.
**Consegna Gmail (rifinitura, esito verificato)**: il tentativo di invio reale è
`python scripts/send_digest.py digests/<YYYY-MM-DD>.md` — SMTP usando
`GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` (app-password Gmail, se presenti come
**secret dell'ambiente** della routine, mai nel repo). **Nella routine cloud
questo fallisce strutturalmente** (`OSError(97, 'Address family not supported by
protocol')`, verificato in run reale del 2026-07-08): il sandbox cloud non
espone socket di rete grezzi, solo i canali già strumentati (connettori MCP,
git). Non è un bug da rincorrere: è un confine della sandbox. **L'esito atteso e
normale per la routine cloud è la bozza**, non l'invio reale — trattalo come il
comportamento di produzione, non come un fallback raro. Lo script resta un
percorso valido solo per un'eventuale routine **Desktop locale** (macchina
reale, networking non sandboxato). Lo script ha **exit code semantici, tutti
non-fatali** — la routine non fallisce MAI per il digest: `0` = inviato
(realisticamente solo in ambiente locale); `3` = saltato (credenziali/file
assenti — es. dopo averle rimosse dai secret perché inutili in cloud) →
ricadi sulla bozza via connettore `create_draft`; `4` = invio fallito (es.
l'errore di rete sopra) → ricadi sulla bozza E segnala l'anomalia nella
sezione anomalie del digest. In ogni caso la copia autorevole è il file
`digests/<YYYY-MM-DD>.md` nel repo — Gmail (bozza) è solo un canale di
notifica aggiuntivo, non l'unico: valuta anche una notifica push nativa se
l'ambiente la espone (osservato funzionante nella run del 2026-07-08).
**Chiusura del ledger**: appendi a `source-log/runs.jsonl` la riga di end
(`fase:"end"`, `esito` `ok`/`parziale` + `note` sulle degradazioni) e includila
nel commit finale. Il digest dichiara la **prossima run attesa** (vedi
contratto): è ciò che rende un silenzio prolungato un segnale misurabile e non
un dubbio.

### 9. Retention (potatura dello strato operativo — parte del commit finale)

Lo strato operativo è tuo (D5): sei tu a potarlo, a ogni run, con queste soglie
dichiarate (la "verità" non si perde mai: le candidature vive sono in
`applications/`, e la storia completa resta comunque nella storia git):

- **`state.json.seen`**: elimina le voci con `first_seen` più vecchio di
  **6 mesi**. Trade-off dichiarato: un annuncio ancora aperto oltre quella
  soglia può ricomparire una volta come "nuovo" — caso identico al title-drift
  già messo a verbale sopra, il sistema lo riassorbe da solo.
- **`digests/`**: elimina i file più vecchi di **3 mesi** (restano nella
  storia git; la copia operativa serve solo per consultazione recente).
- **`staging/`**: elimina le voci con `status: discarded` più vecchie di
  **3 mesi** (l'`annuncio_id` resta in `state.json` per la sua finestra di
  6 mesi, quindi non rientrano). Le `pending` NON si toccano mai: sono lavoro
  in attesa di revisione umana.
- **`source-log/*.jsonl` mensili**: elimina i file più vecchi di **12 mesi**
  (finestra ampia: sono la materia prima di `job-alert-tuner`).
  `runs.jsonl` non si pota (due righe per run, peso nullo, storia utile).

Le eliminazioni si fanno con `git rm` nelle forme scoped dell'allowlist
(`git rm digests/…`, `git rm source-log/…`, `git rm -r staging/…`), mai `rm`:
tocca solo file tracciati e resta recuperabile dalla storia. Se una potatura
tocca file, includila nel commit finale della run con il conteggio nel digest
(sezione anomalie/note: "retention: N voci seen, M file").

## Note di robustezza

- **Degradazione elegante ovunque**: fonte irraggiungibile, alert non parsabile,
  connettore scaduto → salta e segnala nel digest, non far fallire la run.
- **Idempotenza sul dedup**: `state.json` garantisce che un'offerta già vista non
  rientri; una run ripetuta non duplica staging né log per lo stesso annuncio.
- **Volumi**: `max_annunci_per_esecuzione` è il cap dichiarato; se viene colpito
  spesso, è un segnale per `parametri_esecuzione` (lo dice `job-alert-tuner`).
- **Invio email**: il digest va all'utente stesso — inviarlo è ok (non è una
  candidatura). Tutto ciò che è diretto a un datore di lavoro resta bozza (D3):
  la routine non invia MAI candidature né follow-up.

## Cosa NON fare

- Non scrivere `master-profile.yaml`, `searches/`, `role-fit/`, `applications/`:
  la routine tocca solo lo strato operativo (regola di proprietà D5).
- Non promuovere candidature: la promozione da staging è un atto umano
  (`application-tracker`), mai automatico.
- Non inviare candidature o follow-up (solo il digest all'utente).
- Non automatizzare azioni dietro login su LinkedIn/Indeed (ToS).
- Non far fallire l'intera run per una fonte rotta: degrada e segnala.
- Non pre-generare materiali sotto la soglia del gate (fit `parziale`/`debole`).
