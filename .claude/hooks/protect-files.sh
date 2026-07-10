#!/bin/bash
# protect-files.sh — enforcement meccanico della regola di proprietà D5.
#
# Hook PreToolUse su Edit|Write (vedi .claude/settings.json). Nelle sessioni
# della ROUTINE job-watch (identificate da JOB_HUNTER_ROUTINE=1, impostata
# nella config dell'ambiente cloud della routine) blocca ogni scrittura sui
# file di proprietà delle sessioni interattive:
#   master-profile.yaml, searches/, role-fit/, applications/
# e lascia passare lo strato operativo (source-log/, state.json, staging/,
# digests/, PIPELINE.md) e tutto il resto.
#
# Nelle sessioni interattive (variabile assente) l'hook non impone nulla.
# Fail-open by design: se l'input non è parsabile lascia passare — la vera
# barriera di base resta l'allowlist dei permessi (che per la routine non
# concede comunque scritture fuori dallo strato operativo).
set -u

# Sessione interattiva: nessuna restrizione da questo hook.
if [ "${JOB_HUNTER_ROUTINE:-0}" != "1" ]; then
  exit 0
fi

input=$(cat)

file_path=$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")
' 2>/dev/null)

[ -z "$file_path" ] && exit 0

# Normalizza a percorso relativo alla radice del repo.
root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
case "$file_path" in
  "$root"/*) rel="${file_path#"$root"/}" ;;
  *)         rel="$file_path" ;;
esac

case "$rel" in
  master-profile.yaml|searches/*|role-fit/*|applications/*)
    echo "protect-files (D5): la routine job-watch NON scrive '$rel' — è proprietà delle sessioni interattive (master-profile.yaml, searches/, role-fit/, applications/). La routine scrive solo lo strato operativo: source-log/, state.json, staging/, digests/, PIPELINE.md." >&2
    exit 2
    ;;
esac

exit 0
