#!/usr/bin/env bash
# Removes the amd-gpu-fan-daemon systemd service and, critically, reverts
# every configured fan header back to hardware/BIOS auto control
# (pwm*_enable -> FAILSAFE_PWM_ENABLE from .env, normally 5). This script
# is safety-critical, not just cleanup: it must not leave fans stuck at a
# stale manual PWM value. Safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="amd-gpu-fan-daemon"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}.service"

log() { printf '[uninstall] %s\n' "$*"; }

if systemctl list-unit-files "${UNIT_NAME}.service" > /dev/null 2>&1 &&
  [[ -f "${UNIT_PATH}" ]]; then
  if systemctl is-active --quiet "${UNIT_NAME}"; then
    log "stopping ${UNIT_NAME} (this triggers its own auto-revert via ExecStopPost)"
    sudo systemctl stop "${UNIT_NAME}"
  fi
  log "disabling ${UNIT_NAME}"
  sudo systemctl disable "${UNIT_NAME}" 2> /dev/null || true
  log "removing unit file ${UNIT_PATH}"
  sudo rm -f "${UNIT_PATH}"
  sudo systemctl daemon-reload
else
  log "no installed unit found at ${UNIT_PATH} - nothing to stop/remove"
fi

# Belt-and-suspenders: explicitly revert every header even if the unit was
# already gone, already stopped, or its ExecStopPost somehow didn't run.
# Idempotent - reverting an already-auto header is harmless.
if [[ -f "${REPO_ROOT}/.env" ]] && command -v python3 > /dev/null 2>&1; then
  log "reverting all configured fan headers to hardware auto control"
  if ! sudo -- env PYTHONPATH="${REPO_ROOT}" python3 -m fan_daemon \
    --env-file "${REPO_ROOT}/.env" --revert-to-auto; then
    log "WARNING: explicit revert-to-auto failed - check pwm*_enable manually:" \
      "sensors | grep -A2 nct6797"
  fi
else
  log "WARNING: no .env found, could not run explicit revert-to-auto - check" \
    "pwm*_enable manually: sensors | grep -A2 nct6797"
fi

log "uninstall complete. .env and .git history are left in place;" \
  "delete ${REPO_ROOT} manually if you want the repo gone entirely."
