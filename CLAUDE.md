# job-hunter — contesto permanente per l'agente

Assistente IA per la ricerca di lavoro. Vedi `.docs/` per la storia completa
delle decisioni di design; qui solo il riepilogo che serve per orientarsi
in ogni sessione.

## Requisiti non negoziabili
1. Onboarding guidato via wizard conversazionale adattivo — niente config manuale.
2. Profilo del candidato persistente e cumulativo, mai ricostruito da zero.
3. Generazione di CV su misura per ogni offerta rilevante.
4. Analisi del gap di competenze con suggerimenti concreti.

## Apertura sessione — sistema non ancora configurato
Se all'apertura di una sessione il repo risulta privo di profilo configurato
(nessun `master-profile.yaml`, o file vuoto) **e** l'utente non ha ancora
dichiarato cosa vuole fare, proponi tu **proattivamente** l'onboarding
(`agent-config`) invece di aspettare che scelga uno skill a caso e che quello
fallisca. Frase specifica al gap, non generica: es. "Vedo che il sistema non è
ancora configurato — non c'è ancora un profilo. Vuoi che partiamo
dall'onboarding per crearlo? Bastano pochi minuti e una copia del tuo CV.".
Questo è un comportamento di **apertura-sessione**, distinto dalla guardia
per-skill "Precondizioni di readiness" (presente in ogni skill funzionale), che
copre invece il caso in cui l'utente salti dritto a uno skill specifico a metà
conversazione. Se l'utente ha già espresso un intento chiaro, rispettalo e non
anteporre l'onboarding — la guardia per-skill farà comunque da rete se il
prerequisito manca.

## Decisioni di design chiuse (D1-D8) — non riaprirle
- D1 Utente personale-first; condivisione futura è un problema rimandato.
- D2 Profilo unico con intenti annidati: searches/<intento>.yaml + searches/defaults.yaml.
- D3 Revisione umana obbligatoria prima di ogni invio; nessun invio autonomo.
- D4 Batch: raccolta + valutazione + pre-generazione CV in staging; invio manuale.
- D5 Storage: questo repo (file + git), non Drive. La routine scrive solo lo
  strato operativo (log/state/digest/staging); le sessioni interattive scrivono
  profili e candidature.
- D6 Log operativo: JSONL con rotazione mensile in source-log/YYYY-MM.jsonl.
- D7 Interazione in Claude Code Desktop; regola fissa: nessun flusso richiede
  all'utente di aprire un file o toccare git a mano — lo fa sempre l'agente.
- D8 Tracker candidature repo-first: lo stato vive in applications/<id>/ nel
  repo (application.yaml + events.jsonl), non su Todoist. La routine legge
  applications/ (scadenze/pipeline per il digest) ma non lo scrive mai.

Fatto tecnico: il connettore GitHub in chat claude.ai è di sola lettura — le
scritture avvengono solo in sessione Claude Code.

Privacy: questo è il branch **template**, pensato per essere pubblico e
per partenza privo di qualsiasi dato personale. **Appena completi
l'onboarding**, `master-profile.yaml`, `searches/`, `applications/` e lo
strato operativo inizieranno a contenere i tuoi dati reali (email,
telefono, RAL, aziende): da quel momento tieni **privato** il tuo repo.
Nulla rileva automaticamente un cambio di visibilità, quindi verificalo
tu. Per cancellare un dato personale da tutta la storia git (non solo
dall'HEAD), vedi il runbook `docs/runbook-cancellazione-gdpr.md`.

Ancora aperto, deliberatamente: fonti dati (canali legittimi vs scraper terzi)
— da testare in prototipo, non deciso a tavolino.

## Skill disponibili
Otto skill sotto `.claude/skills/`: agent-config, job-search-profile,
job-alert-config, job-alert-tuner, role-fit, cv-tailoring, application-tracker,
job-watch (la routine batch di sourcing — Modulo 1.3).

## Strato operativo (scritto solo dalla routine, regola di proprietà D5)
La routine `job-watch` produce: `source-log/YYYY-MM.jsonl` (telemetria),
`source-log/runs.jsonl` (ledger delle run: riga di start committata subito, riga
di end con esito `ok|parziale|fallita` — una start orfana = run morta a metà,
diagnosticabile dal solo repo, F8), `state.json` (dedup), `staging/<id>/`
(offerte pre-lavorate in attesa di revisione umana — contratto D4),
`digests/YYYY-MM-DD.md` + consegna Gmail (il digest, con sezioni obbligate
scadenze+pipeline; **nella routine cloud la consegna è una bozza** — l'SMTP
diretto fallisce nel sandbox, l'invio reale vale solo per un'eventuale routine
Desktop locale), `PIPELINE.md` (vista funnel rigenerabile). A ogni run applica
anche una **policy di retention** (potatura di `seen` vecchio, digest/staging
scartati oltre soglia — F9). Contratti in `.claude/skills/job-watch/references/`.
Config operativa (non criteri di ricerca) in `routine-config.yaml`: etichetta
Gmail e cadenza dichiarata, scritti dalle sessioni interattive, letti dalla
routine (F5).
Eccezione dichiarata: `PIPELINE.md` è co-scritto (lo rigenera anche
`application-tracker` su richiesta) — chi lo tocca lo rigenera SEMPRE
integralmente da `applications/`, mai merge manuale; in conflitto vince la
rigenerazione più recente. Mai fonte di verità.
Enforcement D5: `.claude/settings.json` (committato) allowlista git, lo script
del digest, i tool MCP della routine e le scritture sui soli path operativi —
così la routine gira senza conferme umane. La rete di sicurezza è l'hook
`.claude/hooks/protect-files.sh`: nelle sessioni con `JOB_HUNTER_ROUTINE=1`
(la routine cloud la imposta) blocca ogni scrittura su master-profile,
searches/, role-fit/, applications/.

## Ridistribuzione — branch `template` (leggi prima di toccarne i pezzi)
Esiste un branch `template` pubblicabile, privo di qualsiasi dato personale,
generato da `main` come **snapshot a radice orfana** (né merge né rebase: la
storia di `main` è satura di PII per costruzione). A ogni push su `main` il
workflow `.github/workflows/sync-template.yml` ricostruisce lo snapshot e apre
una PR verso `template` (non push diretto). Meccanismo e regole di estensione in
`ARCHITETTURA-TEMPLATE.md`; i pezzi vivono in `templating/` +
`scripts/sync-template.sh`. Regola pratica: se aggiungi una cartella con dati
personali aggiornala in `templating/exclude-paths.txt` (+ scan-identifiers se
introduci nuovi identificatori); se aggiungi una skill funzionale, aggiungile la
guardia di readiness e aggiorna la tabella in `ARCHITETTURA-TEMPLATE.md`. Lo
scan è fail-closed: un dato personale sfuggito blocca il sync, non lo espone.

## Documenti di riferimento (contesto, non vincoli aggiuntivi)
`.docs/analisi-esplorativa-job-search-ai_FABLE-01.md` — analisi architetture (fase 1)
`.docs/lista-revisione-skill-job-hunter.md` — lista di revisione da applicare (fase 4)
`.docs/revisioni/` — audit di miglioria del sistema (fase 5+)
Consultali per il "perché" dietro una decisione; questo file resta la fonte
delle decisioni valide da rispettare.

**Due cartelle documentali, scopi distinti (non consolidarle)**: `.docs/`
(nascosta) è la storia di design e gli audit interni di *questa* istanza —
sempre esclusa dal branch `template` (`templating/exclude-paths.txt`), mai
spedita a un futuro utente. `docs/` (visibile) contiene solo materiale
generico pensato per essere spedito ai futuri utenti del template (es. i
runbook operativi come `docs/runbook-cancellazione-gdpr.md`): niente dati
personali, niente storia di design specifica di questa istanza.

## Anti-drift documentale — README e contratti

Ogni fix a un contratto, a uno schema o al comportamento della routine aggiorna
la documentazione **nello stesso commit**, mai in un giro successivo. Dopo ogni
modifica che aggiunge, rimuove o cambia funzionalità visibili, campi o formati:
1. Controlla se `README.md` e i contratti in `.claude/skills/*/references/`
   descrivono ancora il comportamento reale — prosa E blocchi d'esempio (gli
   esempi sono ciò che una sessione futura copia più volentieri della prosa).
2. Se non lo descrivono, o lo descrivono in modo errato, aggiornali **prima di
   chiudere il task**.