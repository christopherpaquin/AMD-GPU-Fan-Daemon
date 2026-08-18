#!/usr/bin/env bash
# Idempotent installer for amd-gpu-fan-daemon. Safe to re-run: existing
# state (.env, unit file) is detected rather than blindly overwritten.
#
# Installs and enables a root-privileged systemd service that takes manual
# control of the configured motherboard fan PWM headers (see .env
# FAN_HEADERS). Read README.md "Security notes" before running this on a
# machine you care about.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="amd-gpu-fan-daemon"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}.service"

log() { printf '[install] %s\n' "$*"; }
die() {
  printf '[install] ERROR: %s\n' "$*" >&2
  exit 1
}
require_cmd() {
  command -v "$1" > /dev/null 2>&1 || die "required command '$1' not found on PATH"
}

require_cmd python3
require_cmd systemctl
require_cmd sudo

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' ||
  die "python3 >= 3.9 required, found $(python3 --version 2>&1)"

[[ -d /sys/class/hwmon ]] || die "/sys/class/hwmon not present - this system has no hwmon subsystem"

if ! grep -qsx amdgpu /sys/class/hwmon/*/name 2> /dev/null; then
  die "no hwmon device named 'amdgpu' found - is the amdgpu driver loaded? (lsmod | grep amdgpu)"
fi

if ! grep -qsx nct6797 /sys/class/hwmon/*/name 2> /dev/null; then
  die "no hwmon device named 'nct6797' found - load the nct6775 kernel module first" \
    "(sudo modprobe nct6775), or edit .env's CPU_HWMON_NAME to match your board's chip" \
    "(check with: for f in /sys/class/hwmon/*/name; do echo \"\$f: \$(cat \$f)\"; done)"
fi

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  log "creating .env from .env-template"
  cp "${REPO_ROOT}/.env-template" "${REPO_ROOT}/.env"
else
  log ".env already exists, leaving it as-is"
fi

log "validating configuration and hwmon resolution (dry run)"
(cd "${REPO_ROOT}" && python3 -m fan_daemon --env-file "${REPO_ROOT}/.env" --print-hwmon-paths)

TMP_UNIT="$(mktemp)"
trap 'rm -f "${TMP_UNIT}"' EXIT
sed "s#__INSTALL_DIR__#${REPO_ROOT}#g" \
  "${REPO_ROOT}/systemd/${UNIT_NAME}.service.template" > "${TMP_UNIT}"

log "installing systemd unit to ${UNIT_PATH}"
sudo install -m 644 "${TMP_UNIT}" "${UNIT_PATH}"
sudo systemctl daemon-reload
sudo systemctl enable "${UNIT_NAME}"

if systemctl is-active --quiet "${UNIT_NAME}"; then
  log "service already running, restarting to pick up any changes"
  sudo systemctl restart "${UNIT_NAME}"
else
  log "starting service"
  sudo systemctl start "${UNIT_NAME}"
fi

log "install complete. Current status:"
systemctl status --no-pager "${UNIT_NAME}" || true
log "tail logs with: journalctl -u ${UNIT_NAME} -f"
