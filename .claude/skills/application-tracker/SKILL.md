---
name: application-tracker
description: >-
  Tracker delle candidature del sistema Job Hunter, repo-first (cartella
  applications/ nel repo: 1 candidatura = 1 sottocartella <id>/ con
  application.yaml + events.jsonl). Usa SEMPRE questa skill quando l'utente
  vuole: aggiungere o promuovere una candidatura ("aggiungi al tracker",
  "mi sono candidato a X", "promuovi questo annuncio"), aggiornare uno stato
  ("ho fatto il colloquio", "mi hanno rifiutato", "ho ritirato la
  candidatura"), controllare le risposte ("ci sono novità sulle
  candidature?", "guarda se mi hanno risposto"), preparare un follow-up
  ("prepara il follow-up per X"), o vedere la pipeline ("a che punto sono
  le candidature"). NON usare per la gestione produttività generale
  (backlog, roadmap, task personali): questa skill tocca SOLO la cartella
  applications/ del sistema Job Hunter.
---

# application-tracker

Modulo 2.3 del progetto Job Hunter: lo stato-workflow delle candidature vive qui, **nel repo**, sotto `applications/` (D8 — repo-first, niente Todoist). È l'unica fonte di verità per "a che punto è" una candidatura (il `role-fit-output` in `role-fit/` si ferma a `promosso_a_tracker`, per costruzione). Due principi sopra tutto:

1. **Nessuna candidatura nasce da sola**: la promozione dal digest/valutazione al tracker è SEMPRE un'azione esplicita dell'utente (decisione fissa del progetto). La routine NON scrive in `applications/` (la legge soltanto, per le scadenze del digest), e questa skill non crea candidature "per completezza".
2. **Nessun cambio di stato silenzioso**: ogni modifica derivata da una email va mostrata (email + azione proposta) e confermata prima di toccare i file.

**Dove giri conta (D5, D7)**: la scrittura richiede una sessione Claude Code (file locali + commit). Da chat claude.ai pura il connettore GitHub è di sola lettura: puoi leggere e proporre, ma NON persistere — dichiaralo e rimanda la scrittura a una sessione Claude Code. Ogni mutazione la committi TU: l'utente non tocca mai git.

## Precondizioni di readiness

- **Profilo configurato (prerequisito minimo)**: esiste `master-profile.yaml` nella radice del repo ed è non vuoto. Se manca, l'utente non ha ancora fatto l'onboarding: non procedere e non iniziare a tracciare candidature su un sistema non inizializzato. Fermati e reindirizza ad `agent-config` con una frase specifica al gap reale, es.: "Prima di tracciare le candidature conviene configurare il tuo profilo, che non risulta ancora presente: vuoi che partiamo dall'onboarding adesso?". **Nota**: la cartella `applications/` NON è un prerequisito — la crea questa skill stessa alla prima promozione, quindi la sua assenza non è un gap da reindirizzare; il prerequisito è il profilo.
- **Repo del sistema** clonato, sessione Claude Code (nessun `tool_search`: `applications/` è filesystem locale).
- **Gmail** — `tool_search` query "Gmail": serve per il controllo risposte e per le bozze di follow-up. Se manca, le funzioni di promozione/avanzamento manuale funzionano comunque; solo il pezzo email si ferma finché non è collegato.

## Contratto di storage: `applications/<id>/`

```text
applications/
  <id>/                    # il nome della cartella È l'id (data inclusa)
    application.yaml       # solo STATO CORRENTE (snapshot)
    events.jsonl           # solo STORIA (append-only)
    jd.md                  # la JD CONGELATA al momento della promozione
    materials/             # CV/cover/DM prodotti da cv-tailoring (2.2)
      cv.md  cover-letter.md  recruiter-dm.md  (+ PDF renderizzati)
      diff-report.md       #   verifica di veridicità master↔generato (D3)
```

**Perché `jd.md` esiste.** L'annuncio online sparisce: fra tre mesi il link è
morto e con esso l'unica traccia di *contro cosa* ti sei candidato. Senza il
testo congelato si sa **che** una candidatura è stata rifiutata, ma non **con
quale CV** né **contro quale annuncio** — e nessuna analisi a posteriori
(cosa converte, cosa no) diventa più possibile. Lo staging non lo salva: porta
solo `links.jd`, e la retention lo pota comunque. La promozione è **l'ultimo
momento utile** per catturarlo.

**Regola sull'id**: include la data (es. `acme-data-engineer-2026-07`) per evitare collisioni su ricandidature stessa azienda+ruolo. La cartella e il campo `id` in `application.yaml` coincidono sempre.

**Invariante snapshot/storico** (non violarlo mai): `application.yaml` è solo lo stato corrente; `events.jsonl` è solo la storia. Ogni mutazione **appende l'evento E aggiorna lo YAML nello stesso commit**. Lo YAML NON replica i campi dell'ultimo evento (niente "ultimo aggiornamento: ..." copiato dall'evento — si legge da `events.jsonl`).

### `application.yaml` (snapshot)

- `id` — coincide col nome cartella.
- `company`, `role`.
- `status: da_candidare | candidata | in_corso | offerta | chiusa` — è il funnel (i vecchi stati-sezione).
- `outcome: null | rifiuto | ritiro | accettata` — valorizzato **se e solo se** `status: chiusa`.
- `source: indeed | linkedin_alert | indeed_alert | manuale` — enum unico
  condiviso con lo `staging.yaml` (`job-watch`) e il `sorgente` del `role-fit`.
  **Il valore è copiato 1:1** dallo staging/role-fit alla promozione: mai
  reinterpretato, rimappato o normalizzato dall'agente (es. `linkedin_alert`
  resta `linkedin_alert`, non diventa `linkedin`). Per una candidatura nata in
  chat senza staging/role-fit, `manuale`.
- `intent_id` — l'intento (D2) da cui viene la candidatura; ereditato dal role-fit se promossa da lì, altrimenti chiesto/`null`.
- `links` — `jd` (URL annuncio), `role_fit` (percorso relativo al file in `role-fit/`, se esiste).
- `next_action` — `{ type: follow_up | interview | reply | none, due: <YYYY-MM-DD | null> }`. È QUI che vive la scadenza (la vecchia "due date"), non negli eventi.
- `materials` — percorsi relativi ai file in `materials/` (popolato da cv-tailoring).

### `events.jsonl` (storia, append-only)

Un oggetto JSON per riga. Chiavi minime: `date` (YYYY-MM-DD), `type`, `note`. Chiavi aggiuntive per tipo sono ammesse senza rompere nulla (stessa proprietà che ha fatto scegliere JSONL in D6). Tipi:

- `created` — candidatura creata nel tracker.
- `applied` — candidatura inviata.
- `status_change` — con `from`/`to`.
- `email_processed` — con `gmail_message_id` e `classificazione`. **È il dedup email** (rimpiazza il vecchio commento Todoist).
- `follow_up_sent` — follow-up inviato (l'evento si scrive quando il follow-up è INVIATO; la *scadenza* del follow-up è `next_action` nello snapshot, non un evento).
- `interview` — colloquio (data/esito).
- `closed` — con `outcome`.
- `note` — annotazione libera.

Il log si APPENDE, mai riscrive.

**Ogni transizione porta quando e perché (requisito per l'analisi a posteriori).**
`events.jsonl` è già il ledger delle transizioni: `status_change` con `from`/`to`
esiste, `date` esiste. Due precisazioni che lo rendono davvero analizzabile:

- **`at` (ISO 8601 UTC) — raccomandato su ogni nuovo evento**, accanto a `date`
  (che resta obbligatorio e invariato: nessuna rottura per gli eventi già
  scritti). `date` ha granularità giornaliera e non ordina due transizioni dello
  stesso giorno — che è precisamente il caso di una giornata movimentata
  (risposta la mattina, colloquio fissato il pomeriggio). Senza `at` i tempi di
  funnel si calcolano male e nessuno se ne accorge.
- **La causa non è opzionale.** Ogni `status_change` dichiara *perché*: `note`
  in linguaggio naturale, più — quando l'origine è un'email — il
  `gmail_message_id` che l'ha provocata. Uno stato che cambia senza una causa
  registrata è un buco nella storia: fra sei mesi non si distingue un rifiuto
  ricevuto da un ritiro deciso.

Esempio di transizione ben formata:

```json
{"date":"2026-07-20","at":"2026-07-20T14:32:05Z","type":"status_change","from":"candidata","to":"in_corso","note":"invito a colloquio tecnico ricevuto via email","gmail_message_id":"18f…"}
```

Non è una migrazione: gli eventi vecchi restano validi senza `at`. Chi legge
tratta `at` come opzionale e ricade su `date` quando manca.

**Righe malformate (robustezza di lettura)**: come per il source-log del tuner,
una riga non parsabile (JSON rotto, chiavi minime mancanti) non deve MAI far
fallire la lettura né essere "corretta" riscrivendo il file — il JSONL è scelto
apposta perché una riga rotta non comprometta le altre. Scartala dal parsing,
segnala all'utente che la storia della candidatura è incompleta ("N righe
malformate in `events.jsonl` di <id>"), e tratta le decisioni che dipendono da
quella storia come prese su dati parziali. Caso delicato: se la riga rotta
potrebbe essere un evento `email_processed` (il dedup email), NON assumere che
l'email non sia mai stata processata — in ambiguità mostra l'email e chiedi
prima di agire: riprocessare un `rejection` già gestito è esattamente il danno
che il dedup esiste per evitare.

## Promozione di una candidatura (manuale)

Su richiesta esplicita ("aggiungila al tracker", "mi sono candidato a X", "promuovi questa dallo staging"). Due punti d'ingresso:

- **Da chat** (una JD/valutazione in corso): raccogli i dati come sotto.
- **Dallo staging** (D4 — l'utente approva una voce che la routine `job-watch` ha pre-lavorato): la voce `staging/<id>/` porta già `staging.yaml` + `fit.yaml` + eventuali `materials/`. Promuovere = crea `applications/<id>/` (stesso `id`), **archivia** materiali e JD (vedi «Archiviazione alla promozione» qui sotto), **persisti** `fit.yaml` in `role-fit/` e mettine il percorso in `links.role_fit`, eredita `intent_id`/`links.jd`/`source`. Poi rimuovi (o marca `approved` e archivia) la voce staging: è uscita dall'anticamera. Lo scarto di una voce staging non crea nulla (`status: discarded`; l'annuncio resta in `state.json` così non rientra). Vedi `job-watch/references/staging-schema.md`.

### Archiviazione alla promozione (obbligatoria, non rimandabile)

È il passo che rende ricostruibile a posteriori cosa è stato davvero inviato.
Va fatto **prima** di rimuovere la voce da staging, e nell'ordine seguente —
copia, verifica, poi rimuovi: se qualcosa fallisce a metà non hai perso nulla.

1. **Materiali** — copia `staging/<id>/materials/` in
   `applications/<id>/materials/` (incluso `diff-report.md`), verifica che i
   file siano arrivati, e solo allora rimuovi l'originale da staging. Se la voce
   non ha materiali (fit `parziale`/`debole` promosso a mano), salta senza
   rumore: li genererà `cv-tailoring` quando servono.
2. **JD** — congela il testo dell'annuncio in `applications/<id>/jd.md`, con
   un'intestazione di provenienza:

   ```markdown
   ---
   fonte: linkedin_alert          # copiato da staging.yaml → source
   url: https://…                 # links.jd
   catturata_il: 2026-07-20
   completezza: completa | parziale | non_disponibile
   ---

   <testo dell'annuncio>
   ```

   Da dove prendere il testo, in quest'ordine:
   - **Indeed** → connettore `get_job_details` (testo completo);
   - **career page** → l'URL è fetchabile se il dominio è allowlistato;
   - **LinkedIn** → non fetchabile (V5): **chiedi all'utente di incollarlo**. È
     il momento giusto per farlo, perché sta candidandosi e ha l'annuncio aperto;
   - **annuncio già sparito** → `completezza: non_disponibile`, salva comunque
     `jd.md` con la sola intestazione più quello che è ricostruibile dal
     `fit.yaml`, dichiarandone la natura. **Non ricostruire il testo
     inventandolo**: una JD plausibile ma falsa è peggio di una mancante, perché
     nessuno la ri-metterà in discussione.

   Il campo `completezza` non è burocrazia: distingue un archivio affidabile da
   uno che *sembra* affidabile, e chi legge fra sei mesi non ha altro modo di
   saperlo.
3. **Solo dopo** rimuovi (o marca `approved`) la voce in staging.

1. **Raccogli il minimo**: ruolo, azienda, link JD, `source`, e `intent_id` se noto (da un `role-fit` in chat, o dallo `staging.yaml`, lo hai già, insieme al percorso del file role-fit da mettere in `links.role_fit`; se l'utente arriva dal digest, fatti dare il link).
2. **DEDUP PRIMA di creare** (obbligatorio): cerca tra le cartelle/`application.yaml` di `applications/` (attive E chiuse — sono tutte lì, la ricerca è semplice) per azienda e ruolo, con normalizzazione fuzzy: minuscolo, senza punteggiatura, senza suffissi societari (S.r.l., S.p.A., B.V., GmbH, Inc, Ltd, AB, SA), tolleranza per varianti di titolo ("BI Developer" ~ "Business Intelligence Developer"). Match probabile → mostra la candidatura esistente e chiedi: è la stessa (aggiorno quella) o una posizione diversa nella stessa azienda (creo una nuova `<id>`)? NON creare in caso di dubbio non risolto.
3. **Crea la candidatura**: costruisci l'`id` (`<azienda-slug>-<ruolo-slug>-<YYYY-MM>`), crea `applications/<id>/` con `application.yaml` (`status: da_candidare` se deve ancora inviare, `candidata` se ha già inviato — chiedi quale, non assumere) e `events.jsonl` con il primo evento `created` (+ `applied` se già inviata). Se esiste un role-fit per la posizione, mettine il percorso in `links.role_fit`. **Committa** (snapshot + eventi nello stesso commit).

   **Collisione legittima nello stesso mese (F17)**: l'`id` ha granularità mensile, quindi non distingue due candidature diverse per la stessa azienda+ruolo aperte nello stesso mese — caso reale: ricandidatura dopo un rifiuto, o due posizioni distinte con lo stesso titolo alla stessa azienda. Se al passo 2 il dedup fuzzy ha già escluso che sia la stessa candidatura (l'utente ha confermato che è un caso nuovo), non riusare l'id esistente: aggiungi un suffisso numerico progressivo (`-2`, `-3`, ...) o, se preferisci maggiore leggibilità nel contesto, la data (`-YYYY-MM-DD`). Verifica che l'id risultante non collida a sua volta prima di creare la cartella.
4. Ricorda (alla skill `role-fit`, o direttamente se il contesto è in chat) di aggiornare l'`esito` del role-fit a `promosso_a_tracker`.

## Avanzamenti dichiarati dall'utente

"Ho inviato la candidatura", "ho il colloquio martedì", "mi hanno fatto un'offerta": aggiorna `status` nello snapshot, appendi l'evento `status_change` (o `applied`/`interview`), gestisci `next_action` (vedi follow-up), committa. Le dichiarazioni dirette dell'utente non richiedono la conferma extra prevista per le email — è lui la fonte.

Chiusure: "mi hanno rifiutato" → `status: chiusa`, `outcome: rifiuto`, evento `closed`. "Lascio perdere / ritiro" → `outcome: ritiro`, idem. "Ho accettato!" → `outcome: accettata`, e proponi di chiudere per ritiro le altre candidature ancora attive (proponi: la decisione è sua).

## Follow-up

- Al passaggio in `candidata`: proponi `next_action = { type: follow_up, due: +7 giorni }` (default del progetto, dichiarato — l'utente può cambiarlo o rifiutarlo).
- A `due` raggiunta, quando l'utente lo chiede ("prepara il follow-up per X" o "cosa c'è in scadenza?"): genera la bozza di follow-up — DM breve (60-100 parole, cortese, un riferimento concreto alla candidatura, una domanda chiara sullo stato) o **bozza email in Gmail** (bozza, MAI invio diretto). Dopo che il follow-up è inviato: evento `follow_up_sent` + proponi nuova `next_action` a +7/+10 giorni o `type: none`.
- Colloquio fissato: `next_action = { type: interview, due: <data> }`, `status: in_corso`.

Nota: la funzione-promemoria non è più delegata a notifiche di app terze. Le scadenze (`next_action.due`) vivono nello snapshot e sono lette dal digest della routine e su richiesta in sessione — è l'unico canale che le fa emergere.

## Aggiornamento stato via email (il pezzo delicato)

SOLO su richiesta esplicita ("controlla le risposte", "novità?") — mai in autonomia.

1. **Recupero**: Gmail `search_threads` su una finestra recente (default: 7 giorni, dichiaralo; l'utente può allargarla). Cerca in modo mirato: per ogni candidatura attiva, query con nome azienda e/o ruolo; più una passata generica su mittenti tipici di ATS/recruiting se le candidature attive sono poche. Leggi i thread candidati con il contenuto completo, non gli snippet.
2. **Mappatura email → candidatura** (fuzzy, a livelli):
   - *Match forte*: dominio o nome del mittente riconducibile all'azienda della candidatura E il titolo del ruolo compare in subject/body → procedi con conferma leggera.
   - *Match medio*: solo l'azienda matcha, e c'è UNA sola candidatura attiva per quell'azienda → proponi l'associazione, chiedi conferma.
   - *Ambiguo*: l'azienda matcha ma ci sono PIÙ candidature per quell'azienda, oppure scrive un'agenzia/ATS il cui dominio non c'entra con l'azienda (caso frequente: `no-reply@ats-di-terzi.com`) → mostra l'email e chiedi a quale candidatura appartiene. Se l'utente la associa, annota l'associazione mittente→candidatura con un evento `note` (`{"type":"note","note":"mittente <x> = questa candidatura"}`): le email successive dello stesso thread/mittente matcheranno da sole.
   - *Nessun match*: segnalala come "email orfana" e chiedi se riguarda una candidatura fuori tracker — NON forzare l'associazione alla candidatura più simile.
3. **Dedup email** (obbligatorio, prima di ogni azione): ogni email processata si registra come evento `email_processed` in `events.jsonl` (`gmail_message_id` + classificazione + data). Prima di proporre un'azione, controlla gli eventi `email_processed` della candidatura: `gmail_message_id` già presente → salta senza dire nulla (non è una novità).
4. **Classificazione** in quattro classi: `ack` (conferma ricezione candidatura) · `rejection` · `invito_colloquio` · `ping` (richiesta info/disponibilità/documenti). In dubbio tra due classi, mostra l'email e chiedi — un falso rejection che chiude una candidatura è il danno peggiore che questa skill possa fare.
5. **Azione per classe** (sempre: proposta → conferma → esecuzione → evento + evento `email_processed` di dedup, nello stesso commit):
   - `ack` → evento `note`/`applied`; nessun cambio `status`.
   - `rejection` → proponi: `status: chiusa` + `outcome: rifiuto` + evento `closed`. Conferma esplicita SEMPRE, anche su match forte.
   - `invito_colloquio` → proponi: `status: in_corso` + `next_action = { type: interview, due: <data se presente nella mail; altrimenti chiedi> }` + eventuale bozza di risposta.
   - `ping` → mostra la richiesta e proponi una bozza di risposta (bozza Gmail, mai invio).
6. **Riepilogo finale**: cosa è stato aggiornato, cosa è in attesa di decisione, le orfane.

## Pipeline view (artefatto generato, mai fonte di verità)

Su richiesta ("a che punto sono le candidature", "mostrami la pipeline"): genera una **tabella funnel in chat** leggendo gli `application.yaml` (raggruppati per `status`, con `next_action.due` in evidenza). Su richiesta o come parte del digest, rigenera anche `PIPELINE.md` nel repo e committalo: GitHub lo renderizza (anche da mobile) — è la vista-da-telefono senza app terze. `PIPELINE.md` è SEMPRE rigenerabile dagli snapshot: non scriverci nulla che non derivi da `applications/`. È un artefatto **co-scritto** con la routine `job-watch` (eccezione dichiarata alla regola di proprietà D5, innocua perché mai fonte di verità): chi lo tocca lo rigenera SEMPRE integralmente da `applications/`, mai con merge manuale; in conflitto vince la rigenerazione più recente.

## Casi limite

- **Due candidature stessa azienda**: sempre chiedere, mai indovinare dal solo mittente.
- **Email su candidatura già chiusa** (es. rejection dopo un ritiro): appendi l'evento alla candidatura chiusa senza riaprirla (`status` resta `chiusa`), e segnalalo all'utente.
- **Scrittura/commit fallito a metà operazione**: riporta cosa è stato scritto/committato e cosa no, così l'utente non resta con uno stato a metà senza saperlo. Se lo snapshot è stato aggiornato ma l'evento no (o viceversa), sistema per ripristinare l'invariante prima di considerare chiusa l'operazione.
- **Volumi**: se le candidature attive sono tante (>15), fai il controllo email per gruppi e dillo, invece di degradare la qualità del matching.

## Cosa NON fare

- Non creare candidature senza richiesta esplicita (né dalla routine, né "già che ci sono").
- Non chiudere/spostare candidature su base email senza conferma.
- Non inviare mai email: solo bozze.
- Non toccare cartelle del repo diverse da `applications/` (e, in lettura, `role-fit/` per i link).
- Non riscrivere `events.jsonl`: solo append.
- Non far divergere snapshot e storico: ogni mutazione aggiorna entrambi nello stesso commit.
- Non rimuovere una voce da `staging/` prima di aver verificato che materiali e `jd.md` siano arrivati in `applications/<id>/`: l'ordine è copia → verifica → rimuovi.
- Non ricostruire una JD sparita inventandone il testo: `completezza: non_disponibile` è un esito onesto, una JD plausibile ma falsa no.
- Non cambiare stato senza registrare la causa nell'evento.
- Non processare due volte la stessa email (evento `email_processed` di dedup prima di tutto).
