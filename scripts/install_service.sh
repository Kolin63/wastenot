#!/usr/bin/env bash
# =============================================================================
# WasteNot – Service Installer
# =============================================================================
# Installs and enables WasteNot as a systemd service so it starts
# automatically on every boot.
#
# Prerequisites:
#   • scripts/setup.sh must have been run first (creates the venv).
#
# Usage:
#   chmod +x scripts/install_service.sh
#   ./scripts/install_service.sh
#
# Optional environment variables forwarded to the service:
#   MOCK_MODE=true            – use simulated sensor data
#   TVOC_ALERT_THRESHOLD=200  – alert threshold in ppb (default: 200)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="wastenot"
SERVICE_SRC="$APP_DIR/wastenot.service"
SERVICE_DEST="/etc/systemd/system/$SERVICE_NAME.service"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   WasteNot – Service Installer       ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ---------------------------------------------------------------------------
# Validate prerequisites
# ---------------------------------------------------------------------------
if [ ! -f "$SERVICE_SRC" ]; then
    error "Service template not found: $SERVICE_SRC"
    exit 1
fi

VENV_PYTHON="$APP_DIR/venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
    error "Virtual environment not found. Please run scripts/setup.sh first."
    exit 1
fi

# ---------------------------------------------------------------------------
# Determine running user and optional env overrides
# ---------------------------------------------------------------------------
CURRENT_USER="$(whoami)"
MOCK_MODE_VAL="${MOCK_MODE:-false}"
THRESHOLD_VAL="${TVOC_ALERT_THRESHOLD:-200}"

info "Installing service for user: $CURRENT_USER"
info "App directory:               $APP_DIR"
info "MOCK_MODE:                   $MOCK_MODE_VAL"
info "TVOC_ALERT_THRESHOLD:        $THRESHOLD_VAL ppb"

# ---------------------------------------------------------------------------
# Substitute placeholders in the unit-file template
# ---------------------------------------------------------------------------
TMP_SERVICE="$(mktemp /tmp/wastenot.service.XXXXXX)"
sed \
    -e "s|%APP_DIR%|$APP_DIR|g" \
    -e "s|%USER%|$CURRENT_USER|g" \
    -e "s|%MOCK_MODE%|$MOCK_MODE_VAL|g" \
    -e "s|%TVOC_ALERT_THRESHOLD%|$THRESHOLD_VAL|g" \
    "$SERVICE_SRC" > "$TMP_SERVICE"

info "Installing service file to $SERVICE_DEST…"
sudo cp "$TMP_SERVICE" "$SERVICE_DEST"
rm -f "$TMP_SERVICE"
sudo chmod 644 "$SERVICE_DEST"

# ---------------------------------------------------------------------------
# Enable and start the service
# ---------------------------------------------------------------------------
info "Reloading systemd daemon…"
sudo systemctl daemon-reload

info "Enabling $SERVICE_NAME to start on boot…"
sudo systemctl enable "$SERVICE_NAME"

info "Starting $SERVICE_NAME now…"
sudo systemctl restart "$SERVICE_NAME"

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
sleep 2
echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Service installed successfully!    ║"
echo "╚══════════════════════════════════════╝"
echo ""
sudo systemctl status "$SERVICE_NAME" --no-pager || true
echo ""
echo "Useful commands:"
echo "  View live logs:       sudo journalctl -u $SERVICE_NAME -f"
echo "  Stop service:         sudo systemctl stop $SERVICE_NAME"
echo "  Restart service:      sudo systemctl restart $SERVICE_NAME"
echo "  Disable on boot:      sudo systemctl disable $SERVICE_NAME"
echo ""
echo "Web interface available at:"
echo "  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):5000"
echo ""
