---
name: cv-tailoring
description: >-
  Genera CV su misura in PDF, cover letter e messaggio diretto al recruiter
  a partire dal master-profile del sistema Job Hunter e da una job
  description. Usa SEMPRE questa skill quando l'utente dice: "fammi il CV",
  "fammi il CV per questa posizione", "tara/adatta il CV alla JD", "scrivi
  la cover letter", "preparami il messaggio per il recruiter",
  "candidiamoci a X", "prepara i materiali per la candidatura" — anche se
  chiede solo uno dei tre artefatti. Il CV esce sempre come PDF renderizzato
  server-side nel code tool; i dati vengono SOLO dal master-profile nel repo,
  mai inventati.
---

# cv-tailoring

Modulo 2.2 del progetto Job Hunter. Produce fino a tre artefatti coerenti tra loro per una candidatura: **CV in PDF**, **cover letter**, **DM al recruiter**. Stesso posizionamento su tutti e tre, lunghezza diversa per canale. Se l'utente ne chiede uno solo, produci quello — ma tienili concettualmente allineati se poi chiede gli altri.

## Precondizioni di readiness

Prima di produrre qualsiasi materiale, verifica il prerequisito minimo di questa skill: esiste `master-profile.yaml` nella radice del repo ed è non vuoto. È l'unica fonte dei contenuti (vedi Regola d'oro): senza, non c'è nulla da tailorare e fabbricare è vietato. Se manca o è vuoto, l'utente non ha ancora fatto l'onboarding: non procedere e non assumere un profilo. Fermati e reindirizza ad `agent-config` con una frase specifica al gap reale, non un generico "profilo non trovato", es.: "Per generarti un CV su misura mi serve il tuo profilo — esperienze, risultati, competenze — che non risulta ancora configurato: vuoi che partiamo dall'onboarding per crearlo adesso?". (È la stessa condizione già citata in "Input → master-profile": qui è la guardia d'ingresso esplicita, non una nuova regola.)

## Regola d'oro (non negoziabile)

Il contenuto viene ESCLUSIVAMENTE dal `master-profile`. Il tailoring è **selezione, riordino ed enfasi** — mai fabbricazione: niente esperienze gonfiate, competenze aggiunte, date ritoccate, risultati inventati. I gap rispetto alla JD non si nascondono con vaghezza: si gestiscono con onestà nel posizionamento (nella cover si può argomentare l'affinità; nel CV semplicemente non si mente). Se il master-profile non basta per una sezione che la JD renderebbe importante, dillo all'utente: la soluzione è aggiornare il profilo (via `agent-config`, o correggendo `master-profile.yaml` nel repo), non improvvisare.

## Input

1. **master-profile** — `master-profile.yaml` dalla radice del repo (in sessione Claude Code è un file locale; nessun `tool_search`). Se manca o è vuoto → onboarding non fatto → rimanda ad `agent-config` e fermati.
2. **JD** — stesse regole di intake di `role-fit`: LinkedIn sempre incollata a mano, Indeed via connettore/alert Gmail, altrimenti testo incollato. Senza JD chiedi: "per quale posizione?" (un CV "generico" è possibile solo se l'utente lo chiede esplicitamente — in quel caso salta la parte di tailoring e usa il profilo completo).
3. **role-fit-output, se esiste** — cerca in `role-fit/` nel repo una valutazione per la stessa azienda+ruolo. Se c'è, RIUSALA: i `match` diventano i punti da enfatizzare, i `gaps` con relativo peso guidano cosa argomentare in cover e cosa non promettere. Se non c'è, non è bloccante: puoi proporre di fare prima un `role-fit` (utile ma non obbligatorio) o procedere direttamente.

## Flusso

### 1. Posizionamento (una frase, prima di tutto)

Formula in una frase chi è l'utente PER QUESTA posizione (es. "profilo dati con N anni su <stack affine a quello richiesto>, forte su <requisito core della JD>"). È il filo che tiene insieme CV, cover e DM. Mostralo all'utente e fallo confermare prima di costruirci sopra: se il posizionamento è sbagliato, tutto il resto lo sarà.

### 2. Selezione contenuti per il CV

- **Esperienze**: tutte in ordine cronologico inverso (i buchi insospettiscono più dei ruoli poco affini), ma bullet ricalibrati: per le esperienze affini alla JD 3-4 bullet con i `risultati_quantificabili` in testa; per le altre 1-2 bullet essenziali.
- **Skill**: raggruppate e ordinate per rilevanza rispetto alla JD; le skill richieste dalla JD e presenti nel profilo vanno visibili subito. Le skill richieste e ASSENTI non compaiono (regola d'oro). Includi lo strato AI-adoption se il profilo lo valorizza e la JD/l'azienda lo rende rilevante.
- **Progetti/certificazioni**: solo se rilevanti per la JD, altrimenti la sezione si omette.
- Target: 1 pagina fino a ~6-8 anni di esperienza, massimo 2.

### 3. Bozza in chat → conferma

Mostra la bozza dei CONTENUTI (posizionamento, bullet riscritti, ordinamento) in chat prima del rendering. È il punto dove l'utente corregge enfasi e formulazioni. Non renderizzare prima della conferma.

### 4. Render PDF (pipeline adattiva, MAI hardcodata)

Il contratto è: **l'utente vuole il suo CV in PDF**. Il come si adatta all'istanza:

- **Default** (utente senza pipeline propria): compila `assets/cv-template.html` con i contenuti confermati (sostituisci i placeholder `{{...}}`, duplica i blocchi BEGIN/END per le voci ripetute, rimuovi le sezioni vuote), poi nel code tool: `pip install weasyprint --break-system-packages` e renderizza in PDF. Fallback se weasyprint non è installabile nel sandbox corrente: `reportlab` (tipicamente preinstallato) costruendo un layout equivalente a codice. Ultimo fallback: consegna il file HTML pronto per "stampa → salva come PDF" dal browser, dicendolo esplicitamente — mai consegnare nulla in silenzio.
- **Utente con formato proprio**: se l'utente ha un suo sorgente/pipeline (es. un sorgente LaTeX, un suo template), usalo per la SUA istanza: aggiorna quel sorgente con i contenuti tailorati e compila con il motore adatto disponibile nel sandbox (es. `pdflatex`). Chiedi, non assumere — e non promuovere il metodo di un utente a standard della skill.
- Il PDF finale va salvato in output e presentato all'utente con il tool di presentazione file. Controlla il risultato (una pagina? testo tagliato? placeholder residui `{{`?) prima di presentarlo.

### 5. Cover letter

250-350 parole, stesso posizionamento del CV. Struttura: aggancio specifico alla posizione/azienda (mai template-vuoto "sono entusiasta di candidarmi") → 2 match concreti con evidenze dal profilo → gestione onesta del gap più rilevante SE argomentabile (affinità, velocità di apprendimento dimostrata — senza scuse né bugie) → chiusura con disponibilità. Lingua: quella della JD, salvo diversa richiesta.

### 6. DM al recruiter

60-120 parole: il posizionamento compresso. Chi sei in mezza frase, il match più forte, una chiusura che chiede il passo successivo. Niente riassunto del CV: è un messaggio LinkedIn, non una cover corta. Stessa lingua della cover.

### 7. Diff-report master↔generato (D3 — obbligatorio prima della consegna)

Insieme ai materiali produci SEMPRE il **diff-report**: lo stesso controllo di
veridicità che il contratto staging impone ai materiali pre-generati dal batch
(`job-watch/references/staging-schema.md`, sezione `diff-report.md`) — qui vale
per il percorso interattivo, che produce i materiali davvero spediti. Formato:
una tabella che elenca ogni scostamento dal `master-profile`, classificato come
**riordino** / **riformulazione** / **omissione** / **⚠ possibile aggiunta di
contenuto**, chiusa dalla verifica esplicita "Contenuto aggiunto (⚠): nessuno"
(se non è vera, torna al passo 2: c'è contenuto da rimuovere o da far
confermare come aggiunta legittima del profilo). È ciò che rende la revisione
D3 un controllo mirato di 2 minuti invece di una rilettura integrale.

- **Se la candidatura esiste** in `applications/<id>/`: salva il report come
  `applications/<id>/materials/diff-report.md`, nello stesso commit dei materiali.
- **Se la candidatura non esiste ancora**: mostralo in chat insieme ai materiali
  (stesso trattamento degli altri artefatti in quel percorso — niente cartelle
  orfane).

### 8. Consegna e destinazioni

Con D8 i materiali hanno una **destinazione canonica nel repo**: la cartella `applications/<id>/materials/` della candidatura corrispondente. Non è più una micro-scelta "copia sì/copia no": la casa esiste, salvarci i materiali è parte del flusso.

- **Se la candidatura esiste già** in `applications/<id>/` (l'utente arriva da lì, o è già stata promossa): scrivi i materiali in `applications/<id>/materials/` (`cv.md` + il PDF renderizzato; `cover-letter.md`; `recruiter-dm.md` — i sorgenti .md diffano in git, il PDF è l'artefatto spedito) e **committa** tu (D7). Presenta comunque il PDF in chat con il tool di presentazione file. Se utile, chiedi ad `application-tracker` di annotare nell'evento che i materiali sono pronti.
- **Se la candidatura NON esiste ancora**: PROPONI di crearla (promozione via `application-tracker`, 2.3) così i materiali hanno dove atterrare; se l'utente non vuole ancora tracciarla, consegna solo in chat (PDF presentato, cover/DM come testo) senza salvare nel repo — non creare una cartella `applications/` orfana d'ufficio.
- Cover e DM: testo in chat oltre che (se la candidatura esiste) in `materials/`. Se l'utente vuole spedire, la bozza email si prepara via Gmail (bozza, MAI invio diretto).
- Da chat claude.ai pura il connettore GitHub è read-only: puoi generare e mostrare tutto, ma NON scrivere in `applications/` — dichiaralo e rimanda il salvataggio a una sessione Claude Code.

## Cosa NON fare

- Non inventare NULLA che non sia nel master-profile (vale per CV, cover e DM allo stesso modo).
- Non hardcodare un motore di render come unico possibile: la gerarchia è weasyprint → reportlab → HTML consegnato, più la pipeline propria dell'utente se esiste.
- Non renderizzare senza la conferma dei contenuti (passo 3).
- Non produrre tre artefatti con posizionamenti diversi: se l'utente cambia il posizionamento su uno, riallinea gli altri.
- Non consegnare materiali senza il diff-report master↔generato (passo 7): è il presidio D3, non un extra.
- Non inviare mai email/messaggi: solo bozze.
