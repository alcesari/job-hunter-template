#!/usr/bin/env python3
"""Risolve i conflitti di merge dello strato operativo in modo deterministico.

Uso:  python3 scripts/merge_operational.py [--dry-run]

Si esegue **durante un merge in corso** (dopo che `git merge` ha lasciato dei
conflitti). Applica una regola fissa per ciascuna famiglia di path dello strato
operativo, poi fa `git add` di ogni file risolto. Non committa: decide il
chiamante (`publish_run.sh`).

Perche' esiste: lo strato operativo e' append-only e i suoi conflitti hanno una
risoluzione OVVIA e sempre uguale. Lasciarla al giudizio del modello a ogni run
significa risolverla in modo diverso ogni volta — ed e' esattamente cosi' che
sono andate perse 125 chiavi di dedup tra il 2026-08-18 e il 2026-09-05.

Regole (in ordine di specificita'):

  state.json          UNIONE. Le chiavi `seen` non si perdono mai; a parita' di
                      chiave vince il `first_seen` piu' VECCHIO (e' la data di
                      prima osservazione: la piu' antica e' quella vera).
                      `career_page_health`: unione, vince la voce gia' presente.

  source-log/*.jsonl  UNIONE delle righe con dedup esatto, riordinate per
                      `run_id`. E' telemetria append-only: perdere una riga
                      falsa le metriche di `job-alert-tuner`.

  PIPELINE.md         OURS. E' rigenerabile integralmente da `applications/` e
                      non e' mai fonte di verita' (eccezione D5 dichiarata):
                      il chiamante lo rigenera comunque a valle.

  staging/**          OURS. Una voce di staging in conflitto significa che la
                      stessa offerta e' stata valutata due volte da run diverse
                      (sintomo di dedup rotto a monte). Si tiene la valutazione
                      del lato corrente: e' quella gia' consegnata all'utente
                      nel digest, e riscriverla cambierebbe sotto gli occhi una
                      voce che l'utente puo' aver gia' revisionato.

  digests/**          OURS se il file esiste su entrambi i lati (stesso giorno,
                      due run: il piu' recente e' gia' quello corrente).

Qualsiasi altro path in conflitto NON viene toccato: lo script esce con codice 2
e lo segnala. E' deliberato — un conflitto fuori dallo strato operativo (es.
`master-profile.yaml`, `searches/`) non ha una risoluzione automatica sensata e
deve fermare il flusso, non essere indovinato.

Exit code:
  0 = tutti i conflitti risolti (o nessun conflitto)
  2 = conflitti su path fuori dallo strato operativo: intervento umano
"""
import json
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_UNHANDLED = 2

# Stage del merge: 2 = ours (HEAD), 3 = theirs (il ramo mergiato).
OURS, THEIRS = 2, 3


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True)


def stage_blob(stage: int, path: str) -> bytes | None:
    """Contenuto di un lato del conflitto, o None se quel lato non ha il file."""
    try:
        return subprocess.check_output(
            ["git", "show", f":{stage}:{path}"], stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return None


def conflicted_paths() -> list[str]:
    out = git("diff", "--name-only", "--diff-filter=U")
    return [p for p in out.splitlines() if p.strip()]


def resolve_state_json(path: str) -> str:
    ours = json.loads(stage_blob(OURS, path) or b"{}")
    theirs = json.loads(stage_blob(THEIRS, path) or b"{}")

    seen = dict(ours.get("seen", {}))
    added = 0
    for key, value in theirs.get("seen", {}).items():
        if key not in seen:
            seen[key] = value
            added += 1
            continue
        # Stessa chiave su entrambi i lati: tieni la prima osservazione.
        mine, other = seen[key].get("first_seen"), value.get("first_seen")
        if other and (not mine or other < mine):
            seen[key] = value

    health = dict(ours.get("career_page_health", {}))
    for key, value in theirs.get("career_page_health", {}).items():
        health.setdefault(key, value)

    merged = {"career_page_health": health, "seen": dict(sorted(seen.items()))}
    Path(path).write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return f"unione: {len(ours.get('seen', {}))} + {len(theirs.get('seen', {}))} -> {len(seen)} chiavi seen (+{added})"


def resolve_jsonl(path: str) -> str:
    def lines(stage: int) -> list[str]:
        blob = stage_blob(stage, path)
        if blob is None:
            return []
        return [l for l in blob.decode("utf-8").splitlines() if l.strip()]

    ours, theirs = lines(OURS), lines(THEIRS)
    seen: set[str] = set()
    merged: list[str] = []
    for line in ours + theirs:
        if line not in seen:
            seen.add(line)
            merged.append(line)

    def run_id(line: str) -> str:
        try:
            return json.loads(line).get("run_id", "")
        except json.JSONDecodeError:
            return ""

    merged.sort(key=run_id)  # stabile: righe con lo stesso run_id restano in ordine
    Path(path).write_text("\n".join(merged) + "\n", encoding="utf-8")
    return f"unione: {len(ours)} + {len(theirs)} -> {len(merged)} righe (+{len(merged) - len(ours)})"


def resolve_ours(path: str) -> str:
    blob = stage_blob(OURS, path)
    if blob is None:
        # Il file non esiste sul lato corrente: tieni quello dell'altro ramo,
        # e' un'aggiunta pura, non un conflitto di contenuto.
        subprocess.check_call(["git", "checkout", "--theirs", "--", path])
        return "aggiunto dal ramo mergiato (assente sul lato corrente)"
    Path(path).write_bytes(blob)
    return "tenuta la versione del lato corrente"


def rule_for(path: str):
    if path == "state.json":
        return resolve_state_json
    if path.startswith("source-log/") and path.endswith(".jsonl"):
        return resolve_jsonl
    if path == "PIPELINE.md":
        return resolve_ours
    if path.startswith("staging/") or path.startswith("digests/"):
        return resolve_ours
    return None


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]
    paths = conflicted_paths()
    if not paths:
        print("nessun conflitto da risolvere")
        return EXIT_OK

    unhandled = [p for p in paths if rule_for(p) is None]
    if unhandled:
        print(
            "conflitti fuori dallo strato operativo — nessuna risoluzione automatica:",
            file=sys.stderr,
        )
        for p in unhandled:
            print(f"  {p}", file=sys.stderr)
        print(
            "Lo strato operativo e' source-log/, state.json, staging/, digests/, "
            "PIPELINE.md. Un conflitto altrove va risolto da una sessione interattiva.",
            file=sys.stderr,
        )
        return EXIT_UNHANDLED

    for path in paths:
        rule = rule_for(path)
        if dry_run:
            print(f"  [dry-run] {path}: {rule.__name__}")
            continue
        note = rule(path)
        subprocess.check_call(["git", "add", "--", path])
        print(f"  {path}: {note}")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
