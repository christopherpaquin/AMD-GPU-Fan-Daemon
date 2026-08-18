#!/usr/bin/env bash
# Checks that amd-gpu-fan-daemon is actually doing its job, not just that
# the process exists: service active, sensors readable, headers in manual
# mode, and the daemon's heartbeat is fresh. cron/systemd-timer friendly:
# exit 0 = healthy, exit 1 = unhealthy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_NAME="amd-gpu-fan-daemon"
ENV_FILE="${REPO_ROOT}/.env"

fail() {
  printf 'UNHEALTHY: %s\n' "$*" >&2
  exit 1
}

[[ -f "${ENV_FILE}" ]] || fail "no .env found at ${ENV_FILE} - has install.sh been run?"

env_value() {
  # Last matching KEY= line wins, mirrors the daemon's own parser.
  local key="$1"
  sed -n "s/^${key}=//p" "${ENV_FILE}" | tail -n1 | tr -d "\"'"
}

systemctl is-active --quiet "${UNIT_NAME}" || fail "systemd unit ${UNIT_NAME} is not active"

if ! grep -qsx amdgpu /sys/class/hwmon/*/name 2> /dev/null; then
  fail "cannot find amdgpu hwmon device - GPU temp is unreadable"
fi

CPU_HWMON_NAME="$(env_value CPU_HWMON_NAME)"
if ! grep -qsx "${CPU_HWMON_NAME}" /sys/class/hwmon/*/name 2> /dev/null; then
  fail "cannot find ${CPU_HWMON_NAME} hwmon device - fan control is unreadable"
fi

FAN_HEADERS="$(env_value FAN_HEADERS)"
CPU_HWMON_PATH=""
for dir in /sys/class/hwmon/*; do
  [[ "$(cat "${dir}/name" 2> /dev/null)" == "${CPU_HWMON_NAME}" ]] && CPU_HWMON_PATH="${dir}"
done
[[ -n "${CPU_HWMON_PATH}" ]] || fail "could not resolve ${CPU_HWMON_NAME} hwmon path"

for header in ${FAN_HEADERS}; do
  enable_file="${CPU_HWMON_PATH}/pwm${header}_enable"
  [[ -r "${enable_file}" ]] || fail "cannot read ${enable_file}"
  value="$(cat "${enable_file}")"
  [[ "${value}" == "1" ]] || fail "pwm${header}_enable is ${value}, expected 1 (manual) - daemon may not be actively managing it"
done

HEARTBEAT_FILE="$(env_value HEARTBEAT_FILE)"
HEARTBEAT_STALE_SECONDS="$(env_value HEARTBEAT_STALE_SECONDS)"
[[ -f "${HEARTBEAT_FILE}" ]] || fail "heartbeat file ${HEARTBEAT_FILE} does not exist"

heartbeat_age() {
  python3 -c "import time; print(int(time.time() - float(open('${HEARTBEAT_FILE}').read())))"
}
AGE="$(heartbeat_age)"
if ((AGE > HEARTBEAT_STALE_SECONDS)); then
  fail "heartbeat is ${AGE}s old, older than HEARTBEAT_STALE_SECONDS=${HEARTBEAT_STALE_SECONDS} - control loop may be hung"
fi

printf 'OK: %s active, headers [%s] in manual mode, heartbeat %ss old\n' \
  "${UNIT_NAME}" "${FAN_HEADERS}" "${AGE}"
