#!/usr/bin/env bash
# Autopilot scheduler registration (macOS launchd). AUTHORED, NOT AUTO-RUN.
# Per the house rule "prove → harden → automate": run a loop manually + watch it
# succeed ONCE, THEN run this to schedule it. Nothing here arms a loop you
# haven't watched.
#
# Usage:
#   ./register-launchd.sh install <loop>     # schedule one proven loop
#   ./register-launchd.sh uninstall <loop>
#   ./register-launchd.sh list
#
# Each loop runs headless via `claude -p` reading its skill, logging to the
# git-ignored state dir. Schedules come from policy.json (loops.<loop>.schedule,
# cron-style → translated to a launchd StartCalendarInterval... here kept simple
# as a daily/interval anchor; tune per loop in the generated plist).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
POLICY="$HERE/policy.json"
LOG_DIR="$HERE/state/logs"
LABEL_PREFIX="ai.aurion.autopilot"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

cmd="${1:-}"; loop="${2:-}"

plist_path() { echo "$HOME/Library/LaunchAgents/${LABEL_PREFIX}.${1}.plist"; }

install_loop() {
  local lp="$1"
  python3 -c "import json,sys; d=json.load(open('$POLICY')); sys.exit(0 if '$lp' in d['loops'] else 1)" \
    || { echo "unknown loop: $lp (see policy.json loops)"; exit 1; }
  mkdir -p "$LOG_DIR"
  local plist; plist="$(plist_path "$lp")"
  # Headless invocation: claude -p reads the loop skill; output appended to the log.
  # NOTE: validate `claude -p` runs headless in YOUR environment first. The
  # prompt points at the loop playbook so the spec/gate/ledger are all in scope.
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${LABEL_PREFIX}.${lp}</string>
  <key>WorkingDirectory</key><string>${REPO_ROOT}</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string>
    <string>${CLAUDE_BIN} -p "Run the Autopilot '${lp}' loop per .claude/autopilot/loops/${lp}.md. Honor policy.json. Stop at the Loop spec STOP WHEN / caps / token budget." >> "${LOG_DIR}/${lp}.log" 2>&1</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardErrorPath</key><string>${LOG_DIR}/${lp}.launchd.err</string>
  <key>StandardOutPath</key><string>${LOG_DIR}/${lp}.launchd.out</string>
</dict></plist>
PLIST
  echo "wrote $plist"
  echo "To arm:   launchctl load -w \"$plist\""
  echo "(left UNLOADED — arm only after a watched manual success. Edit StartCalendarInterval to match policy.json loops.${lp}.schedule.)"
}

uninstall_loop() { local plist; plist="$(plist_path "$1")"; launchctl unload -w "$plist" 2>/dev/null || true; rm -f "$plist"; echo "removed $plist"; }
list_loops() { ls "$HOME/Library/LaunchAgents/${LABEL_PREFIX}".*.plist 2>/dev/null || echo "(none registered)"; }

case "$cmd" in
  install)   [ -n "$loop" ] || { echo "usage: $0 install <loop>"; exit 1; }; install_loop "$loop";;
  uninstall) [ -n "$loop" ] || { echo "usage: $0 uninstall <loop>"; exit 1; }; uninstall_loop "$loop";;
  list)      list_loops;;
  *) echo "usage: $0 {install|uninstall|list} [loop]"; exit 1;;
esac
