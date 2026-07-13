# digest — contratto di consegna della routine

Il **digest** è ciò che l'utente riceve a ogni run di `job-watch`. È il canale
con cui il sistema "lo cerca lui" (invece di aspettare che apra il repo). Con
Todoist fuori (D8), il digest è anche l'UNICO canale che fa emergere le
**scadenze**: la sua sezione scadenze non è opzionale.

## Canale (doppio)

1. **Gmail** — il push: raggiunge l'utente senza aprire l'app. **Nella routine
   cloud l'esito normale è la bozza**: l'invio SMTP reale fallisce
   strutturalmente nel sandbox (nessun socket di rete grezzo esposto — vedi
   `job-watch/SKILL.md`, sezione "Consegna Gmail"), non è un caso limite.
   La routine crea una **bozza** del digest verso l'utente: la vede in Gmail e
   la copia autorevole resta comunque il file nel repo. L'invio SMTP reale
   resta un percorso valido solo per un'eventuale routine **Desktop locale**
   (rete non sandboxata). Se l'ambiente espone una notifica push nativa,
   usala come segnale immediato aggiuntivo. Oggetto suggerito:
   `Job Hunter — digest <YYYY-MM-DD> (<N> nuove, <M> in scadenza)`.
2. **File nel repo** — `digests/<YYYY-MM-DD>.md`: il record durevole, versionato,
   sfogliabile anche da GitHub mobile. Stesso contenuto dell'email.

Se più run cadono nello stesso giorno, il file è `digests/<YYYY-MM-DD>-<HHMM>.md`.

**Nota D3**: inviare il digest all'utente è consentito. Tutto ciò che è diretto
a un datore di lavoro (candidature, follow-up) resta bozza, mai inviato dalla
routine.

## Formato

Markdown (rende bene in email, come file nel repo e su GitHub mobile). Conciso:
è una vista di lavoro, non un report. Sezioni, nell'ordine:

### 1. Intestazione
Timestamp della run, intenti processati (per `nome`/`id`), fonti interrogate con
eventuali fallimenti (es. "⚠ connettore Indeed non disponibile: saltato"), e la
**prossima run attesa** (data/ora indicativa dalla cadenza di scheduling): se
quel momento passa senza né email né commit, la routine è morta in silenzio —
il ledger `source-log/runs.jsonl` dice dove (start senza end).

### 2. Offerte nuove valutate
Raggruppate per intento, ordinate per `score` (forte → debole). Per ognuna:
`Ruolo @ Azienda` · location · **score** · una riga di sintesi (dai bullet del
fit) · link alla JD. Se i materiali sono pre-generati (fit forte/buono), segnala
"📄 materiali pronti in staging" col path `staging/<id>/`. Se non ci sono offerte
nuove, dillo esplicitamente (non è un errore). Una fusione **cross-run** che ha
solo aggiunto una fonte a una voce `pending` già esistente (vedi
`references/entity-resolution.md`) NON conta come offerta nuova qui — va nella
sezione Anomalie (punto 6).

### 3. In attesa di revisione (staging `pending`)
Le voci `staging/*/staging.yaml` con `status: pending`, con l'azione richiesta:
"valuta e promuovi (`application-tracker`) o scarta". Include sia le nuove di
questa run sia quelle rimaste da run precedenti non ancora revisionate.

### 4. Scadenze (OBBLIGATORIA)
Da `applications/*/application.yaml` → `next_action` con `due` entro una finestra
(default: prossimi 7 giorni, più gli scaduti). Per ognuna: `Ruolo @ Azienda` ·
tipo (`follow_up`/`interview`/`reply`) · data · stato. È la funzione-promemoria
che prima delegavamo a Todoist: se questa sezione manca, il contratto è violato.
Se non ci sono scadenze, scrivi "nessuna scadenza nei prossimi 7 giorni".

### 5. Sintesi pipeline (OBBLIGATORIA) + PIPELINE.md
Conteggio delle candidature per `status` (`da_candidare`/`candidata`/`in_corso`/
`offerta`/`chiusa`), lette da `applications/`. La routine **rigenera** anche
`PIPELINE.md` (tabella funnel completa) e lo committa: il digest linka ad esso.
`PIPELINE.md` è sempre rigenerabile dagli snapshot, mai fonte di verità.

### 6. Anomalie della run
Fonti fallite, alert non parsati, righe di source-log malformate, scrittura
telemetria fallita, ecc. Trasparenza operativa: se qualcosa è degradato, si dice.

**Fusione cross-run (obbligatoria se avvenuta)**: se il passo 5-bis di
`job-watch/SKILL.md` ha aggiunto una fonte nuova a una voce `staging` `pending`
già esistente, segnalalo qui (es. "🔗 nuova fonte trovata per `<ruolo> @
<azienda>`, già in staging da run precedente"). Se invece ha riconosciuto che
una posizione ricomparsa corrisponde a una candidatura già in `applications/`,
segnalalo con link alla candidatura (es. "↩️ `<ruolo> @ <azienda>` ricompare su
una nuova fonte — già candidato il `<data>`, nessuna nuova voce in staging").
Nessuna delle due va contata tra le "offerte nuove" del punto 2.

**Career page — verdetto di diagnosi (obbligatoria se il canale è attivo)**:
riporta testualmente il campo `diagnosis.verdetto` dell'output di
`scripts/fetch_careers.py` — non riassumerlo, non riformularlo: è scritto per
essere letto a colpo d'occhio senza interpretare i singoli errori per-azienda
(distingue già da solo un fallimento isolato da un blocco sistemico
dell'ambiente). Se `diagnosis` segnala "BLOCCO AMBIENTALE PROBABILE" per la
prima volta, aggiungi una riga esplicita del tipo "⚠ career page: possibile
blocco egress in questo ambiente, verificare nei prossimi run" — così è
visibile anche a chi legge solo l'intestazione, non l'intero digest.

## Cosa il digest NON fa

- Non cambia stati di candidature né promuove offerte: è sola lettura + notifica.
  Ogni azione (valutare, promuovere, candidarsi, follow-up) resta in chat, con le
  skill dedicate.
- Non invia nulla verso datori di lavoro.
- Non omette scadenze e pipeline: sono le due sezioni che, senza Todoist,
  giustificano l'esistenza stessa del digest.
