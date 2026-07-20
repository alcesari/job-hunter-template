---
name: job-alert-tuner
description: >-
  Metriche di tuning delle ricerche del sistema Job Hunter a partire dal
  source-log nel repo (source-log/YYYY-MM.jsonl): overlap tra ricerche e
  tra intenti, numerosità per ricerca, tasso di annunci fuori scope.
  Analizza anche lo stato dello staging: distribuzione degli score di fit
  e quanto lavoro del batch resta non revisionato. Usa
  SEMPRE questa skill quando l'utente chiede: "come stanno andando le
  ricerche/gli alert", "quali ricerche rendono", "ci sono alert
  doppi/inutili", "tuning del sourcing", "metriche della routine",
  "conviene togliere qualche alert", "quante offerte sono ferme in
  staging", "come sono distribuiti i fit", "perché non trovo mai fit
  forti", o vuole capire se le fonti del digest producono rumore. Produce
  analisi e raccomandazioni in chat: NON modifica da sola profilo o alert.
---

# job-alert-tuner

Modulo 1.2.2 del progetto Job Hunter. Analizza il `source-log` prodotto dalla routine `job-watch` e risponde a tre domande: quali ricerche portano volume, quali si sovrappongono, quali portano rumore (annunci fuori scope). L'output informa; le modifiche restano all'utente, tramite `job-search-profile` (1.2) per i criteri e `job-alert-config` (1.2.1) per riallineare gli alert.

## Precondizioni di readiness

**Due prerequisiti distinti, non uno.** Le metriche 1-4 (sourcing) richiedono il `source-log`; le metriche 5-6 (staging) richiedono `staging/`. Sono indipendenti: se manca l'uno, calcola comunque le metriche dell'altro e dichiara quale gruppo non è calcolabile e perché. Non bloccare l'intera skill per un prerequisito che serve solo a metà dell'analisi — e non usare l'uno come surrogato dell'altro.

Prima di calcolare metriche, verifica il prerequisito minimo di questa skill: esiste almeno un file `source-log/YYYY-MM.jsonl` con almeno una riga. **Attenzione: qui il gap NON è l'onboarding** — a differenza delle altre skill funzionali, il prerequisito mancante è un passo successivo. Il source-log lo produce la routine `job-watch`, che dev'essere già girata almeno una volta. Se la cartella `source-log/` è assente o vuota, o i file esistono ma hanno 0 righe, non procedere e non ricostruire il log da fonti alternative: fermati e spiega il gap reale con una frase specifica, es.: "Non ho ancora metriche da analizzare: il source-log lo scrive la routine `job-watch`, che finora non ha prodotto dati — facciamola girare almeno una volta (skill `job-watch`) e poi torniamo qui al tuning.". (È il "caso base" già descritto sotto in dettaglio: qui è la guardia d'ingresso esplicita, con la stessa postura — nessun crash, nessuna ricostruzione inventata.)

## Contratto dati

Il `source-log` vive nel repo, in `source-log/YYYY-MM.jsonl` (un file JSONL per mese, rotazione mensile). Lo schema completo — chiavi, enum, campo `intento_id`, semantica "una riga = un annuncio osservato da una ricerca in una run" — è in `references/source-log-schema.md`: **leggilo prima di ogni analisi**, è il contratto che questa skill ha definito e che la routine `job-watch` rispetta scrivendolo a ogni run.

## Caso base da gestire per primo: il log non c'è (previsto, non un errore)

Il `source-log` è scritto dalla routine `job-watch`: se manca, la routine non ha ancora girato (o l'ultima run è fallita prima di scrivere — controlla `source-log/runs.jsonl`, il ledger delle run). Non è un errore, è uno stato previsto. Quindi, prima di tutto:

1. Guarda nella cartella `source-log/` del repo (file locali in sessione Claude Code, nessun connettore): cerca i file `YYYY-MM.jsonl`. Se una finestra temporale richiesta copre più mesi, i file mensili corrispondenti vanno **concatenati** (leggendoli tutti riga per riga).
2. **Nessun file / cartella vuota** → spiega con calma: "il source-log non esiste ancora: lo produce la routine job-watch a ogni run. Se è vuoto, la routine non ha ancora girato (o l'ultima run è fallita — vedi `runs.jsonl`). Finché non c'è almeno una run, non ci sono metriche calcolabili." Nessun crash, nessun tentativo di ricostruire il log da altre fonti (email digest, state.json): dati parziali produrrebbero metriche fuorvianti.
3. **File presente ma vuoto (0 righe)** → stesso messaggio, più il fatto che il file esiste ma nessuna run ha ancora loggato.
4. **File presente ma con poche run** (1-2 `run_id` distinti) → calcola comunque, ma dichiara che con così poche esecuzioni le metriche sono indicative, non conclusive.

## Parsing (robusto per costruzione)

Usa il code tool per leggere i JSONL **riga per riga** (una riga = un oggetto JSON; es. `pandas.read_json(path, lines=True)`, oppure parsing manuale riga-per-riga se una riga è malformata). Concatena i mensili quando la finestra copre più mesi. Righe malformate (JSON non valido, chiavi obbligatorie mancanti, enum sconosciuti in `esito` o `fonte`): scartale, contale, e riporta il conteggio nell'output ("N righe malformate ignorate") — non fermarti e non correggerle inventando valori. Il JSONL è robusto proprio qui: una riga rotta non compromette le altre. Se le righe malformate superano ~20% del totale, segnala che il log è probabilmente corrotto o che la routine ha deviato dal contratto: in quel caso le metriche non sono affidabili e la cosa va sistemata alla fonte.

## Metriche (definizioni esatte)

Calcola sulle run disponibili (o su una finestra se l'utente la chiede, es. "ultimo mese" = il/i file `YYYY-MM.jsonl` corrispondenti, o filtrando `run_id`). Ogni metrica è **raggruppabile per `intento_id`** (D2): puoi darle sia per singola `ricerca_id` sia aggregate per intento, secondo cosa chiede l'utente.

1. **Numerosità per ricerca** — per ogni `ricerca_id`: righe totali, media per run, trend (prime run vs ultime). Aggregabile per `intento_id`. Una ricerca che porta ~0 annunci per molte run è morta o mal configurata.
2. **Overlap tra ricerche** — per ogni coppia di `ricerca_id`: quanti `annuncio_id` condividono nella stessa run (contando anche le righe `scartato_dedup`, che esistono apposta). Deriva per ogni ricerca la **resa unica**: quota di annunci portati SOLO da quella ricerca. Resa unica bassa + alto overlap con un'altra = candidata alla rimozione. **Overlap TRA intenti** (`intento_id` diversi che portano gli stessi `annuncio_id`): è un caso a sé da segnalare — non è necessariamente un errore (due intenti possono legittimamente sovrapporsi), ma se è alto vale la pena dirlo, perché significa che due intenti stanno cercando quasi la stessa cosa.
3. **Tasso fuori scope per ricerca** — quota di righe con `esito` in {`scartato_lingua`, `scartato_livello`} sul totale della ricerca (aggregabile per `intento_id`). Alto fuori scope = query troppo larga (es. location che pesca annunci in lingua esclusa) — costa tempo di pipeline anche se il digest resta pulito. **NON includere qui gli esiti `scartato_ruolo`/`scartato_location`**: sono career_page-only e non misurano la qualità di una query (una career page non la puoi restringere, fetcha sempre tutta l'azienda) — vanno nella metrica 3-bis, altrimenti falsano il segnale "query da restringere".
3-bis. **Rumore per-azienda del canale `career_page`** (solo se il log contiene righe `fonte: career_page`) — per ogni `azienda_fonte`: quota di `scartato_ruolo` + `scartato_location` sul totale portato da quell'azienda, e conteggio delle righe `incluso_*` sopravvissute. È il segnale di **valore cross-source**: un'azienda che porta 190 righe di cui 189 scartate per ruolo/location e 1 inclusa (già vista anche su Indeed) è candidata a `attiva: false` in `companies.yaml` — non perché la query sia sbagliata (non c'è query), ma perché quella specifica career page rende poco. Distinto dalla metrica 3 proprio perché l'azione è diversa: qui si agisce sull'anagrafica aziende (`job-search-profile`), non sui criteri di ricerca.
4. (Di contorno) **quota `non_lavorato_cap`** complessiva: se è ricorrente, il cap della routine sta tagliando materiale — informazione utile per `parametri_esecuzione`.

### Metriche 5 e 6 — input diverso: `staging/`, non il source-log

Le due metriche seguenti **non leggono il source-log**: leggono `staging/*/fit.yaml` e `staging/*/staging.yaml`. Non cercare i loro campi nel contratto del log, non ci sono. Sono qui perché rispondono alla stessa famiglia di domande ("il sistema sta rendendo?"), ma guardano a valle del sourcing invece che a monte. Valgono le stesse regole di robustezza: file illeggibile o campo assente → scartalo, contalo, dillo; non ricostruire.

5. **Distribuzione degli score e potere discriminante** (input: `staging/*/fit.yaml`, campo `valutazione`→`score`; in alternativa il campo `score` proiettato in `staging.yaml`, più comodo da leggere in blocco)

   Distribuzione dei quattro livelli `forte|buono|parziale|debole` sul totale valutato, complessiva **e** per `intento_id`.

   - **Soglia minima: 20 valutazioni.** Sotto, non calcolare: dillo e fermati su questa metrica (le altre restano valide). Una distribuzione su 8 voci non dice nulla e invita a conclusioni che i dati non reggono.
   - **Segnala esplicitamente le classi vuote o quasi vuote.** Una scala a 4 livelli in cui un livello non viene mai assegnato su un campione ≥ 30 **non sta discriminando**, ed è un fatto da riportare, non da lasciare implicito in una tabella.
   - **Incrocia SEMPRE con `non_lavorato_cap`** (metrica 4). Se il cap morde, la distribuzione osservata **non è un campione rappresentativo** delle offerte disponibili: le voci tagliate dal cap non sono mai state valutate, e nulla garantisce che le lavorate fossero le migliori — il cap taglia in ordine di raccolta, non di promessa. **Dichiaralo come limite dell'analisi**, non ometterlo perché scomodo.

   **Umiltà causale (obbligatoria, stessa postura della metrica 3-bis).** Se un livello è vuoto, ci sono almeno tre spiegazioni con azioni **diverse e incompatibili**, e questa metrica da sola non le distingue. Presentale come ipotesi alternative, mai come diagnosi:
   1. il sourcing non pesca ruoli di quel livello → si agisce sui criteri (`job-search-profile`);
   2. la rubrica di `role-fit` è tarata in modo che quel livello sia di fatto irraggiungibile → si agisce sulla rubrica;
   3. il cap ha tagliato le candidate migliori prima che venissero valutate → si agisce su `parametri_esecuzione`, o si introduce un pre-ordinamento prima del cap.

   Non scrivere mai "la tua scala è sbagliata": con un campione tagliato dal cap non è deducibile. Scrivi cosa si osserva, le tre letture possibili, e cosa servirebbe per distinguerle (tipicamente: una run senza cap, o il cap alzato per qualche giro).

6. **Gap di conversione staging → decisione** (input: `staging/*/staging.yaml`)

   Non è una metrica di sourcing: misura quanto del lavoro prodotto dal batch resta **inutilizzato**. Riporta:
   - quota di voci `pending` sul totale (`pending` / `approved` / `discarded` / `expired`);
   - **età della voce `pending` più vecchia** (dal `run_id` che l'ha creata) e mediana dell'età delle pending;
   - conteggio delle voci con `materials_generated: true` **mai promosse**, cioè materiali pre-generati che nessuno ha mai letto;
   - conteggio delle voci con `materials_flagged: true` (gate di veridicità rosso — vanno guardate prima di essere usate).

   È spesso l'informazione più azionabile che il sistema possa dare: se le pending crescono in modo monotono e nulla viene promosso o scartato, il collo di bottiglia non è il sourcing ma la **revisione**, e nessuna metrica di tuning delle ricerche lo risolve. Dillo esplicitamente quando i numeri lo mostrano — con la stessa franchezza (e senza colpevolizzare: è un'osservazione sul sistema, non sull'utente).

Nota per il futuro (non requisito v1): `applications/<id>/application.yaml` porta un `intent_id`; incrociarlo col log abiliterebbe una metrica *candidature-per-intento* (quali intenti non solo portano volume, ma convertono in candidature reali) a costo quasi zero — da tenere presente, non da implementare ora. **Prerequisito reale**: serve che `applications/` contenga almeno ~5 esiti oltre lo stato "candidata"; finché è vuota o quasi, questa metrica non è calcolabile e non va simulata sui dati di staging (che misurano il giudizio del sistema, non l'esito del mercato).

## Output (in chat)

1. Una tabella riassuntiva per `ricerca_id` (con la colonna `intento_id`, così si legge anche aggregata per intento): volume medio/run, resa unica %, fuori scope %, note.
2. Le coppie con overlap rilevante, distinguendo overlap *dentro* lo stesso intento da overlap *tra* intenti diversi.
2-bis. Se hai calcolato le metriche 5 e 6: la distribuzione degli score (con il limite dovuto al cap dichiarato accanto, non in nota) e lo stato della coda di staging. Se la metrica 6 mostra una coda che cresce senza essere consumata, mettila **in testa** all'output, non in fondo: è il vincolo che rende poco rilevante tutto il resto.
3. **2-4 raccomandazioni qualitative**, nello stile del progetto (pesate, non binarie): non "elimina la ricerca X" ma "X porta il 90% di annunci già portati da Y e quasi nulla di unico: candidata alla rimozione — la decisione è tua". Ogni raccomandazione indica anche DOVE si agisce: criteri → `job-search-profile`, alert sulle piattaforme → `job-alert-config`. **Rendile azionabili**: per le ricerche `linkedin_alert`/`indeed_alert`, risolvi il `ricerca_id` opaco in `searches/alerts-registry.yaml` (se presente) e cita l'**etichetta leggibile** (es. "Integration Engineer — Unione Europea") e, se serve, l'URL/keywords dell'alert reale da disattivare sulla piattaforma — così l'utente sa esattamente quale avviso toccare, non un id criptico.
4. Le soglie usate (es. "resa unica < 15% = bassa") sono euristiche dichiarate nel testo, mai tagli automatici.

## Cosa NON fare

- Non modificare i file in `searches/` né generare istruzioni alert: solo raccomandare e rimandare a 1.2 / 1.2.1.
- Non ricostruire dati mancanti da fonti alternative (digest email, state.json).
- Non presentare metriche su 1-2 run come conclusive.
- Non inventare chiavi o esiti fuori dal contratto: se il log contiene valori non previsti, è la routine che ha deviato — segnalalo, non adattare silenziosamente il contratto.
