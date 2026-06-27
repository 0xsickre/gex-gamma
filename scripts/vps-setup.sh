#!/usr/bin/env bash
# Idempotent VPS setup for gex-gamma (SQLite + systemd timers + Streamlit).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="/var/lib/gex-gamma"
ENV_FILE="${REPO_ROOT}/.env"
VENV="${REPO_ROOT}/.venv"

log() { echo "[vps-setup] $*"; }

log "Creating data directories..."
mkdir -p "${DATA_DIR}/snapshots"

if [[ ! -f "${ENV_FILE}" ]]; then
  log "Creating .env from deploy/env.example..."
  cp "${REPO_ROOT}/deploy/env.example" "${ENV_FILE}"
  log "Edit ${ENV_FILE} — set MASSIVE_API_KEY (required for the option chain)."
fi

if [[ ! -d "${VENV}" ]]; then
  log "Creating Python venv..."
  python3 -m venv "${VENV}"
fi

log "Installing package..."
"${VENV}/bin/pip" install -q --upgrade pip
"${VENV}/bin/pip" install -q -e "${REPO_ROOT}[dev,pg]"

if [[ ! -f "${DATA_DIR}/snapshots/latest.json" ]]; then
  log "Running initial gex-refresh + signal..."
  set -a
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +a
  "${VENV}/bin/gex-refresh" || true
  "${VENV}/bin/gex-signal" --out "${DATA_DIR}/snapshots/latest.json" --persist || true
else
  log "Snapshot already exists, skipping initial refresh."
fi

log "Installing systemd units..."
cp "${REPO_ROOT}/deploy/systemd/"* /etc/systemd/system/
chmod +x "${REPO_ROOT}/scripts/vps-deploy.sh"
systemctl daemon-reload
systemctl enable gex-refresh.timer gex-deploy.timer gex-streamlit
systemctl start gex-refresh.timer gex-deploy.timer
systemctl restart gex-streamlit

echo ""
echo "=== gex-gamma setup complete ==="
systemctl list-timers gex-refresh.timer gex-deploy.timer --no-pager || true
echo ""
echo "Dashboard: https://gex.kresicds.com (after DNS A -> VPS IP)"
echo "Snapshot:  ${DATA_DIR}/snapshots/latest.json"
