#!/bin/bash
# ==========================================================================
# deploy_to_pi.sh - Deploy the node firmware from your workstation
# Version: v8 (2026-04-11)
# Run from your machine: bash deploy_to_pi.sh [user@host]
#
# Example:
#   bash deploy_to_pi.sh                         # uses <YOUR_PI_USERNAME>@<YOUR_PI_HOST> by default
#   bash deploy_to_pi.sh <YOUR_PI_USERNAME>@<YOUR_PI_HOST>   # custom host or IP
# ==========================================================================

PI="${1:-<YOUR_PI_USERNAME>@<YOUR_PI_HOST>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="/tmp/node_v8_deploy"

echo "=========================================="
echo "  NODE - Deploy v8"
echo "  Target: $PI"
echo "  $(date)"
echo "=========================================="
echo ""

# ------------------------------------------------------------------
# 1. Check SSH connectivity
# ------------------------------------------------------------------
echo "=== 1/4: Checking connectivity ==="
HOST=$(echo "$PI" | cut -d@ -f2)
if ssh-keygen -F "$HOST" &>/dev/null; then
    echo "Host key OK for $HOST"
else
    echo "Host key not found for $HOST"
    echo "If you reinstalled the OS, remove the old key with:"
    echo "  ssh-keygen -R $HOST"
    echo ""
    echo "Continuing (SSH will ask you to confirm the new fingerprint)..."
fi
echo ""

# ------------------------------------------------------------------
# 2. Create the remote directory and copy files
# ------------------------------------------------------------------
echo "=== 2/4: Copying files to the Pi ==="
ssh "$PI" "rm -rf $REMOTE_DIR && mkdir -p $REMOTE_DIR/systemd $REMOTE_DIR/MGSv2Lib $REMOTE_DIR/SPS30Lib/i2c"

# Main code
scp "$SCRIPT_DIR/node3AllSensorsInfluxdb.py" "$PI:$REMOTE_DIR/"

# Libraries
scp "$SCRIPT_DIR/MGSv2Lib/__init__.py" "$SCRIPT_DIR/MGSv2Lib/multichannel_gas_gmxxx.py" "$PI:$REMOTE_DIR/MGSv2Lib/"
scp "$SCRIPT_DIR/SPS30Lib/__init__.py" "$SCRIPT_DIR/SPS30Lib/sps30.py" "$PI:$REMOTE_DIR/SPS30Lib/"
scp "$SCRIPT_DIR/SPS30Lib/i2c/__init__.py" "$SCRIPT_DIR/SPS30Lib/i2c/i2c.py" "$PI:$REMOTE_DIR/SPS30Lib/i2c/"

# Service and configs
scp "$SCRIPT_DIR/node3AllSensorsInfluxdb.service" "$PI:$REMOTE_DIR/"
scp "$SCRIPT_DIR/systemd/50-aqms-watchdog.conf" "$SCRIPT_DIR/systemd/50-aqms-persistent.conf" "$PI:$REMOTE_DIR/systemd/"

# Scripts
scp "$SCRIPT_DIR/setup_pi.sh" "$SCRIPT_DIR/verify.sh" "$PI:$REMOTE_DIR/"

echo "Files copied"
echo ""

# ------------------------------------------------------------------
# 3. Run setup on the Pi
# ------------------------------------------------------------------
echo "=== 3/4: Running setup on the Pi ==="
echo "(This requires the sudo password on the Pi)"
echo ""
ssh -t "$PI" "bash $REMOTE_DIR/setup_pi.sh"

# ------------------------------------------------------------------
# 4. Done
# ------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  DEPLOY COMPLETE"
echo "=========================================="
echo ""
echo "Remaining steps on the Pi:"
echo "  1. Bring up your overlay network / VPN (if used)"
echo "  2. sudo raspi-config  > Interface Options > Serial Port"
echo "     - Login shell over serial: No"
echo "     - Serial port hardware: Yes"
echo "  3. sudo reboot"
echo "  4. ssh $PI 'bash $REMOTE_DIR/verify.sh'"
echo ""
