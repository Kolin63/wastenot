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
VENV_DIR="$APP_DIR/venv"

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
    info "Configuring CSI camera interface for libcamera/picamera2…"

    # Determine the correct config.txt path.
    # Raspberry Pi OS Bookworm stores it under /boot/firmware/; older releases
    # use /boot/config.txt directly.
    if [ -f /boot/firmware/config.txt ]; then
        CONFIG_TXT="/boot/firmware/config.txt"
    else
        CONFIG_TXT="/boot/config.txt"
    fi

    # The legacy camera stack (start_x=1, set by `raspi-config do_camera 0`)
    # uses the bcm2835 V4L2 driver and is INCOMPATIBLE with libcamera and
    # picamera2.  If it was previously enabled, disable it now so that
    # libcamera can take control of the camera hardware.
    if grep -q "^start_x=1" "$CONFIG_TXT" 2>/dev/null; then
        warn "Legacy camera (start_x=1) found in $CONFIG_TXT."
        warn "Disabling it – picamera2 requires the libcamera stack."
        sudo sed -i 's/^start_x=1/start_x=0/' "$CONFIG_TXT"
        info "Legacy camera disabled in $CONFIG_TXT."
    fi

    # Ensure camera auto-detection is enabled for the libcamera stack.
    # This is already the default on Raspberry Pi OS Bookworm but may be
    # absent on older images.
    if ! grep -q "^camera_auto_detect" "$CONFIG_TXT" 2>/dev/null; then
        echo "camera_auto_detect=1" | sudo tee -a "$CONFIG_TXT" > /dev/null
        info "Added camera_auto_detect=1 to $CONFIG_TXT."
    fi

    info "A reboot will be required for camera config changes to take effect."

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
# The venv must be created with --system-site-packages so that
# system-installed packages such as python3-picamera2 (which are not
# available on PyPI and cannot be installed via pip) are accessible when
# the application runs under the systemd service.  If an existing venv was
# created without this flag, recreate it so the camera works in daemon mode.
if [ -d "$VENV_DIR" ]; then
    if grep -q "include-system-site-packages = false" "$VENV_DIR/pyvenv.cfg" 2>/dev/null; then
        warn "Existing virtual environment lacks --system-site-packages."
        warn "Recreating it so that system packages (e.g. picamera2) are accessible."
        rm -rf "$VENV_DIR"
    else
        info "Virtual environment already exists with system-site-packages – skipping creation."
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    info "Creating Python virtual environment at $VENV_DIR…"
    python3 -m venv --system-site-packages "$VENV_DIR"
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
