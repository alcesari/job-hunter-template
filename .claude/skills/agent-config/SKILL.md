---
name: agent-config
description: >-
  Onboarding guidato per il sistema Job Hunter. Usa questa skill quando un
  nuovo utente vuole attivare il sistema di ricerca lavoro autonoma:
  ingerisce il CV, fa domande su vincoli/preferenze (trasferimento, remoto,
  retribuzione, preavviso, diritto al lavoro, lingue), produce
  master-profile.yaml e il primo intento di ricerca in searches/ nel repo
  del sistema, genera e attiva la config della routine job-watch. Trigger
  su qualsiasi richiesta di avviare/configurare/inizializzare il sistema o
  la ricerca lavoro, anche breve o generica — es. "inizializza il
  progetto", "salva queste skill e configurami", "iniziamo a fare
  job-hunting", "configurami il sistema". Non richiedere che l'utente
  nomini "agent-config" o "onboarding": il segnale è l'intento di avviare
  il processo. NON usarla per modificare un search-profile già esistente
  ("aggiorna il mio profilo di ricerca", "cambia i ruoli/le location"):
  per quello esiste la skill job-search-profile.
---

# agent-config

Orchestratore conversazionale che porta un utente da zero a sistema attivo (Modulo 1.1 del progetto Job Hunter). Produce i primi artefatti di profilo nel repo del sistema (`master-profile.yaml` nella radice, `searches/defaults.yaml` + il primo `searches/<intent-id>.yaml`) e passa la palla a `job-alert-config` (1.2.1) per la config degli alert.

**Nota architetturale (D5, D7 — da non dimenticare in futuri aggiornamenti)**: architettura a binario unico. TUTTO vive nello stesso repo — profili (`master-profile.yaml`, `searches/`), valutazioni (`role-fit/`), candidature (`applications/`), telemetria operativa (`source-log/`, `state.json`, staging, digest) e le skill stesse sotto `.claude/skills/`. Non c'è più Google Drive: era il vecchio design, sostituito. Fatto tecnico che motiva l'impianto: l'integrazione GitHub di base disponibile in chat claude.ai (Impostazioni → Connettori) è di **sola lettura** — sincronizza i contenuti per contesto ma non espone tool di scrittura/commit. Per questo ogni SCRITTURA reale (profili, valutazioni, candidature, stato) avviene in **sessione Claude Code** (Desktop o routine cloud), che ha accesso git nativo indipendente dai connettori di chat. Regola di proprietà: le sessioni interattive scrivono profili/valutazioni/candidature; la routine scrive solo lo strato operativo append-only (log/state/digest/staging).

Non eseguire questa skill silenziosamente: è interattiva per costruzione. Ogni sezione sotto corrisponde a un blocco di domande da fare in chat, una alla volta o in piccoli gruppi coerenti — mai tutte insieme in un unico wall of text.

## Passo 0 — Messaggio di apertura fisso

Prima di qualunque verifica tecnica, invia sempre questo messaggio (adattalo minimamente se necessario, ma mantieni struttura, contenuto e tono):

---

Ciao! 👋 Iniziamo la configurazione del sistema Job Hunter.

Ti spiego prima cosa serve e cosa succederà, così puoi preparare tutto senza interruzioni a metà strada :)

**La casa del sistema è un repository GitHub** 🏠 — un'unica repo (questa, in cui stiamo lavorando ora) contiene tutto: il tuo profilo, le ricerche, le valutazioni, le candidature e la routine automatica. Se stai leggendo questo messaggio in Claude Code, la repo c'è già: la verifico tra un attimo.

**Cosa ti servirà collegato prima di iniziare:**
1. **Gmail** 📧 — necessario alla routine di ricerca automatica per leggere gli alert LinkedIn/Indeed, e per preparare le bozze di follow-up più avanti.
2. **Indeed** 🔍 — necessario alla routine per cercare annunci.

Se non li hai già collegati, puoi farlo da Impostazioni → Connettori. Te li verifico comunque uno per uno tra un attimo.

**Cosa ti chiederò:**
- Il tuo CV 📄 (in qualsiasi formato che riesci a caricare qui in chat)
- Alcune domande su vincoli e preferenze: disponibilità a trasferirti o lavorare da remoto, retribuzione attuale e aspettativa, preavviso, diritto al lavoro nei paesi che ti interessano, lingue
- Conferma su ruoli, location e criteri di esclusione per la ricerca

**Cosa succederà dopo:**
1. Scrivo il tuo profilo nel repo (e lo committo io — non devi toccare git)
2. Ti do le istruzioni per impostare gli alert LinkedIn/Indeed
3. Attiviamo insieme la routine di ricerca automatica — questo passaggio si fa dall'**app desktop di Claude Code** 🖥️ (niente terminale, solo click)

Da lì in poi il sistema lavora per te: ricevi un digest via email con gli annunci trovati, e usi la chat per valutarli, preparare CV su misura e tenere traccia delle candidature.

Cominciamo dal CV — puoi caricarlo ora? 😊

---

Dopo questo messaggio, procedi comunque con la verifica tecnica concreta delle Precondizioni sotto — il messaggio dichiara i requisiti all'utente, ma non sostituisce il controllo reale via `tool_search`. Non fidarti della sola dichiarazione dell'utente "ce li ho tutti collegati": verificalo.

## Precondizioni

Prima di iniziare l'intervista, verifica CONCRETAMENTE (non a parole) i requisiti del sistema, anche quelli che questa skill non usa direttamente — è il primo punto di contatto interattivo, il posto giusto per bloccare l'intero onboarding se manca qualcosa:

1. **Repo del sistema clonato e git funzionante** — verifica DIRETTAMENTE in Claude Code (nessun `tool_search`, non è un connettore di chat): sei dentro un clone di lavoro del repo, `git` risponde, ed esiste un remote configurato (`git remote -v`). È la casa dell'intero sistema — profili, ricerche, valutazioni, candidature, telemetria della routine. Il remote serve perché la routine cloud legge solo ciò che è committato+pushato (vedi passo 6). Se non c'è un remote, dillo e chiedi all'utente di crearlo/collegarlo (repo GitHub sua, nome a scelta) prima del passo 6: i passi 1–4 scrivono in locale e committano, ma senza push la routine non li vedrebbe.
2. **Gmail** — `tool_search` query "Gmail". Necessario alla routine (lettura alert) e a valle per follow-up/bozze.
3. **Indeed** — `tool_search` query "Indeed jobs". Necessario alla routine per la ricerca.
4. **CV disponibile** — chiedilo come primo passo se non è già stato allegato in chat.

Per Gmail/Indeed mancanti: fermati, dì per nome quale manca e perché serve, e chiedi di collegarlo prima di proseguire. Non generare un profilo incompleto "per ora" e non saltare la verifica assumendo che l'utente li abbia già collegati solo perché ha caricato il pacchetto di skill (il pacchetto e i connettori sono due cose diverse, vedi customer journey passi 2 e 3).

**Connettore o scrittura che fallisce a metà flusso**: se un tool call fallisce durante l'intervista (connettore Gmail/Indeed scaduto, permesso revocato) o se la scrittura/commit al passo 4 fallisce, non perdere il lavoro fatto: mostra subito in chat lo stato completo dei dati raccolti fino a quel punto (lo YAML parziale, se già formato), spiega cosa ha fallito e come rimediare, e riprendi ESATTAMENTE dal passo interrotto — non ricominciare l'intervista da capo. In particolare, se la scrittura file al passo 4 riesce ma il commit no, i file sono comunque salvati in locale: ritenta solo il commit.

## Schema di riferimento

Gli schemi dato-agnostici sono in:
- `references/master-profile.schema.yaml`
- `references/search-profile.schema.yaml`

Leggili prima di condurre l'intervista: ogni campo dello schema è una domanda potenziale. Non inventare campi che non sono nello schema; se durante l'intervista emerge un dato utile che non ha posto nello schema, segnalalo all'utente invece di infilarlo a forza da qualche parte — potrebbe voler dire che lo schema va aggiornato (torna al progetto, non decidere da solo).

## Flusso

### 1. Ingestione CV → bozza master-profile

- Chiedi il CV se non presente.
- Estrai dal CV tutto ciò che mappa direttamente sui campi di `master-profile.schema.yaml`: esperienze, progetti, skill tecniche, lingue, formazione, certificazioni.
- Presenta la bozza risultante e chiedi conferma/correzioni prima di proseguire. Un CV può essere ambiguo o incompleto (date mancanti, stack non esplicito) — segnala i buchi invece di indovinare.
- Non chiedere ancora i campi che il CV non può contenere (retribuzione, preavviso, disponibilità): vengono dopo, sono domande dirette non deducibili da un documento.

### 2. Domande su vincoli e preferenze

Copri, in gruppi tematici separati (non tutto insieme):

**Mobilità**
- Disponibilità trasferimento (sì / no / solo alcune aree — e quali)
- Disponibilità remoto (full remote / ibrido / solo sede / indifferente)

**Economico**
- Retribuzione attuale (valore, lordo/netto, periodicità)
- Aspettativa (range, stesse unità)
- Eventuale flessibilità/note

**Contrattuale**
- Preavviso (durata, eventuali vincoli particolari)

**Legale**
- Cittadinanza/e
- Diritto al lavoro per le aree in cui l'utente vuole cercare (non dare per scontato che coincida con la cittadinanza — un permesso di soggiorno, un passaporto UE aggiuntivo, ecc. possono cambiare la risposta)

**Lingue**
- Livello per ciascuna lingua rilevante, e contesto d'uso (lavorativo quotidiano vs solo letto) — serve sia a `master-profile` sia, a valle, a filtrare gli annunci in `search-profile`

Ogni gruppo di domande scrive direttamente nei campi corrispondenti dello schema. Se l'utente salta una domanda o risponde "non so", lascia il campo vuoto/null nello YAML — non riempirlo con un default plausibile.

### 3. Produzione del primo intento di ricerca

A questo punto hai i dati per derivare (non indovinare — derivare, con conferma esplicita) la ricerca. Con D2 la ricerca non è un file unico ma una cartella `searches/` con un `defaults.yaml` condiviso e un file per intento. All'onboarding produci **un solo intento** (l'utente potrà aggiungerne altri dopo, via `job-search-profile`). Le domande NON cambiano: cambia solo dove atterrano le risposte.

Dove atterra cosa (vedi `references/search-profile.schema.yaml`):
- **`searches/defaults.yaml`** (default ereditabili, stabili tra intenti): `esclusioni`, `lingue_annuncio`, `parametri_esecuzione`.
- **`searches/<intent-id>.yaml`** (l'intento): `id` (slug stabile, chiedi/proponi un nome breve — es. `data-engineering-eu` — perché è la chiave che comparirà in log, valutazioni e candidature), `nome` (etichetta leggibile), `stato: attivo`, `creato` (data odierna), più `ruoli_target`, `location_target`, `seniority`, `settori`. All'onboarding l'intento non ha `override` (eredita tutti i defaults); lo si aggiunge solo se in futuro un intento diverge.

I campi da raccogliere (invariati nella sostanza):

- **Seniority**: dagli anni di esperienza e dal tipo di ruoli avuti in `master-profile.esperienze`, proponi un livello (`junior/medio/senior/...`) e chiedi conferma — non scriverlo senza validazione, perché la percezione di seniority dell'utente può differire dal dato grezzo.
- **Ruoli target**: chiedi esplicitamente quali titoli cercare (non dedurli automaticamente dal ruolo attuale — un utente potrebbe voler cambiare ruolo).
- **Location target**: chiedi le aree geografiche di interesse, incrociando con `disponibilita_remoto`/`disponibilita_trasferimento` già raccolti.
- **Esclusioni**: chiedi se ci sono titoli o tipi di contratto da escludere sempre (es. ruoli manageriali, stage) — proponi i default tipici (Head of/Director/VP/C-level, Internship/Traineeship/Stage) ma fai confermare, non assumerli silenziosamente.
- **Settori**: target ed esclusi, se l'utente ha preferenze.
- **Lingue annuncio**: da `master-profile.lingue`, proponi quali lingue sono accettabili per il corpo di un annuncio e quali lo scartano se prevalenti/obbligatorie — richiede una domanda esplicita, perché "so l'inglese" non implica automaticamente "accetto annunci il cui corpo è in inglese ma richiede altra lingua come requisito".
- **Parametri esecuzione**: finestra temporale e max annunci per esecuzione — proponi i default usati nella routine esistente (48 ore, 15 annunci) solo come punto di partenza dichiarato, fai confermare.

### 4. Scrittura nel repo + commit

- Verifica se esistono già i file di profilo (`master-profile.yaml` nella radice, `searches/`): se sono già valorizzati, l'utente ha probabilmente già fatto l'onboarding — chiedi conferma prima di sovrascrivere, non ripartire da zero in silenzio. (Un `master-profile.yaml` vuoto/placeholder o un `searches/` con solo `defaults.yaml` scaffold NON è "già onboardato": procedi.)
- Mostra il contenuto finale all'utente PRIMA di scriverlo. Non scrivere silenziosamente — è un dato che alimenta tutto il resto del sistema (routine, role-fit, cv-tailoring): un errore qui si propaga ovunque.
- Ultimo atto del passo, eseguito da te (l'utente non tocca git — D7): scrivi i file (`master-profile.yaml`, `searches/defaults.yaml`, `searches/<intent-id>.yaml`) e **committa** con un messaggio chiaro (es. `onboarding: master-profile + primo intento <intent-id>`). Il push si fa al passo 6, quando si attiva la routine (prima non serve: nulla legge ancora questi file da remoto).

### 5. Passaggio a job-alert-config (alert LinkedIn/Indeed)

Segui la sequenza del customer journey (punto 4, a→b→c): dopo la scrittura del primo intento in `searches/`, il passo successivo è la configurazione degli alert, PRIMA di attivare la routine — la routine legge alert LinkedIn via Gmail, quindi attivarla senza alert configurati la farebbe partire su una fonte vuota.

- Richiama esplicitamente la skill `job-alert-config` (1.2.1), passandole l'intento appena creato in `searches/`. Non duplicarne la logica qui: quella skill produce le istruzioni su come impostare i campi degli alert su LinkedIn/Indeed (sono dietro login, quindi istruzioni per l'utente, non config programmatica).
- Aspetta conferma esplicita dall'utente che gli alert sono stati effettivamente impostati prima di passare al punto 6. Non proseguire per inerzia.

### 6. Verifica e attivazione della routine

Architettura a **binario unico** (D5): tutto vive in questo repo — i profili (`master-profile.yaml`, `searches/`) scritti al passo 4, e lo strato operativo che la routine scriverà (`source-log/`, `state.json`, staging, digest). Non c'è un secondo storage.

Compiti di questo passo:
- **Push obbligatorio prima di attivare la routine**: la routine cloud gira su un clone del repo e vede SOLO ciò che è stato committato *e pushato*. Esegui tu il push del commit del passo 4 (D7 — l'utente non tocca git). Se al prerequisito 1 mancava il remote, è il momento di risolverlo: fatti dare l'URL della repo GitHub dell'utente, collegala come remote, poi push. Senza questo, la routine partirebbe su un profilo vuoto.
- **Regola di proprietà (ricordala all'utente)**: da qui in poi la routine scrive solo lo strato operativo append-only (log/state/digest/staging); i profili, le valutazioni e le candidature restano scritti dalle sessioni interattive. La routine *legge* i profili e `applications/` (per le scadenze del digest), non li modifica.
- Guida l'attivazione della routine come Claude Code Routine in cloud, dall'app desktop Claude Code (nessun terminale). Spiega i passaggi a livello di cosa cliccare, non assumere che l'utente sappia già come si crea una routine.
- Mostra, a scopo di verifica, i valori committati al passo 4, così l'utente capisce cosa la routine leggerà dal clone.

### 7. Utente operativo

Solo a questo punto l'onboarding è completo: profilo scritto, alert impostati, routine attiva. Dillo esplicitamente all'utente e ricorda dove vivono i due canali con cui interagirà da qui in poi (digest via email, chat per lo Studio). Ricorda anche che i criteri di ricerca si modificano in futuro con la skill `job-search-profile` (senza rifare l'onboarding) e che, dopo ogni modifica, gli alert LinkedIn/Indeed vanno riallineati con `job-alert-config`.

## Cosa NON fare

- Non riempire mai un campo con un valore plausibile ma non confermato dall'utente ("assunzione silenziosa").
- Non usare dati di memoria dell'account per rispondere a domande che l'intervista dovrebbe porre all'utente attivo in quel momento — la skill deve funzionare identica per un utente di cui non sai nulla.
- Non saltare la conferma finale prima della scrittura dei file nel repo.
- Non inventare campi fuori schema: se serve un campo nuovo, fermati e segnalalo invece di forzarlo in un campo esistente.
