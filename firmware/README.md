# Station firmware

The acquisition software that runs on each node (Raspberry Pi Zero 2 W). It
reads every sensor on a 30-second cycle, stores each reading in a local SQLite
buffer, and synchronises buffered readings to an InfluxDB time-series database
in batches whenever the server is reachable.

## Design points

- **Never loses data.** Readings are written to SQLite first; if the database
  server is unreachable the node keeps buffering and syncs later.
- **Runs unattended for months.** A systemd watchdog and a hardware watchdog
  restart the service or the board if it hangs; the I2C bus and individual
  sensors are recovered and reconnected automatically after transient faults.
- **No secrets in the code.** Connection settings come from environment
  variables.

## Configuration

Set these environment variables (for example in `/etc/aqms.env`, read by the
systemd unit):

```
AQMS_INFLUX_URL=http://<THE_IP_OF_THE_INFLUXDB_SERVER>:8086
AQMS_INFLUX_TOKEN=<YOUR_INFLUXDB_TOKEN>
AQMS_INFLUX_ORG=<YOUR_INFLUXDB_ORG>
AQMS_INFLUX_BUCKET=<YOUR_INFLUXDB_BUCKET>
```

## Layout

- `node3AllSensorsInfluxdb.py` - the main acquisition and sync loop.
- `MGSv2Lib/`, `SPS30Lib/` - sensor libraries.
- `node3AllSensorsInfluxdb.service` - systemd unit.
- `systemd/` - drop-ins that set the watchdog and persistent journald.
- `deploy_to_pi.sh`, `setup_pi.sh`, `verify.sh` - deployment helpers.

## Per-node differences

Every node runs this same code. Two things change per node: the `TAGS` block
at the top of `node3AllSensorsInfluxdb.py` (node id, site, coordinates,
exposure) and the sensor subset - nodes without the Alphasense mid-cost cells
simply do not record those signals.
