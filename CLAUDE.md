# job-hunter — contesto permanente per l'agente

Assistente IA per la ricerca di lavoro. Questo file riassume le decisioni
chiuse e il funzionamento del sistema per orientarsi in ogni sessione; per
il dettaglio dei singoli moduli vedi le skill in `.claude/skills/*/SKILL.md`.

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
- D2 Profilo unico con intenti annidati: searches/<intento>.yaml + searches/defaults.yaml
  (+ searches/alerts-registry.yaml: registro degli alert email realmente creati →
  chiave canonica keywords+geoId per attribuire gli annunci alla ricerca giusta).
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

Fonti dati (decisione post-prototipo 2026-07): oltre a Indeed/alert, la routine
legge le career page delle aziende in searches/companies.yaml con adapter
A (ATS noto) o B (API JSON scoperta via probe) — vedi
.docs/analisi/analisi-career-pages-aziende-fusione-cross-fonte_2026-07-12.md.
Lo scraping HTML/headless (fascia C) resta deliberatamente fuori: le aziende C
sono tracciate nel digest e candidabili via link diretto, non lette.

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
del digest e le scritture sui soli path operativi; i tool MCP dei connettori
(Gmail/Indeed) hanno ID legati all'account — dove presenti in allowlist la
routine li usa senza conferma, in un clone fresco vanno approvati al
collegamento — così la routine gira senza conferme umane. La rete di sicurezza è l'hook
`.claude/hooks/protect-files.sh`: nelle sessioni con `JOB_HUNTER_ROUTINE=1`
(la routine cloud la imposta) blocca ogni scrittura su master-profile,
searches/, role-fit/, applications/.

## Documenti di riferimento
Questa è la versione distribuibile del sistema: non include la storia di
design interna né gli strumenti di sincronizzazione del repo sorgente. Le
fonti valide per orientarti sono questo file, il `README.md`, gli schemi in
`.claude/skills/*/references/` e i runbook operativi in `docs/`.

## Anti-drift documentale — README e contratti

Ogni fix a un contratto, a uno schema o al comportamento della routine aggiorna
la documentazione **nello stesso commit**, mai in un giro successivo. Dopo ogni
modifica che aggiunge, rimuove o cambia funzionalità visibili, campi o formati:
1. Controlla se `README.md` e i contratti in `.claude/skills/*/references/`
   descrivono ancora il comportamento reale — prosa E blocchi d'esempio (gli
   esempi sono ciò che una sessione futura copia più volentieri della prosa).
2. Se non lo descrivono, o lo descrivono in modo errato, aggiornali **prima di
   chiudere il task**.