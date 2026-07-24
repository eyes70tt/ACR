#!/usr/bin/env bash
set -euo pipefail

# NFC Web Manager - Bootstrap Installer for Raspberry Pi
# Usage: sudo bash bootstrap.sh
# Tested on: Raspberry Pi OS / Debian (arm64)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== NFC Web Manager Bootstrap ==="
echo ""

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Step 1: Install system dependencies
echo "[1/8] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq pcscd pcsc-tools libpcsclite-dev libnfc-bin libnfc-dev \
    python3 python3-pip python3-venv git build-essential autoconf automake libtool pkg-config || true

# Step 2: Blacklist kernel NFC drivers (conflict with ACR122U)
echo "[2/8] Blacklisting kernel NFC drivers..."
cat > /etc/modprobe.d/blacklist-libnfc.conf << 'CONF'
blacklist nfc
blacklist pn533
blacklist pn533_usb
CONF

# Step 3: Add udev rules for ACR122U
echo "[3/8] Adding udev rules..."
cat > /etc/udev/rules.d/99-nfc-acr122u.rules << 'RULE'
# ACR122U
SUBSYSTEM=="usb", ATTRS{idVendor}=="072f", ATTRS{idProduct}=="2200", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb_device", ATTRS{idVendor}=="072f", ATTRS{idProduct}=="2200", MODE="0664", GROUP="plugdev"
RULE
udevadm control --reload-rules || true
udevadm trigger || true

# Step 4: Create polkit rule for pi user
echo "[4/8] Creating polkit rules..."
cat > /etc/polkit-1/rules.d/99-nfc-pi.rules << 'RULES'
polkit.addRule(function(action, subject) {
    if (action.id == "org.debian.pcsc-lite.access_pcsc" && subject.user == "pi") {
        return polkit.Result.YES;
    }
    if (action.id == "org.debian.pcsc-lite.access_card" && subject.user == "pi") {
        return polkit.Result.YES;
    }
});
RULES

# Step 5: Configure libnfc for ACR122U
echo "[5/8] Configuring libnfc..."
cat > /etc/nfc/libnfc.conf << 'CONF'
allow_autoscan = true
log_level = 1
CONF

# Step 6: Create Python venv and install dependencies
echo "[6/8] Installing Python dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install --quiet fastapi uvicorn[standard] python-socketio pyscard pydantic
deactivate

# Step 7: Create password file for sudo commands
echo "[7/8] Setting up sudo helper..."
PASSWORD_FILE="/home/pi/.nfc_sudo_pw"
if [ ! -f "$PASSWORD_FILE" ]; then
    echo ""
    echo "Enter your sudo password (used for stopping/starting pcscd):"
    read -s SUDO_PW
    echo -n "$SUDO_PW" > "$PASSWORD_FILE"
    chmod 600 "$PASSWORD_FILE"
    echo "Password saved to $PASSWORD_FILE"
fi

# Step 8: Enable and start pcscd
echo "[8/8] Starting pcscd..."
systemctl enable pcscd.socket
systemctl start pcscd.socket
sleep 2

echo ""
echo "=== Bootstrap Complete! ==="
echo "Start the service with:  bash start.sh"
echo "Access the web UI at:   http://<raspberry-pi-ip>:8000"
echo ""

# Check reader
if pcsc_scan -r 2>&1 | grep -q "ACR122U\|ACS"; then
    echo "[OK] Reader detected!"
else
    echo "[WARN] Reader not detected. Check USB connection."
    echo "Try: lsusb | grep -i acs"
fi
