#!/usr/bin/env bash
# =============================================================================
# WasteNot – Setup Script
# =============================================================================
# Installs all system and Python dependencies needed to run the WasteNot
# ethylene-sensor web application on a Raspberry Pi (or any Debian-based
# Linux system).
#
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
#
# Optional environment variables:
#   MOCK_MODE=true   – skip hardware/I²C setup (useful on non-Pi machines)
# =============================================================================

set -euo pipefail

# Resolve the repo root regardless of where the script is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════╗"
echo "║   WasteNot – Setup Script            ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ---------------------------------------------------------------------------
# 1. Detect Raspberry Pi
# ---------------------------------------------------------------------------
IS_RPI=false
if grep -qi "raspberry pi" /proc/cpuinfo 2>/dev/null; then
    IS_RPI=true
    info "Raspberry Pi detected."
else
    warn "Raspberry Pi NOT detected."
    warn "I²C and hardware setup steps will be skipped."
    warn "The application will run in MOCK_MODE (simulated sensor data)."
fi

# ---------------------------------------------------------------------------
# 2. System package updates
# ---------------------------------------------------------------------------
info "Updating package list…"
sudo apt-get update -y

info "Installing required system packages…"
sudo apt-get install -y python3 python3-pip python3-venv i2c-tools

# ---------------------------------------------------------------------------
# 3. Enable I²C (Raspberry Pi only)
# ---------------------------------------------------------------------------
if [ "$IS_RPI" = "true" ]; then
    info "Enabling I²C interface via raspi-config…"
    # raspi-config nonint do_i2c 0 enables I2C (0 = enable)
    if command -v raspi-config &>/dev/null; then
        sudo raspi-config nonint do_i2c 0
        info "I²C enabled. A reboot may be required for this to take effect."
    else
        warn "raspi-config not found – please enable I²C manually:"
        warn "  sudo nano /boot/config.txt  →  add: dtparam=i2c_arm=on"
    fi

    # Verify the SGP30 is visible on the I²C bus (address 0x58)
    info "Scanning I²C bus…"
    if sudo i2cdetect -y 1 2>/dev/null | grep -q "58"; then
        info "SGP30 found on I²C bus at address 0x58."
    else
        warn "SGP30 not detected on I²C bus. Check wiring (see README.md)."
        warn "You can still run the app in MOCK_MODE=true until the sensor"
        warn "is connected."
    fi
fi

# ---------------------------------------------------------------------------
# 4. Enable camera (CSI) and install picamera2 (Raspberry Pi only)
# ---------------------------------------------------------------------------
if [ "$IS_RPI" = "true" ]; then
    info "Enabling CSI camera interface…"
    if command -v raspi-config &>/dev/null; then
        # do_camera 0 = enable legacy camera; for picamera2 we use the libcamera stack
        sudo raspi-config nonint do_camera 0 2>/dev/null || true
    fi

    # Ensure the libcamera stack and picamera2 are present
    info "Installing libcamera and picamera2…"
    sudo apt-get install -y libcamera-apps python3-picamera2 \
        python3-libcamera python3-kms++ libcap-dev

    # Install OpenCV system libraries (needed by opencv-python-headless)
    info "Installing OpenCV system dependencies…"
    sudo apt-get install -y libopencv-dev python3-opencv
else
    info "Installing OpenCV system dependencies (non-Pi)…"
    sudo apt-get install -y libopencv-dev 2>/dev/null || true
fi
# ---------------------------------------------------------------------------
# 5. Python virtual environment
# ---------------------------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python virtual environment at $VENV_DIR…"
    python3 -m venv "$VENV_DIR"
else
    info "Virtual environment already exists – skipping creation."
fi

info "Installing Python dependencies…"
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet
info "Python dependencies installed."

# ---------------------------------------------------------------------------
# 6. Done
# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Setup complete!                    ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "To start the application manually:"
echo ""
if [ "$IS_RPI" = "true" ]; then
    echo "  cd $APP_DIR"
    echo "  source venv/bin/activate"
    echo "  python app.py"
else
    echo "  cd $APP_DIR"
    echo "  MOCK_MODE=true venv/bin/python app.py"
fi
echo ""
echo "Then open a browser at:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost):5000"
echo ""
echo "To install as a background service that starts on boot, run:"
echo "  ./scripts/install_service.sh"
echo ""
