#!/bin/bash
# ==========================================================================
# verify.sh - Post-deploy verification on the Pi
# Run on the Pi after reboot: bash verify.sh
# Optional: export AQMS_INFLUX_HOST=<THE_IP_OF_THE_INFLUXDB_SERVER> first.
# ==========================================================================

echo "=========================================="
echo "  NODE - Verification v8"
echo "  $(date)"
echo "=========================================="
echo ""

PASS=0
WARN=0
FAIL=0

check_pass() { echo "  [OK]   $1"; PASS=$((PASS+1)); }
check_warn() { echo "  [WARN] $1"; WARN=$((WARN+1)); }
check_fail() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

# 1. Service
echo "=== Service ==="
systemctl is-active --quiet node3AllSensorsInfluxdb.service \
    && check_pass "Sensor service: active" \
    || check_fail "Sensor service: inactive"

systemctl is-enabled --quiet node3AllSensorsInfluxdb.service \
    && check_pass "Sensor service: enabled" \
    || check_fail "Sensor service: not enabled"
echo ""

# 2. Hardware watchdog
echo "=== Hardware Watchdog ==="
WD_LOG=$(journalctl -b | grep -i "watchdog running" | tail -1)
if echo "$WD_LOG" | grep -q "12h"; then
    check_pass "RuntimeWatchdogSec: 12h"
elif echo "$WD_LOG" | grep -q "watchdog"; then
    check_warn "Watchdog active but not 12h: $WD_LOG"
else
    check_fail "Hardware watchdog not detected"
fi

journalctl -b | grep -qi "BCM2835 watchdog" \
    && check_pass "BCM2835 watchdog timer loaded" \
    || check_warn "BCM2835 not found in the journal"
echo ""

# 3. Persistent journald
echo "=== Journald ==="
BOOT_COUNT=$(journalctl --list-boots 2>/dev/null | wc -l)
if [ "$BOOT_COUNT" -gt 1 ]; then
    check_pass "Persistent journal: $BOOT_COUNT boots stored"
elif [ "$BOOT_COUNT" -eq 1 ]; then
    check_warn "Persistent journal: only 1 boot (check after another reboot)"
else
    check_fail "Persistent journal: no boots"
fi

ls /var/log/journal/$(cat /etc/machine-id)/*.journal &>/dev/null \
    && check_pass "Journal files on disk: OK" \
    || check_fail "No journal files on disk"

DISK=$(journalctl --disk-usage 2>/dev/null | grep -oP '[\d.]+[KMGT]')
echo "  [INFO] Journal disk usage: $DISK"
echo ""

# 4. InfluxDB
echo "=== InfluxDB ==="
INFLUX_HOST="${AQMS_INFLUX_HOST:-<THE_IP_OF_THE_INFLUXDB_SERVER>}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "http://${INFLUX_HOST}:8086/health" 2>/dev/null)
if [ "$HTTP_CODE" = "200" ]; then
    check_pass "InfluxDB reachable ($INFLUX_HOST)"
else
    check_warn "InfluxDB not reachable (HTTP $HTTP_CODE). Normal if offline."
fi

# Check the last sync log (the app logs this message in Spanish)
LAST_SYNC=$(grep -i "sincroniz" /home/<YOUR_PI_USERNAME>/Node3Code/logs.log 2>/dev/null | tail -1)
if echo "$LAST_SYNC" | grep -qi "correctamente"; then
    check_pass "Last synchronisation: successful"
    echo "  [INFO] $LAST_SYNC"
elif echo "$LAST_SYNC" | grep -qi "sincroniz"; then
    check_warn "Last synchronisation: review"
    echo "  [INFO] $LAST_SYNC"
else
    check_warn "No synchronisation records in the log"
fi
echo ""

# 5. Sensors (the app logs these messages in Spanish)
echo "=== Sensors ==="
SENSOR_LOG=$(grep "inicializ" /home/<YOUR_PI_USERNAME>/Node3Code/logs.log 2>/dev/null | tail -10)

echo "$SENSOR_LOG" | grep -qi "ADS1115 inicializados" \
    && check_pass "ADS1115 (x3): OK" \
    || check_fail "ADS1115: initialisation error"

echo "$SENSOR_LOG" | grep -qi "SHT45" \
    && check_pass "SHT45: OK" \
    || check_fail "SHT45: not detected"

echo "$SENSOR_LOG" | grep -qi "SGP40" \
    && check_pass "SGP40: OK" \
    || check_fail "SGP40: not detected"

echo "$SENSOR_LOG" | grep -qi "MGSv2" \
    && check_pass "MGSv2: OK" \
    || check_fail "MGSv2: not detected"

echo "$SENSOR_LOG" | grep -qi "SPS30" \
    && check_pass "SPS30: OK" \
    || check_warn "SPS30: not detected (may take time to initialise)"
echo ""

# 6. Serial (APC220)
echo "=== Serial (APC220) ==="
[ -e /dev/serial0 ] \
    && check_pass "/dev/serial0 available" \
    || check_fail "/dev/serial0 does not exist"
echo ""

# Summary
echo "=========================================="
echo "  RESULTS: $PASS OK, $WARN WARN, $FAIL FAIL"
echo "=========================================="
