#!/bin/bash
# ==========================================================================
# setup_pi.sh - Full node setup on the Raspberry Pi
# Version: v8 (2026-04-11)
# Run on the Raspberry Pi: bash setup_pi.sh
#
# Prerequisites:
#   - Raspberry Pi OS (Debian 13 trixie) installed
#   - Internet connection
#   - I2C enabled (raspi-config > Interface Options > I2C > Yes)
#   - Serial enabled (raspi-config > Interface Options > Serial Port)
#       Login shell over serial: No
#       Serial port hardware: Yes
# ==========================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE_HOME="/home/<YOUR_PI_USERNAME>"

echo "=========================================="
echo "  NODE - Setup v8"
echo "  $(date)"
echo "=========================================="
echo ""

# ------------------------------------------------------------------
# 1. Check prerequisites
# ------------------------------------------------------------------
echo "=== 1/8: Checking prerequisites ==="

# Check I2C
if [ ! -d /dev/i2c-1 ] && [ ! -c /dev/i2c-1 ]; then
    echo "WARNING: I2C does not appear to be enabled"
    echo "  Run: sudo raspi-config > Interface Options > I2C > Yes"
fi

# Check serial
if [ ! -e /dev/serial0 ]; then
    echo "WARNING: serial port not enabled (/dev/serial0 does not exist)"
    echo "  Run: sudo raspi-config > Interface Options > Serial Port"
    echo "    Login shell over serial: No"
    echo "    Serial port hardware: Yes"
fi

echo "User: $(whoami)"
echo "Hostname: $(hostname)"
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)"
echo "Python: $(python3 --version)"
echo ""

# ------------------------------------------------------------------
# 2. System packages
# ------------------------------------------------------------------
echo "=== 2/8: System packages ==="
sudo apt update -qq
sudo apt install -y -qq python3-pip python3-smbus i2c-tools curl
echo "OK"
echo ""

# ------------------------------------------------------------------
# 3. Python dependencies
# ------------------------------------------------------------------
echo "=== 3/8: Python dependencies ==="
sudo pip install --break-system-packages -q \
    sdnotify \
    influxdb-client \
    pyserial \
    adafruit-blinka \
    adafruit-circuitpython-ads1x15 \
    adafruit-circuitpython-sht4x \
    adafruit-circuitpython-sgp40 \
    adafruit-circuitpython-busdevice

# Check imports
python3 -c "
import sdnotify; import influxdb_client; import serial
import board; import busio
import adafruit_ads1x15.ads1115; import adafruit_sht4x; import adafruit_sgp40
from adafruit_bus_device.i2c_device import I2CDevice
print('All dependencies OK')
"
echo ""

# ------------------------------------------------------------------
# 4. Deploy the application code
# ------------------------------------------------------------------
echo "=== 4/8: Application code ==="
mkdir -p "$NODE_HOME/Node3Code"

cp "$SCRIPT_DIR/node3AllSensorsInfluxdb.py" "$NODE_HOME/Node3Code/"
cp -r "$SCRIPT_DIR/MGSv2Lib" "$NODE_HOME/Node3Code/"
cp -r "$SCRIPT_DIR/SPS30Lib" "$NODE_HOME/Node3Code/"

echo "Node3Code:"
ls -la "$NODE_HOME/Node3Code/"
echo ""

# ------------------------------------------------------------------
# 5. systemd service
# ------------------------------------------------------------------
echo "=== 5/8: systemd service ==="
sudo cp "$SCRIPT_DIR/node3AllSensorsInfluxdb.service" /lib/systemd/system/
echo "Service copied"
echo ""

# ------------------------------------------------------------------
# 6. systemd drop-ins (override RPi OS trixie defaults)
# ------------------------------------------------------------------
echo "=== 6/8: systemd drop-ins ==="

# Watchdog: RPi OS trixie forces RuntimeWatchdogSec=1m via
# /usr/lib/systemd/system.conf.d/40-rpi-enable-watchdog.conf
# We override with 50-aqms (50 > 40)
sudo mkdir -p /etc/systemd/system.conf.d
sudo cp "$SCRIPT_DIR/systemd/50-aqms-watchdog.conf" /etc/systemd/system.conf.d/
echo "Watchdog: RuntimeWatchdogSec=12h, RebootWatchdogSec=10min"

# Journald: RPi OS trixie forces Storage=volatile via
# /usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf
# We override with 50-aqms (50 > 40)
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp "$SCRIPT_DIR/systemd/50-aqms-persistent.conf" /etc/systemd/journald.conf.d/
echo "Journald: Storage=persistent, 300M max, 3-month retention"
echo ""

# ------------------------------------------------------------------
# 7. Hardware watchdog + persistent journald
# ------------------------------------------------------------------
echo "=== 7/8: Hardware watchdog + journald ==="

# Watchdog in the device tree
if [ -f /boot/firmware/config.txt ]; then
    CFG=/boot/firmware/config.txt
else
    CFG=/boot/config.txt
fi
sudo cp "$CFG" "${CFG}.bak.$(date +%F_%H%M%S)"
grep -q '^dtparam=watchdog=on' "$CFG" || echo 'dtparam=watchdog=on' | sudo tee -a "$CFG"
echo 'bcm2835_wdt' | sudo tee /etc/modules-load.d/bcm2835_wdt.conf > /dev/null

# Journald: create the persistent directory
sudo mkdir -p /var/log/journal/$(cat /etc/machine-id)
sudo systemd-tmpfiles --create --prefix /var/log/journal
echo "Hardware watchdog and journald configured"
echo ""

# ------------------------------------------------------------------
# 8. Enable and start the service
# ------------------------------------------------------------------
echo "=== 8/8: Enable the service ==="
sudo systemctl daemon-reload
sudo systemctl enable node3AllSensorsInfluxdb.service

# Apply persistent journald
sudo systemctl restart systemd-journald
sudo journalctl --flush

# Start the service
sudo systemctl start node3AllSensorsInfluxdb.service

sleep 3
echo "--- Sensor service ---"
systemctl status node3AllSensorsInfluxdb.service --no-pager | head -5
echo ""

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo "=========================================="
echo "  SETUP COMPLETE"
echo "=========================================="
echo ""
echo "Remaining manual steps:"
echo "  1. Bring up your overlay network / VPN if the InfluxDB server is remote"
echo "  2. Reboot to activate the hardware watchdog:"
echo "       sudo reboot"
echo "  3. Verify after reboot:"
echo "       bash $SCRIPT_DIR/verify.sh"
echo ""
