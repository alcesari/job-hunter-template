# entity-resolution — contratto della fusione cross-fonte (job-watch, passo 5-bis)

Contratto operativo del matcher che riconosce quando due annunci di fonti
diverse sono la **stessa posizione reale**. È lo strato che alimenta
`position_id` + `sources[]` nello staging (`references/staging-schema.md`). Vive
a **valle** del source-log e del dedup per-fonte: non tocca mai `annuncio_id`
né `state.json`. Questo file È la fonte di verità delle soglie e delle liste —
la routine (e il filtro location del passo 4) le legge da qui, non dal
documento di analisi in `.docs/` (che è storia di design, esclusa dal template).

Origine: §2 del documento
`.docs/analisi/analisi-career-pages-aziende-fusione-cross-fonte_2026-07-12.md`.
I valori numerici sono **default di partenza dichiarati, regolabili in Fase 2**
sui falsi positivi/negativi osservati; la distinzione qualitativa (azienda come
gate rigido, tre esiti, conservatività) è la parte non negoziabile.

## Rischio asimmetrico (la ragione della conservatività)

- **Falso positivo** (fondere due posizioni diverse) = **grave**: l'utente vede
  una posizione sola e ne perde una reale; la valutazione di fit si sporca
  mescolando due JD. È il rischio da minimizzare.
- **Falso negativo** (non fondere due annunci della stessa posizione) = **lieve**:
  l'utente vede due card per la stessa cosa (rumore, non perdita) — lo stesso
  difetto che il sistema già tollera col title-drift.

Quindi: fondi solo con evidenza forte; nel dubbio lascia separato e, al più,
segnala `suspect` per la revisione umana.

## Ambito di applicazione: intra-run e cross-run

L'algoritmo sotto è lo STESSO in entrambi i casi (stesse soglie, stesso gate,
stessa tabella alias) — cambia solo il **pool di candidati** con cui si
confronta un'offerta sopravvissuta:

- **Intra-run**: il pool sono le altre offerte sopravvissute della stessa run
  (caso originale — es. la stessa posizione trovata su Indeed e career_page
  nello stesso giro).
- **Cross-run**: il pool sono anche il `position_id` (+ azienda/titolo/
  location) delle voci `staging/*/staging.yaml` con `status: pending` di run
  **precedenti**, e delle voci `applications/*/application.yaml` (qualunque
  stato). Copre il caso — verificato utile: un'azienda trovata oggi via
  career_page, la cui stessa posizione ricompare su LinkedIn/Indeed due giorni
  dopo in una run successiva — senza cross-run finirebbe duplicata come
  seconda voce staging invece di essere riconosciuta come la stessa.

Esiti cross-run:
- `merge` contro una `pending` esistente → **quella voce riceve la fonte
  nuova** in append a `sources[]` (mai una seconda cartella staging); si
  riapplica la merge per-campo (sotto) e si ricalcolano `primary_source`/
  `preferred_apply_channel` se la fonte vincente cambia.
- `merge` contro una voce già in `applications/` → **non si crea nulla in
  staging**: la routine segnala nel digest che una posizione già candidata è
  ricomparsa su una fonte nuova (con link alla candidatura), per lasciare
  alla revisione umana la decisione (es. ri-candidarsi su un canale diverso
  se la prima è stata rifiutata).
- `suspect` (in entrambi i casi) → si crea/lascia la voce separata con
  `possible_duplicate_of` valorizzato, stessa logica dell'intra-run.

`sources[].annuncio_id` resta sempre la chiave per-fonte di
`state.json`/source-log, sia che la fonte sia stata aggiunta alla creazione
sia a run successive: la fusione cross-run non tocca mai quello strato,
esattamente come l'intra-run (vedi Invarianti in `staging-schema.md`).

## Algoritmo (a soglie, niente ML)

Un candidato-match tra due annunci (o tra un'offerta e una voce staging/
application esistente, nel caso cross-run) si valuta in quest'ordine:

1. **Gate azienda (obbligatorio, rigido).** Slug azienda uguale, oppure uguale
   dopo la normalizzazione delle forme societarie (sotto). Azienda diversa →
   **mai fondere** (`distinct`), qualunque cosa dicano titolo e location.
2. **Location compatibile.** Uguale slug, oppure una inclusa nell'altra secondo
   la tabella alias, oppure almeno un token remote (sotto). **Location assente
   (null) su uno dei due → NON è "compatibile per default": mai `merge`** — al
   più `suspect`, di norma `distinct` (stessa conservatività del gate: l'assenza
   di dato non è prova di identità). Location incompatibili con titolo identico
   = due sedi diverse della stessa apertura → `distinct` (due candidature).
3. **Similarità titolo** sopra soglia (metrica sotto).
4. **Tie-break su descrizione** (solo quando 1–3 sono al limite): vedi matrice.

## Metrica di similarità titolo

`token_set_ratio` (à la rapidfuzz: similarità di edit sui token unici ordinati,
insensibile all'ordine delle parole), scala 0–1, sul titolo **normalizzato**:
slug esistente + rimozione dei suffissi titolo (sotto) + rimozione della
seniority ridondante (`junior|senior|mid|medior`) SOLO se presente in uno solo
dei due titoli.

**Normalizzazione condivisa**: la stessa regola di normalizzazione titolo è
usata anche dal **filtro di rilevanza ruolo del passo 4** per il canale
`career_page` (`job-watch/SKILL.md`, §4) — un'unica regola, non due. Lì serve a
estrarre i token di ruolo distintivi dai `ruoli_target` e a confrontarli col
titolo dell'offerta; qui a confrontare due titoli tra loro. La normalizzazione
è la stessa; l'uso a valle differisce.

## Matrice di decisione (si valuta solo se il gate azienda è passato)

| Location | Similarità titolo | Esito |
|---|---|---|
| compatibile | ≥ 0.90 | `merge` |
| compatibile | 0.75 – 0.89 | `suspect` → tie-break descrizione: se disponibile per entrambe e `token_set_ratio(desc) ≥ 0.80` (primi 1500 caratteri normalizzati) → `merge`, altrimenti resta `suspect` |
| compatibile | < 0.75 | `distinct` |
| incompatibile / una null | qualsiasi | `distinct` (mai fondere sedi diverse o su location mancante) |

Esiti:
- `merge` → un solo record staging con `sources[]` multiplo + merge per-campo.
- `suspect` → record separati, ma `possible_duplicate_of` valorizzato col
  `position_id` dell'altro, per l'occhio umano.
- `distinct` → separati, nessuna annotazione.

## Normalizzazione forme societarie (gate azienda) — lista chiusa iniziale

Suffissi da rimuovere (case-insensitive, con o senza punti, solo se in coda al
nome): `s.r.l.`, `srl`, `s.r.l.s.`, `srls`, `s.p.a.`, `spa`, `s.n.c.`, `snc`,
`s.a.s.`, `sas`, `s.c.a r.l.`, `scarl`, `società benefit`, `gmbh`, `ag`, `bv`,
`b.v.`, `nv`, `n.v.`, `sarl`, `sa`, `ltd`, `limited`, `llc`, `inc`, `inc.`,
`corp`, `co.`, `plc`, `group`, `holding`, `italia`, `italy`.

**Quattro suffissi rischiosi** — `group`, `holding`, `italia`, `italy`: possono
distinguere entità legali diverse ("Generali Italia SpA" ≠ "Generali Group").
Si rimuovono per il *matching*, ma il nome completo resta nel record; e se due
annunci matchano SOLO grazie alla rimozione di uno di questi quattro, l'esito
si **declassa da `merge` a `suspect`**. Lista estendibile: ogni aggiunta va
messa QUI, non hardcodata nel codice.

## Suffissi di titolo da rimuovere prima del confronto (lista aperta)

Testo tra parentesi in coda (`(Healthcare Platform)`), `in presenza`,
`da remoto`, `- remote`, `- hybrid`, `- ibrido`, `m/f/d`, `(m/w/d)`, `f/m/x`,
un trailing location che duplica il campo location.

## Tabella alias location IT/EU (compatibilità gerarchica; `⊂` = incluso in)

Usata sia dal matcher (passo 5-bis) sia dal **filtro location del passo 4** per
il canale `career_page` — un'unica tabella, nessun duplicato.

| Alias / città | Compatibile con |
|---|---|
| `milano` | `lombardia`, `italia` |
| `roma` | `lazio`, `italia` |
| `torino` | `piemonte`, `italia` |
| `bologna` | `emilia-romagna`, `italia` |
| `firenze` | `toscana`, `italia` |
| `napoli` | `campania`, `italia` |
| `venezia`, `padova`, `verona`, `mogliano-veneto`, `treviso` | `veneto`, `italia` |
| `genova` | `liguria`, `italia` |
| `amsterdam` | `paesi-bassi`, `netherlands`, `north-holland` |
| token remote: `remote`, `remoto`, `full-remote`, `smart-working`, `da-remoto` | **qualsiasi** location |
| token ibrido: `hybrid`, `ibrido` | compatibile con la città/regione che lo accompagna |
| equivalenze EN→IT: `milan`→`milano`, `rome`→`roma`, `turin`→`torino`, `florence`→`firenze`, `naples`→`napoli`, `venice`→`venezia`, `italy`→`italia` | le career page espongono spesso i nomi in inglese: normalizza prima di confrontare |

Regole: il confronto location passa se gli slug sono uguali, o se uno è
compatibile con l'altro secondo la tabella, o se almeno uno è un token remote.
Se la location elenca **più sedi** (es. Bending Spoons "Milan (Italy), Madrid
(Spain), Warsaw (Poland)"), basta che **UNA** sia compatibile. La tabella copre
le location degli intenti attivi di oggi (Milano, Roma, Remote Italia, Remote
EU): si estende quando un intento aggiunge location nuove, non preventivamente.

## Politica di merge dei campi (solo per gli esiti `merge`)

Regola deterministica, per-campo. La fusione **non genera mai testo nuovo**:
sceglie tra valori esistenti e li accosta con attribuzione, mai sintetizza.

| Campo | Regola |
|---|---|
| `company`, `location` | dalla fonte col dato più completo; conflitto reale → non si era fusi a monte |
| Descrizione JD | tieni **la più lunga/ricca** come corpo per il fit; le altre restano in `sources[].jd` |
| RAL / retribuzione | **unione, non sostituzione**: se una ce l'ha e l'altra no, prendi quella; se divergono, riporta entrambe con la fonte accanto (mai un valore fuso inventato) |
| Data pubblicazione | la **più recente** tra le fonti |
| `links.jd` | **tutti** i link, uno per fonte |
| `primary_source` | la fonte del corpo vincente; euristica: **career_page > indeed > alert** |
