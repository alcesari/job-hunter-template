# staging — contratto dell'area di pre-lavoro (D4)

L'area di **staging** è la posta in arrivo del batch: dove la routine `job-watch`
deposita le offerte valutate (e, per i fit migliori, i materiali pre-generati)
in attesa della **revisione umana**. Non è mai fonte di verità sulle
candidature: è un'anticamera. L'unica uscita "positiva" è la **promozione** in
`applications/` (un atto umano, via `application-tracker`); l'alternativa è lo
scarto.

## Chi scrive, chi legge

- **Scrive**: `job-watch` (la routine) — è strato operativo, regola di proprietà D5.
- **Legge / consuma**: la revisione umana in sessione interattiva. Approvazione →
  `application-tracker` promuove in `applications/`; scarto → si archivia.
- La routine può **riscrivere** una voce staging esistente a run successive (es.
  rivalutazione, o fusione cross-run di una fonte nuova trovata su un'altra
  piattaforma per la stessa posizione — vedi `references/entity-resolution.md`),
  MAI una già promossa (una volta in `applications/`, esce da qui).

## Struttura

```text
staging/
  <candidate-id>/            # stesso schema id di applications: <azienda-slug>-<ruolo-slug>-<YYYY-MM>
    staging.yaml             # snapshot: stato + meta dell'offerta in anticamera
    fit.yaml                 # valutazione, schema role-fit-output (score/match/gaps/considerazioni)
    materials/               # SOLO se il gate è passato (fit forte/buono)
      cv.md  cover-letter.md  recruiter-dm.md
      diff-report.md         # master↔generato (D3) — obbligatorio se i materiali sono pre-generati
      cv.pdf                 # OPZIONALE in staging (vedi sotto): garantito alla promozione/su richiesta
```

L'`id` usa lo stesso schema di `applications/` (data inclusa), così la
promozione è un rename/spostamento senza rimappare identità.

### `staging.yaml` (snapshot)

- `id` — coincide col nome cartella.
- `status: pending | approved | discarded | expired` — `pending` alla creazione;
  la revisione umana lo porta a `approved` (subito prima della promozione) o
  `discarded`. La routine crea solo `pending`; l'unico altro stato che può
  scrivere è `expired`.
  **`discarded` vs `expired` — la distinzione che tiene D3 intatta**:
  `discarded` è un **giudizio umano** ("non mi interessa"); `expired` è un
  **fatto osservabile** ("l'annuncio non esiste più"), accertato dalla routine
  al passo 4-bis con `scripts/check_liveness.py`. La routine non decide mai al
  posto dell'utente: constata. Un `expired` si assegna SOLO su evidenza positiva
  di chiusura (404/410, redirect alla lista, marker esplicito) — mai su timeout,
  403, 5xx o dominio non raggiungibile, che restano `pending`.
  Una voce `expired` che l'utente ritiene ancora valida può essere riportata a
  `pending` a mano: `expired` non è irreversibile e non cancella nulla.
- `company`, `role`, `location`.
- `source: indeed | linkedin_alert | indeed_alert | career_page | manuale` —
  proiezione di `sources[0].fonte` (retro-compatibilità: i consumatori esistenti
  continuano a leggere questo scalare; enum condiviso con `role-fit` e
  `applications/`, `manuale` mai prodotto in staging). Copiato 1:1 alla
  promozione, mai rimappato.
- `position_id` — identità della POSIZIONE reale (non dell'annuncio-su-fonte):
  `<slug(azienda)>:<slug(titolo)>:<slug(location)>` = l'`annuncio_id` senza il
  prefisso fonte. Raggruppa 1..N fonti quando l'entity resolution fonde, sia
  nella stessa run sia a run successive (fusione cross-run, vedi
  `references/entity-resolution.md`): `sources[]` può quindi crescere anche
  dopo la creazione della voce, non solo alla creazione.
- `sources[]` — lista delle fonti che riportano questa posizione. Ogni voce:
  `fonte` (stesso enum di `source`), `annuncio_id` (quello per-fonte di
  state.json/source-log — MAI perso), `jd` (URL annuncio), `apply_url` (URL di
  candidatura su quella fonte), `fetched_at` (ISO 8601); per `career_page`
  anche `company_slug` (id in companies.yaml) e `native_id` (id nativo della
  piattaforma, se esposto — es. il contestId di gogenerali). Caso mono-fonte:
  un solo elemento.
- `primary_source` — la fonte da cui viene il corpo usato per la valutazione
  (merge policy: descrizione più ricca vince; euristica career_page > indeed >
  alert).
- `preferred_apply_channel` — il canale di candidatura consigliato
  (career_page > sito aziendale > aggregatore). Ereditato da
  application-tracker alla promozione; cv-tailoring prepara i materiali per
  QUEL canale. La candidatura resta un atto umano (D3).
- `possible_duplicate_of` — valorizzato (con un `position_id`) solo se il
  matcher di fusione ha esito `suspect`: segnala alla revisione umana un
  possibile duplicato NON fuso automaticamente.
- `intent_id` — l'intento che l'ha trovata (viaggia fino ad `applications/`).
- `annuncio_id` — id/URL canonico (lo stesso di `state.json` e del source-log).
- `links` — `jd` (URL annuncio).
- `score: forte | buono | parziale | debole` — copia dallo `fit.yaml`, per
  ordinare/filtrare senza aprire ogni file (comodità, non seconda fonte).
- `materials_generated: bool` — true se il gate è passato e `materials/` esiste.
- `materials_flagged: bool` — **assente o `false`** = il gate di veridicità
  (`scripts/verify_cv_facts.py`, passo 6 di `job-watch/SKILL.md`) è passato su
  tutti gli artefatti. **`true`** = almeno un artefatto contiene claim numerici
  non tracciabili al `master-profile` o frasi vietate: i materiali ci sono ma
  **non sono verificati**, e la revisione umana deve guardarli prima di usarli.
  Lo valorizza solo la routine; una sessione interattiva che corregge i
  materiali lo rimette a `false` dopo un nuovo run verde del gate.
  Ha senso solo se `materials_generated: true`.
- `run_id` — la run che l'ha prodotta (ISO 8601), per tracciabilità.

### `fit.yaml` (valutazione)

Stesso schema di `role-fit/references/role-fit-output.schema.yaml` (`meta`,
`valutazione`, `esito`, `note`). `meta.intento` = `intent_id`. `esito` resta
`valutato` (la routine non decide). Alla promozione, questo file è ciò che una
sessione interattiva persiste in `role-fit/` — così la valutazione del batch non
va persa e non viene rifatta.

### `materials/` (incluso `diff-report.md`)

Presenti solo per i fit `forte`/`buono` (gate). Prodotti riusando la pipeline di
`cv-tailoring` (sorgenti `.md`). Tutto vive DENTRO `materials/`, incluso il
diff-report: è la posizione reale delle voci esistenti e la stessa usata da
`cv-tailoring` nel percorso interattivo (`applications/<id>/materials/`), così
la promozione sposta la cartella senza rimappare nulla.

- Il `diff-report.md` è il confronto master↔generato richiesto da D3: elenca
  ogni modifica classificata (riordino / riformulazione / omissione /
  ⚠ possibile aggiunta di contenuto), così la revisione è un controllo mirato
  di 2 minuti, non una rilettura integrale. **Obbligatorio** quando i materiali
  sono pre-generati.
- Il **PDF è opzionale in staging**: l'ambiente della routine cloud non
  garantisce un motore di render affidabile (weasyprint/reportlab), e
  pre-renderizzare per offerte non ancora approvate è spreco. Il PDF è
  **garantito alla promozione** (o su richiesta in chat): lo produce
  `cv-tailoring` in sessione interattiva, dove la pipeline di render è
  disponibile e i contenuti sono confermati. `materials_generated: true` NON
  implica quindi che il PDF esista — implica sorgenti `.md` + diff-report.

## Ciclo di vita di una voce

1. **Creazione** (routine, passo 6): `status: pending`, `fit.yaml`, e — se il gate
   passa — `materials/` (sorgenti `.md` + `diff-report.md`; PDF opzionale).
2. **Revisione** (umana, in chat): l'utente vede la valutazione e, se generati, il
   diff. Decide.
3a. **Approvazione → promozione**: `application-tracker` crea `applications/<id>/`,
   archivia i `materials/` in `applications/<id>/materials/` e **congela la JD**
   in `applications/<id>/jd.md` (l'annuncio online sparirà: la promozione è
   l'ultimo momento utile per catturarne il testo), persiste `fit.yaml`
   in `role-fit/`, imposta `links.role_fit` e `intent_id`. L'ordine è
   **copia → verifica → rimuovi**: la voce staging si rimuove (o si marca
   `approved` e si archivia) solo dopo che l'archiviazione è confermata, così un
   fallimento a metà non perde nulla. Contratto completo in
   `application-tracker/SKILL.md`, sezione «Archiviazione alla promozione».
3b. **Scarto**: `status: discarded`. L'`annuncio_id` resta in `state.json`, così
   l'offerta non rientra alle run successive. Nessuna candidatura creata.
3c. **Scadenza** (routine, passo 4-bis): `status: expired` quando
   `scripts/check_liveness.py` accerta che l'annuncio non esiste più. È l'unica
   transizione di stato che la routine può fare, e non è una decisione: è una
   constatazione. Nota nel digest, nessuna candidatura creata, `annuncio_id`
   invariato in `state.json`. Reversibile a mano se l'utente sa che l'annuncio è
   ancora valido (es. career page con soft-404 o marker fuorviante).

## Invarianti

- La fusione cross-fonte non genera mai testo nuovo: ogni campo del record
  fuso è riconducibile a UNA fonte precisa (attribuzione, mai sintesi).
- `sources[].annuncio_id` restano le chiavi per-fonte di state.json/source-log:
  la fusione vive solo qui, mai a monte.
- La routine crea solo `pending`; non promuove, non scarta, non riapre. L'unica
  transizione che le è concessa è `pending → expired`, e solo su evidenza
  positiva di chiusura dell'annuncio (passo 4-bis): è un fatto accertato, non un
  giudizio, ed è ciò che la tiene dentro D3.
- Una voce promossa non torna in staging (vive in `applications/`).
- `staging/` si può svuotare senza perdere verità (le offerte viste
  restano in `state.json`/`source-log/`, le candidature vere in `applications/`).
  In pratica: la routine elimina a ogni run le voci `discarded` **ed `expired`**
  più vecchie di 3 mesi (passo Retention di `job-watch/SKILL.md`); le `pending`
  non si toccano mai — sono lavoro in attesa di revisione umana. `expired` si
  pota come `discarded` perché in entrambi i casi la voce è uscita dal flusso:
  nell'una per decisione dell'utente, nell'altra perché l'annuncio non esiste
  più. È questa coppia che dà allo staging un'uscita che non dipende solo da una
  decisione umana che potrebbe non arrivare mai.
