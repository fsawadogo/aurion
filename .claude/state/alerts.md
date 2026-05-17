# Aurion Autonomous Loop — Alerts

Append-only file. The monitor cron writes here when state changes; the
driver loop reads this at the top of every tick and handles new entries
before any new task work.

Format:

    ## YYYY-MM-DD HH:MM [severity] {source}
    {one-line summary}
    {optional details}

Severity: INFO | WARN | ALERT (loop pauses + Linear post)

Loops MUST NOT delete entries from this file. Mark handled by appending
a `→ resolved YYYY-MM-DD HH:MM` line under the entry.

---

(no alerts yet)
