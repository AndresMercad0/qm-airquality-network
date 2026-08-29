# Changelog - Node firmware

## v8 (2026-04-11) - Debian 13 (trixie) compatibility + automated deployment

- InfluxDB connection settings moved to environment variables (previously
  hardcoded).
- ADS1115 pin constants `ADS.P0`..`ADS.P3` replaced with integers `0`..`3`
  (the `adafruit-circuitpython-ads1x15` 3.x library removed those constants).
- Debian 13 compatibility: systemd drop-ins override the RPi OS defaults for
  the watchdog and journald storage; `pip install` uses `--break-system-packages`.
- Automated deployment scripts: `deploy_to_pi.sh`, `setup_pi.sh`, `verify.sh`.

## v7 (2026-02-14) - Operational hardening

- No functional changes to acquisition or synchronisation.
- Hardware watchdog (`bcm2835_wdt`) and persistent `journald`.

## v6 - Functional baseline

- Full sensor support, SQLite WAL buffer with sync to InfluxDB, and a systemd
  service watchdog.
