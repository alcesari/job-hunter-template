# Runbook — cancellazione profonda di un dato personale (GDPR)

*Contesto: procedura di cancellazione GDPR per il sistema Job Hunter.*

## Quando serve

La cancellazione ordinaria (riscrivere `master-profile.yaml`, chiudere una
candidatura, rimuovere un file con `git rm`) elimina il dato solo dall'**HEAD**
del repo: ogni commit precedente resta leggibile nella storia git, quindi
anche dopo `git push`. Questo runbook serve solo quando serve rimuovere un
dato personale **da tutta la storia**, non solo dallo stato attuale — es.
richiesta di cancellazione GDPR su un dato che è stato committato per errore
(un numero di telefono sbagliato, un'email di un terzo finita in una nota, un
file caricato per sbaglio in `.docs/`).

Se il dato è solo nello stato attuale (non serve toccare la storia), **non**
serve questo runbook: basta la modifica normale + commit + push.

## Prerequisiti

- `git filter-repo` installato (`brew install git-filter-repo` o
  `pip install git-filter-repo`) — NON usare `git filter-branch` (deprecato,
  più lento, più facile da usare male) né `BFG` a meno di preferenza esplicita.
- Il repo è **privato** (verificato, vedi `CLAUDE.md`): questo limita ma non
  azzera l'esposizione pregressa — se il dato è stato pubblico anche solo
  temporaneamente, valuta se il repo vada anche reso privato con urgenza
  (indipendente da questo runbook) e se GitHub Support vada informato per
  purgare cache/fork.
- **Comunica prima all'utente** cosa stai per fare: riscrivere la storia è
  distruttivo e irreversibile lato repo locale (ogni clone esistente diverge).
  Non eseguire questo runbook senza conferma esplicita, anche se l'azione
  finale (push) fosse già autorizzata in altro contesto.

## Procedura

1. **Backup**: clona una copia a parte del repo prima di iniziare
   (`git clone --mirror <url> job-hunter-backup-pre-filter.git`), tienila
   offline finché non sei sicuro che la cancellazione sia andata a buon fine.

2. **Identifica cosa rimuovere**: un valore specifico (es. una stringa email)
   o un intero file (es. un CV caricato per sbaglio). `git filter-repo`
   supporta entrambi i casi con opzioni diverse.

   Per un **file** (es. rimuovere `.docs/CV-vecchio.pdf` da tutta la storia):
   ```bash
   git filter-repo --path .docs/CV-vecchio.pdf --invert-paths
   ```

   Per un **valore testuale** (es. un numero di telefono committato per
   errore in un punto diverso dal campo corrente di `master-profile.yaml`):
   crea un file `replacements.txt` con una riga `<valore-vecchio>==>[RIMOSSO]`
   per ogni sostituzione, poi:
   ```bash
   git filter-repo --replace-text replacements.txt
   ```

3. **Verifica in locale** prima di toccare il remoto: cerca il valore/file
   rimosso in tutta la storia riscritta.
   ```bash
   git log --all -p | grep -i "<valore-rimosso>"   # deve dare zero risultati
   ```

4. **Riallinea il remoto** (distruttivo, richiede conferma esplicita
   dell'utente prima di eseguirlo — vedi Prerequisiti):
   ```bash
   git push origin --force --all
   git push origin --force --tags
   ```
   `git filter-repo` rimuove per design il remote `origin` dal repo riscritto
   (misura di sicurezza per evitare push accidentali) — va riaggiunto prima:
   ```bash
   git remote add origin <url-del-repo>
   ```

5. **Invalida ogni clone esistente**: dopo un force-push storico, qualunque
   altro clone (incluso l'ambiente della routine cloud, se ne mantiene uno
   persistente) diverge dalla nuova storia. La routine clona `main` fresco a
   ogni run (vedi `job-watch/SKILL.md`), quindi si autocorregge al giro
   successivo — ma se esistono clone locali extra dell'utente, vanno
   riclonati da zero, non semplicemente `git pull`-ati (un pull su storia
   riscritta produce conflitti irrisolvibili).

6. **Chiudi il ciclo**: aggiorna il finding/ticket che ha originato la
   richiesta con la conferma dell'avvenuta cancellazione (data, cosa è stato
   rimosso, verifica del passo 3). Se la richiesta veniva da un obbligo GDPR
   formale (diritto all'oblio), questa nota è la prova di adempimento.

## Cosa NON fa questo runbook

- Non tocca eventuali fork o clone fuori dal controllo dell'utente (repo
  privato → nessun fork possibile su GitHub finché resta privato, ma un clone
  scaricato prima che il repo diventasse privato resta un rischio residuo,
  non risolvibile lato repo).
- Non sostituisce la valutazione se il repo debba anche cambiare visibilità o
  se GitHub Support debba essere coinvolto per purgare cache interne — sono
  passi paralleli, da valutare caso per caso in base alla natura
  dell'esposizione.
