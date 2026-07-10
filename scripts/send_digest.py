#!/usr/bin/env python3
"""Invia il digest Job Hunter via SMTP Gmail (app-password).

Uso:  python scripts/send_digest.py <path-al-digest.md>
Env:  GMAIL_ADDRESS        indirizzo Gmail mittente/destinatario
      GMAIL_APP_PASSWORD   app-password Gmail (16 caratteri, NON la password normale)
      DIGEST_TO            (opz.) destinatario diverso dal mittente

Exit code semantici (tutti non-fatali per la routine, che non fallisce MAI
per il digest — decide solo il fallback):
  0 = inviato con successo
  3 = saltato (argomenti mancanti / file inesistente / credenziali assenti)
      → la routine ricade sulla bozza via connettore Gmail
  4 = fallito (errore SMTP a credenziali presenti)
      → la routine ricade sulla bozza E segnala l'anomalia nel digest successivo

Le credenziali vivono SOLO come secret dell'ambiente, mai nel repo.

Nota nota (2026-07-08): nella routine CLOUD questo script fallisce
strutturalmente con `OSError(97, 'Address family not supported by protocol')`
— il sandbox non espone socket di rete grezzi (smtplib ne apre uno diretto),
solo i canali già strumentati (connettori MCP, git). Non è un bug: è un
confine della sandbox, non vale la pena inseguirlo lì. L'esito exit 4 in quel
contesto è normale, non un'anomalia da correggere — il fallback bozza è il
comportamento di produzione atteso. Lo script resta valido per un'eventuale
routine Desktop locale (rete non sandboxata).
"""
import os
import sys
import ssl
import html
import smtplib
from email.message import EmailMessage
from pathlib import Path

EXIT_SENT = 0
EXIT_SKIPPED = 3
EXIT_FAILED = 4


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: send_digest.py <digest.md> → invio saltato")
        return EXIT_SKIPPED
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"digest non trovato: {path} — invio saltato")
        return EXIT_SKIPPED

    addr = os.environ.get("GMAIL_ADDRESS")
    # Google mostra l'app-password con spazi separatori (es. "abcd efgh ijkl mnop"):
    # rimuovili, valgono sia con che senza — evita ambiguità di parsing .env.
    pw_raw = os.environ.get("GMAIL_APP_PASSWORD")
    pw = pw_raw.replace(" ", "") if pw_raw else pw_raw
    to = os.environ.get("DIGEST_TO", addr)
    if not addr or not pw:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD non impostati → invio saltato "
              "(la routine ricada sulla bozza via connettore Gmail).")
        return EXIT_SKIPPED

    body = path.read_text(encoding="utf-8")
    first_line = next((l for l in body.splitlines() if l.strip()), path.stem)
    subject = first_line.lstrip("# ").strip() or f"Job Hunter — {path.stem}"

    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)  # plain text: il markdown si legge bene
    msg.add_alternative(
        '<pre style="font-family:-apple-system,Segoe UI,Roboto,monospace;'
        'white-space:pre-wrap;font-size:14px;line-height:1.45">'
        f"{html.escape(body)}</pre>",
        subtype="html",
    )

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(addr, pw)
            s.send_message(msg)
    except Exception as e:  # noqa: BLE001 — degradazione elegante, ma esito distinguibile
        print(f"Invio digest fallito ({e!r}) → la routine ricada sulla bozza.")
        return EXIT_FAILED

    print(f"Digest inviato a {to}: {subject}")
    return EXIT_SENT


if __name__ == "__main__":
    sys.exit(main())
