# job-hunter — template

Assistente IA personale per la ricerca di lavoro, costruito come pacchetto di
**Claude Skills** su un **unico repository GitHub**. Onboarding guidato, profilo
persistente e cumulativo, valutazione delle offerte, CV su misura e tracking
delle candidature — tutto in file versionati, ispezionabili e correggibili.

> **Questo è il branch `template`.** Non contiene alcun dato personale: è la
> base pulita da clonare per far partire *il tuo* sistema. Ti bastano una
> conversazione di onboarding e il tuo CV — nessun file da configurare a mano.

## Cosa fa il sistema

| Skill | Ruolo |
|---|---|
| `agent-config` | **Onboarding**: dal tuo CV al primo intento di ricerca, fino all'attivazione della routine. **Parti da qui.** |
| `job-search-profile` | Editor delle ricerche dopo l'onboarding: intenti, defaults/override, ciclo di vita (crea/pausa/archivia). |
| `job-alert-config` | Istruzioni passo-passo per impostare gli alert LinkedIn/Indeed dai tuoi intenti. |
| `job-alert-tuner` | Metriche di tuning dal `source-log`: volume, overlap, rumore per ricerca. |
| `role-fit` | Valuta il fit tra una JD e il tuo profilo; salva un esito strutturato. |
| `cv-tailoring` | Genera CV (PDF), cover letter e DM al recruiter dal tuo profilo; mai fabbrica dati. |
| `application-tracker` | Tracker delle candidature in `applications/`: promozione, avanzamenti, follow-up, risposte via Gmail. |
| `job-watch` | La routine batch: raccoglie, deduplica, filtra, valuta, pre-genera i materiali in staging e manda il digest. |

## Come iniziare (da zero)

1. **Clona questo branch** e aprilo in **Claude Code Desktop**:
   ```bash
   git clone --branch template <url-del-tuo-fork> job-hunter
   ```
   Consiglio: crea un **tuo repository privato** dal template (vedi *Privacy*
   più sotto) e clona quello.

2. **Apri la cartella in Claude Code Desktop.** Non serve conoscere git né
   aprire file a mano: lo fa sempre l'agente.

3. **Avvia l'onboarding parlando in chat**, con frasi naturali. Non devi
   nominare nessuna skill: basta l'intento. Esempi:
   > *"iniziamo a configurare il sistema di ricerca lavoro"*
   > *"aiutami a impostare il job hunting, ecco il mio CV"*

   Si attiva `agent-config`, che ingerisce il CV, ti fa qualche domanda su
   vincoli e preferenze (trasferimento, remoto, retribuzione, lingue…) e scrive
   `master-profile.yaml` + il tuo primo intento in `searches/`. **Nessun campo
   va compilato a mano.**

4. **Imposta gli alert e attiva la routine** quando l'onboarding te lo propone
   (istruzioni generate da `job-alert-config`).

Da lì in poi lavori in chat con frasi naturali: *"valuta questo annuncio"*,
*"fammi il CV per questa posizione"*, *"mi sono candidato a X"*, *"a che punto
sono le candidature?"*.

### Il sistema ti guida se salti l'onboarding

Ogni skill funzionale ha una **guardia di readiness**: se la usi prima di aver
configurato il suo prerequisito (es. chiedi un CV su misura senza aver ancora un
profilo), la skill **non fallisce e non inventa** — riconosce cosa manca e ti
reindirizza al passo giusto con un messaggio specifico. Se apri una sessione su
un sistema non ancora configurato, l'agente stesso ti propone l'onboarding. Non
puoi "romperlo" partendo dal punto sbagliato.

## Layout del repo

```
job-hunter/
├─ master-profile.yaml   # CHI sei (creato dall'onboarding — assente nel template)
├─ routine-config.yaml   # config operativa della routine (etichetta Gmail, cadenza)
├─ searches/             # COSA cerchi (vuota nel template; onboarding la popola)
├─ role-fit/             # valutazioni JD↔profilo (vuota nel template)
├─ applications/         # candidature repo-first (vuota nel template)
├─ source-log/           # telemetria della routine (vuota nel template)
├─ staging/              # offerte pre-lavorate in attesa di revisione (vuota)
├─ digests/              # digest generati (vuota nel template)
├─ scripts/              # utility (es. consegna digest: SMTP se possibile, altrimenti bozza)
├─ docs/                 # runbook operativi (es. cancellazione GDPR)
├─ .claude/skills/       # le skill del sistema
└─ CLAUDE.md             # contesto permanente per l'agente
```

Le cartelle operative arrivano **vuote** (un `.gitkeep` ne mantiene la
struttura): si riempiono man mano che usi il sistema.

## Cosa serve collegare

- **Claude Code Desktop** (le scritture su file + git avvengono qui). Richiede
  un **piano Claude a pagamento** (o accesso API a consumo): il ciclo completo
  — onboarding, routine autonoma, valutazioni, generazione CV — usa capacità
  agentiche che il tier gratuito di claude.ai non copre, ed è comunque
  sola-lettura sul connettore GitHub (non può scrivere/committare). Mettilo in
  conto prima di iniziare, non a metà onboarding.
- Un **connettore Indeed** e un **connettore Gmail** (per il sourcing e per
  leggere gli alert / preparare bozze). Li colleghi dalle impostazioni
  connettori; l'onboarding ti dice quando servono. Nota: l'allowlist in
  `.claude/settings.json` non elenca ID di connettore — dipendono dal tuo
  account e vengono approvati quando colleghi i tuoi.

## Le tre cose che restano sempre manuali (per costruzione)

1. **Impostare gli alert** LinkedIn/Indeed (una tantum, dietro login).
2. **Inviare** candidature e follow-up (revisione umana obbligatoria).
3. **Promuovere** un'offerta a candidatura (nessuna candidatura nasce da sola).

Tutto il resto — sourcing, valutazione, pre-generazione, tracking delle scadenze
— è automatico.

## Privacy

Appena completi l'onboarding, il repo inizia a contenere **dati personali reali**
(email, telefono, retribuzione, aziende a cui ti candidi). **Tieni privato il tuo
repo.** Nulla rileva automaticamente un cambio di visibilità: verificalo tu. Per
cancellare un dato personale da *tutta* la storia git (non solo dall'HEAD), vedi
`docs/runbook-cancellazione-gdpr.md`.

## Decisioni di design

Le decisioni chiuse che vincolano il sistema (D1–D8) sono in
[`CLAUDE.md`](CLAUDE.md): utente personale-first, profilo unico con intenti
annidati, revisione umana obbligatoria prima di ogni invio, batch in staging con
invio manuale, storage nel repo, log JSONL mensile, interazione in Claude Code
Desktop, tracker candidature repo-first.
