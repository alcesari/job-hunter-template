#!/bin/bash
# publish_run.sh — il passo di pubblicazione della routine job-watch.
#
#   scripts/publish_run.sh reconcile
#   scripts/publish_run.sh publish "<messaggio di commit>"
#
# PERCHE' ESISTE (incidente 2026-08-18 → 2026-09-05, diagnosticato il 2026-09-07)
# ------------------------------------------------------------------------------
# La routine PUO' pushare su `main`: lo ha fatto in circa meta' delle run. Il
# difetto non era il permesso, era che il passo di pubblicazione veniva
# improvvisato dal modello a ogni giro — a volte push diretto, a volte
# branch + PR mai mergiata, con commit rifatti (su `main` esistono commit
# gemelli con lo STESSO tree: la firma di un push andato storto e ritentato a
# mano). Risultato: 10 run mai atterrate su `main`, 125 chiavi di dedup perse,
# e un'auto-riparazione agganciata alle PR APERTE che quindi mancava
# sistematicamente le run rimaste solo come branch.
#
# Qui il flusso git non e' piu' una decisione: e' codice. Effetto collaterale
# utile — l'allowlist di `.claude/settings.json` puo' autorizzare QUESTO SCRIPT
# invece di `git push *` / `git merge *`, quindi la superficie concessa alla
# routine si restringe invece di allargarsi (i comandi lanciati dentro uno
# script non passano dal gate dei permessi: passa solo l'invocazione).
#
# GARANZIE
#   - `publish` mette in staging SOLO i path dello strato operativo (D5):
#     source-log/ state.json staging/ digests/ PIPELINE.md. Non puo'
#     committare master-profile.yaml, searches/, role-fit/, applications/
#     nemmeno per errore — seconda barriera dopo l'hook protect-files.sh.
#   - Il lavoro atterra su `main` o, se proprio non ci riesce, su UN branch
#     fisso (`routine/job-watch`) che la `reconcile` del giro dopo recupera per
#     costruzione. Mai piu' un branch nuovo per run.
#   - `reconcile` riconosce i branch da recuperare dal CONTENUTO (toccano solo
#     path operativi), non dal messaggio di commit: un branch che tocca il
#     profilo non viene mai assorbito in automatico.
#
# Exit code (nessuno e' fatale per la run: il digest e' gia' su file):
#   0 = atterrato su main (o niente da fare)
#   4 = non atterrato su main, lavoro salvato su routine/job-watch
#   2 = conflitto fuori dallo strato operativo: serve una sessione interattiva
set -uo pipefail

FALLBACK_BRANCH="routine/job-watch"
OPERATIONAL_PATHS=(source-log state.json staging digests PIPELINE.md)
PUSH_RETRIES=4

cd "$(git rev-parse --show-toplevel)" || exit 1

die() { echo "publish_run: $*" >&2; }

# --- resolve_or_abort: risolve un merge in corso, o lo annulla ----------------
resolve_or_abort() {
  if [ -z "$(git diff --name-only --diff-filter=U)" ]; then
    return 0
  fi
  if python3 scripts/merge_operational.py; then
    return 0
  fi
  die "conflitto fuori dallo strato operativo — merge annullato"
  git merge --abort 2>/dev/null || true
  return 2
}

# --- land_on_main: porta HEAD su origin/main, con retry ----------------------
# Ogni tentativo ri-fetcha e ri-mergia: se qualcun altro ha pushato nel
# frattempo il giro successivo lo assorbe invece di fallire.
land_on_main() {
  local attempt delay
  for attempt in $(seq 1 "$PUSH_RETRIES"); do
    git fetch --quiet origin main || true

    if ! git merge-base --is-ancestor origin/main HEAD; then
      echo "  origin/main e' avanti: mergio prima di pushare"
      git merge --no-edit --no-ff origin/main >/dev/null 2>&1
      resolve_or_abort || return 2
      if [ -n "$(git diff --name-only --diff-filter=U)" ] || [ -f .git/MERGE_HEAD ]; then
        git commit --no-edit --quiet -m "merge: allinea a origin/main prima della pubblicazione" 2>/dev/null || true
      fi
    fi

    if git push --quiet origin HEAD:main 2>/dev/null; then
      echo "  pubblicato su main: $(git rev-parse --short HEAD)"
      return 0
    fi

    delay=$((2 ** attempt))
    die "push su main fallito (tentativo $attempt/$PUSH_RETRIES), riprovo tra ${delay}s"
    sleep "$delay"
  done

  # Ultima spiaggia: UN branch fisso, che la reconcile del giro dopo recupera.
  if git push --quiet --force-with-lease origin "HEAD:refs/heads/$FALLBACK_BRANCH" 2>/dev/null; then
    die "NON atterrato su main: lavoro salvato su '$FALLBACK_BRANCH'."
    die "La 'reconcile' della prossima run lo recuperera' automaticamente."
    return 4
  fi
  die "push fallito anche su '$FALLBACK_BRANCH': il lavoro resta solo nel clone locale."
  return 4
}

# --- touches_only_operational: il branch tocca solo lo strato operativo? ------
touches_only_operational() {
  local ref="$1" base f
  base=$(git merge-base origin/main "$ref" 2>/dev/null) || return 1
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
      source-log/*|state.json|staging/*|digests/*|PIPELINE.md) ;;
      *) return 1 ;;
    esac
  done < <(git diff --name-only "$base" "$ref")
  return 0
}

# --- reconcile ---------------------------------------------------------------
cmd_reconcile() {
  git fetch --quiet --prune origin || { die "fetch fallito, salto la reconcile"; return 0; }

  if ! git merge-base --is-ancestor origin/main HEAD; then
    git merge --no-edit --no-ff origin/main >/dev/null 2>&1
    resolve_or_abort || return 2
    [ -f .git/MERGE_HEAD ] && git commit --no-edit --quiet 2>/dev/null
  fi

  local head_ref orphans=() ref name
  head_ref=$(git rev-parse --abbrev-ref HEAD)

  while IFS= read -r ref; do
    name="${ref#refs/remotes/origin/}"
    [ "$name" = "main" ] && continue
    [ "$name" = "$head_ref" ] && continue
    git merge-base --is-ancestor "$ref" HEAD 2>/dev/null && continue
    touches_only_operational "$ref" || continue
    orphans+=("$name")
  done < <(git for-each-ref --format='%(refname)' refs/remotes/origin)

  if [ ${#orphans[@]} -eq 0 ]; then
    echo "reconcile: nessuna run da recuperare"
    return 0
  fi

  echo "reconcile: ${#orphans[@]} run mai atterrate su main da recuperare"
  for name in "${orphans[@]}"; do
    echo "  <- origin/$name"
    git merge --no-edit --no-ff "origin/$name" >/dev/null 2>&1
    resolve_or_abort || return 2
    if [ -f .git/MERGE_HEAD ]; then
      git commit --no-edit --quiet -m "merge: recupera run job-watch da origin/$name

Branch mai atterrato su main. Conflitti dello strato operativo risolti da
scripts/merge_operational.py (state.json e source-log per unione)." 2>/dev/null
    fi
  done

  land_on_main
}

# --- publish -----------------------------------------------------------------
cmd_publish() {
  local message="${1:-}"
  if [ -z "$message" ]; then
    die "uso: publish_run.sh publish \"<messaggio di commit>\""
    return 1
  fi

  # SOLO strato operativo: e' la barriera, non una comodita'.
  local existing=()
  local p
  for p in "${OPERATIONAL_PATHS[@]}"; do
    [ -e "$p" ] && existing+=("$p")
  done
  [ ${#existing[@]} -gt 0 ] && git add -A -- "${existing[@]}"

  if git diff --cached --quiet; then
    echo "publish: niente da committare nello strato operativo"
  else
    git commit --quiet -m "$message"
    echo "publish: $(git rev-parse --short HEAD) $(git log -1 --format=%s)"
  fi

  land_on_main
}

case "${1:-}" in
  reconcile) cmd_reconcile ;;
  publish)   shift; cmd_publish "${1:-}" ;;
  *)
    die "uso: publish_run.sh {reconcile | publish \"<messaggio>\"}"
    exit 1 ;;
esac
