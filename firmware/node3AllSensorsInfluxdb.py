import os
import time
import logging
import json
import sqlite3
import datetime
import signal

import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import adafruit_sht4x
import adafruit_sgp40
from MGSv2Lib.multichannel_gas_gmxxx import MultichannelGasGMXXX
from SPS30Lib.sps30 import SPS30
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

import socket

# systemd watchdog (optional)
try:
    import sdnotify
    SYSTEMD_NOTIFY = True
    systemd_notifier = sdnotify.SystemdNotifier()
except ImportError:
    SYSTEMD_NOTIFY = False
    systemd_notifier = None

# -------------------------------------------------------------------------
# Configuration constants
# -------------------------------------------------------------------------
SENSOR_INIT_TIMEOUT = 10        # Per-sensor initialisation timeout (seconds)
I2C_ERROR_THRESHOLD = 10        # Consecutive I2C errors before resetting the bus
SENSOR_RECONNECT_INTERVAL = 10  # Try to reconnect sensors every N cycles (5 min)

# -------------------------------------------------------------------------
# Tag constants for this node
# -------------------------------------------------------------------------
TAGS = {
    "NodeID": "node_3",
    "Site": "Queen Mary University of London",
    "Subsite": "Mile End Road",
    "Exposure": "Outdoor",
    "Environment": "Roadside - Urban Traffic",
    "Latitude": "51.522530",
    "Longitude": "-0.042155"
}


# -------------------------------------------------------------------------
# InfluxDB configuration (read from environment variables; see the README)
# -------------------------------------------------------------------------
bucket = os.environ.get("AQMS_INFLUX_BUCKET", "<YOUR_INFLUXDB_BUCKET>")
org = os.environ.get("AQMS_INFLUX_ORG", "<YOUR_INFLUXDB_ORG>")
token = os.environ.get("AQMS_INFLUX_TOKEN", "")
url = os.environ.get("AQMS_INFLUX_URL", "http://<THE_IP_OF_THE_INFLUXDB_SERVER>:8086")

# -------------------------------------------------------------------------
# Global parameter: batch size for synchronisation
# -------------------------------------------------------------------------
BATCH_SIZE = 1000

# -------------------------------------------------------------------------
# Logging configuration (INFO+ to console, DEBUG+ to file)
# -------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(script_dir, "logs.log")

logger = logging.getLogger("AQMS")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)


# -------------------------------------------------------------------------
# Initialisation timeout class
# -------------------------------------------------------------------------
class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("Timeout durante inicializacion de sensor")

# -------------------------------------------------------------------------
# Global sensor variables (may be None if they fail)
# -------------------------------------------------------------------------
i2c = None
MQ131x48 = None
ALPHAx49 = None
ALPHAx4A = None
MQ131_signal = None
NO2_OP1 = None
NO2_OP2 = None
OZONE_OP1 = None
OZONE_OP2 = None
CO_OP1 = None
CO_OP2 = None
sht = None
sgp = None
mcgv2 = None
pm_sensor = None

# Counters for reconnection and errors
_consecutive_i2c_errors = 0
_cycle_counter = 0
_sps30_stats_counter = 0
_SPS30_STATS_INTERVAL = 20  # Print stats every 20 cycles (~10 minutes)

# -------------------------------------------------------------------------
# Initialisation functions with timeout
# -------------------------------------------------------------------------
def init_with_timeout(init_func, sensor_name, timeout_sec=SENSOR_INIT_TIMEOUT):
    """
    Run an initialisation function with a timeout.
    Return the result, or None on failure/timeout.
    """
    # Set up the alarm
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_sec)

    try:
        result = init_func()
        signal.alarm(0)  # Cancel the alarm
        return result
    except TimeoutError:
        logger.error("%s: Timeout de %ds durante inicializacion", sensor_name, timeout_sec)
        return None
    except Exception as e:
        logger.exception("%s: Error durante inicializacion: %s", sensor_name, type(e).__name__)
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def init_i2c_bus():
    """Initialise the I2C bus."""
    global i2c
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        logger.info("Bus I2C inicializado correctamente")
        return True
    except Exception as e:
        logger.exception("Error al inicializar bus I2C: %s", type(e).__name__)
        i2c = None
        return False


def init_ads1115_sensors():
    """Initialise the ADS1115 sensors and their channels."""
    global MQ131x48, ALPHAx49, ALPHAx4A
    global MQ131_signal, NO2_OP1, NO2_OP2, OZONE_OP1, OZONE_OP2, CO_OP1, CO_OP2

    if i2c is None:
        logger.warning("ADS1115: Bus I2C no disponible")
        return False

    try:
        # ADS1115 at address 0x48
        def init_mq131x48():
            ads = ADS.ADS1115(i2c, address=0x48)
            ads.gain = 2/3
            return ads
        MQ131x48 = init_with_timeout(init_mq131x48, "ADS1115@0x48")

        # ADS1115 at address 0x49
        def init_alphax49():
            ads = ADS.ADS1115(i2c, address=0x49)
            ads.gain = 2/3
            return ads
        ALPHAx49 = init_with_timeout(init_alphax49, "ADS1115@0x49")

        # ADS1115 at address 0x4A
        def init_alphax4a():
            ads = ADS.ADS1115(i2c, address=0x4A)
            ads.gain = 2/3
            return ads
        ALPHAx4A = init_with_timeout(init_alphax4a, "ADS1115@0x4A")

        # Analogue channels (pin numbers: P0=0, P1=1, P2=2, P3=3)
        if MQ131x48:
            MQ131_signal = AnalogIn(MQ131x48, 1)
        if ALPHAx49:
            NO2_OP1 = AnalogIn(ALPHAx49, 0)
            NO2_OP2 = AnalogIn(ALPHAx49, 1)
        if ALPHAx4A:
            OZONE_OP1 = AnalogIn(ALPHAx4A, 0)
            OZONE_OP2 = AnalogIn(ALPHAx4A, 1)
            CO_OP1 = AnalogIn(ALPHAx4A, 2)
            CO_OP2 = AnalogIn(ALPHAx4A, 3)
        
        status = []
        if MQ131x48: status.append("0x48")
        if ALPHAx49: status.append("0x49")
        if ALPHAx4A: status.append("0x4A")
        
        if status:
            logger.info("ADS1115 inicializados: %s", ", ".join(status))
            return True
        else:
            logger.warning("ADS1115: Ningun sensor inicializado")
            return False
            
    except Exception as e:
        logger.error("ADS1115: Error general: %s", e)
        return False


def init_sht45_sensor():
    """Initialise the SHT45 sensor."""
    global sht
    
    if i2c is None:
        logger.warning("SHT45: Bus I2C no disponible")
        return False
    
    def init_sht():
        s = adafruit_sht4x.SHT4x(i2c)
        s.mode = adafruit_sht4x.Mode.NOHEAT_HIGHPRECISION
        return s
    
    sht = init_with_timeout(init_sht, "SHT45")
    
    if sht:
        logger.info("SHT45 con serial %s en modo %s",
                    hex(sht.serial_number),
                    adafruit_sht4x.Mode.string[sht.mode])
        return True
    else:
        logger.warning("SHT45: No disponible, reintentando en %d ciclos", SENSOR_RECONNECT_INTERVAL)
        return False


def init_sgp40_sensor():
    """Initialise the SGP40 sensor."""
    global sgp
    
    if i2c is None:
        logger.warning("SGP40: Bus I2C no disponible")
        return False
    
    def init_sgp_func():
        return adafruit_sgp40.SGP40(i2c)
    
    sgp = init_with_timeout(init_sgp_func, "SGP40")
    
    if sgp:
        logger.info("SGP40 inicializado correctamente")
        return True
    else:
        logger.warning("SGP40: No disponible, reintentando en %d ciclos", SENSOR_RECONNECT_INTERVAL)
        return False


def init_mcgv2_sensor():
    """Initialise the Multichannel Gas v2 sensor."""
    global mcgv2
    
    if i2c is None:
        logger.warning("MGSv2: Bus I2C no disponible")
        return False
    
    def init_mcg():
        return MultichannelGasGMXXX(i2c)
    
    mcgv2 = init_with_timeout(init_mcg, "MGSv2")
    
    if mcgv2:
        logger.info("MGSv2 inicializado correctamente")
        return True
    else:
        logger.warning("MGSv2: No disponible, reintentando en %d ciclos", SENSOR_RECONNECT_INTERVAL)
        return False


def init_sps30_sensor():
    """
    Initialise the SPS30 sensor with a robust sequence.
    Includes wakeup() + reset() to recover the sensor from inconsistent
    states (e.g. after a power cut or an abrupt restart).
    """
    global pm_sensor

    def init_pm():
        pm = SPS30(logger="AQMS", retries=3)

        # Try to wake the sensor (it may be in sleep mode)
        try:
            pm.wakeup()
            time.sleep(0.1)
        except:
            pass

        # Reset the sensor to bring it to a known state
        try:
            pm.reset()
            time.sleep(0.5)  # The reset needs time
        except:
            pass

        # Check communication by reading the firmware version
        fw = pm.firmware_version()

        # Check there is no CRC error in the response
        if fw and "CRC" in fw:
            raise Exception(f"SPS30: Error de CRC en firmware: {fw}")
        
        pt = pm.product_type()
        sn = pm.serial_number()
        pm.start_measurement()
        time.sleep(3)
        return pm, fw, pt, sn
    
    result = init_with_timeout(init_pm, "SPS30")
    
    if result:
        pm_sensor, fw, pt, sn = result
        logger.info("SPS30 - Firmware: %s | Producto: %s | Serial: %s | Modo: SINCRONO", fw, pt, sn)
        return True
    else:
        pm_sensor = None
        logger.warning("SPS30: No disponible, reintentando en %d ciclos", SENSOR_RECONNECT_INTERVAL)
        return False


def init_all_sensors():
    """Initialise all sensors."""
    logger.info("-"*60)
    logger.info("Iniciando inicializacion de sensores...")
    
    if not init_i2c_bus():
        logger.error("CRITICO: No se pudo inicializar el bus I2C")
        return False
    
    init_ads1115_sensors()
    init_sht45_sensor()
    init_sgp40_sensor()
    init_mcgv2_sensor()
    init_sps30_sensor()
    
    logger.info("Inicializacion completada")
    logger.info("-"*60)
    return True


def reinit_i2c_bus():
    """Reinitialise the I2C bus and all sensors."""
    global i2c, _consecutive_i2c_errors

    logger.warning("."*60)
    logger.warning("REINICIALIZANDO BUS I2C por %d errores consecutivos", _consecutive_i2c_errors)
    logger.warning("."*60)

    # Close the current bus if it exists
    try:
        if i2c:
            i2c.deinit()
    except:
        pass

    time.sleep(2)  # Wait before reinitialising

    # Reinitialise everything
    _consecutive_i2c_errors = 0
    init_all_sensors()

    logger.info("Bus I2C reinicializado")


def try_reconnect_sensors():
    """Try to reconnect sensors that are currently None."""
    global _cycle_counter
    
    _cycle_counter += 1
    
    if _cycle_counter < SENSOR_RECONNECT_INTERVAL:
        return
    
    _cycle_counter = 0
    reconnected = []
    
    if sht is None:
        if init_sht45_sensor():
            reconnected.append("SHT45")
    
    if sgp is None:
        if init_sgp40_sensor():
            reconnected.append("SGP40")
    
    if mcgv2 is None:
        if init_mcgv2_sensor():
            reconnected.append("MGSv2")
    
    if pm_sensor is None:
        if init_sps30_sensor():
            reconnected.append("SPS30")
    
    # ADS1115
    if MQ131x48 is None or ALPHAx49 is None or ALPHAx4A is None:
        if init_ads1115_sensors():
            reconnected.append("ADS1115")
    
    if reconnected:
        logger.info("Sensores reconectados: %s", ", ".join(reconnected))


def register_i2c_error():
    """Record an I2C error and reset the bus if it exceeds the threshold."""
    global _consecutive_i2c_errors
    _consecutive_i2c_errors += 1

    if _consecutive_i2c_errors >= I2C_ERROR_THRESHOLD:
        reinit_i2c_bus()


def register_i2c_success():
    """Record a successful I2C operation, resetting the counter."""
    global _consecutive_i2c_errors
    _consecutive_i2c_errors = 0


# -------------------------------------------------------------------------
# Helper function to add tags to a Point
# -------------------------------------------------------------------------
def add_tags(point, tags_dict):
    for k, v in tags_dict.items():
        point.tag(k, v)
    return point

# -------------------------------------------------------------------------
# Sensor reads (each function returns a Point or None)
# -------------------------------------------------------------------------

# NO2
def read_no2_alpha(measurement_time):
    if NO2_OP1 is None or NO2_OP2 is None:
        return None
    try:
        pt = Point("NO2")
        pt.tag("SensorModel", "Alphasense")
        pt.tag("SensorCost", "Mid")
        pt = add_tags(pt, TAGS)
        pt.time(measurement_time, WritePrecision.S)
        pt = (pt.field("op1_raw", int(NO2_OP1.value))
                .field("op1_voltage", float(round(NO2_OP1.voltage, 5)))
                .field("op2_raw", int(NO2_OP2.value))
                .field("op2_voltage", float(round(NO2_OP2.voltage, 5))))
        register_i2c_success()
        return pt
    except Exception as e:
        logger.exception("NO2_Alpha: %s", type(e).__name__)
        register_i2c_error()
        return None

def read_no2_mgsv2(measurement_time):
    if mcgv2 is None:
        return None
    try:
        pt = Point("NO2")
        pt.tag("SensorModel", "MGSv2")
        pt.tag("SensorCost", "Low")
        pt = add_tags(pt, TAGS)
        pt.time(measurement_time, WritePrecision.S)
        pt = pt.field("raw", int(mcgv2.measure_no2()))
        register_i2c_success()
        return pt
    except Exception as e:
        logger.exception("NO2_MGSv2: %s", type(e).__name__)
        register_i2c_error()
        return None

# Ozone (O3)
def read_ozone_alpha(measurement_time):
    if OZONE_OP1 is None or OZONE_OP2 is None:
        return None
    try:
        pt = Point("Ozone")
        pt.tag("SensorModel", "Alphasense")
        pt.tag("SensorCost", "Mid")
        pt = add_tags(pt, TAGS)
        pt.time(measurement_time, WritePrecision.S)
        pt = (pt.field("op1_raw", int(OZONE_OP1.value))
                .field("op1_voltage", float(round(OZONE_OP1.voltage, 5)))
                .field("op2_raw", int(OZONE_OP2.value))
                .field("op2_voltage", float(round(OZONE_OP2.voltage, 5))))
        register_i2c_success()
        return pt
    except Exception as e:
        logger.exception("Ozone_Alpha: %s", type(e).__name__)
        register_i2c_error()
        return None

def read_ozone_mq131(measurement_time):
    if MQ131_signal is None:
        return None
    try:
        pt = Point("Ozone")
        pt.tag("SensorModel", "MQ131")
        pt.tag("SensorCost", "Low")
        pt = add_tags(pt, TAGS)
        pt.time(measurement_time, WritePrecision.S)
        pt = (pt.field("raw", int(MQ131_signal.value))
                .field("voltage", float(round(MQ131_signal.voltage, 5))))
        register_i2c_success()
        return pt
    except Exception as e:
        logger.exception("Ozone_MQ131: %s", type(e).__name__)
        register_i2c_error()
        return None

# CO
def read_co_alpha(measurement_time):
    if CO_OP1 is None or CO_OP2 is None:
        return None
    try:
        pt = Point("CO")
        pt.tag("SensorModel", "Alphasense")
        pt.tag("SensorCost", "Mid")
        pt = add_tags(pt, TAGS)
        pt.time(measurement_time, WritePrecision.S)
        pt = (pt.field("op1_raw", int(CO_OP1.value))
                .field("op1_voltage", float(round(CO_OP1.voltage, 5)))
                .field("op2_raw", int(CO_OP2.value))
                .field("op2_voltage", float(round(CO_OP2.voltage, 5))))
        register_i2c_success()
        return pt
    except Exception as e:
        logger.exception("CO_Alpha: %s", type(e).__name__)
        register_i2c_error()
        return None

def read_co_mgsv2(measurement_time):
    if mcgv2 is None:
        return None
    try:
        pt = Point("CO")
        pt.tag("SensorModel", "MGSv2")
        pt.tag("SensorCost", "Low")
        pt = add_tags(pt, TAGS)
        pt.time(measurement_time, WritePrecision.S)
        pt = pt.field("raw", int(mcgv2.measure_co()))
        register_i2c_success()
        return pt
    except Exception as e:
        logger.exception("CO_MGSv2: %s", type(e).__name__)
        register_i2c_error()
        return None

# Temperature and humidity
def read_sht45_temp_and_hum(measurement_time):
    if sht is None:
        return None, None, None, None
    try:
        t, h = sht.measurements
        pt_temp = Point("Temperature")
        pt_temp.tag("SensorModel", "SHT45")
        pt_temp.tag("SensorCost", "Low")
        pt_temp = add_tags(pt_temp, TAGS)
        pt_temp.time(measurement_time, WritePrecision.S)
        pt_temp = pt_temp.field("celsius", float(round(t, 2)))
        pt_hum = Point("Humidity")
        pt_hum.tag("SensorModel", "SHT45")
        pt_hum.tag("SensorCost", "Low")
        pt_hum = add_tags(pt_hum, TAGS)
        pt_hum.time(measurement_time, WritePrecision.S)
        pt_hum = pt_hum.field("percentage", float(round(h, 2)))
        register_i2c_success()
        return pt_temp, pt_hum, t, h
    except Exception as e:
        logger.exception("SHT45: %s", type(e).__name__)
        register_i2c_error()
        return None, None, None, None

# VOC Index
def read_sgp40(temp, hum, measurement_time):
    if sgp is None:
        return None
    if temp is None or hum is None:
        # No temperature/humidity data available, use default values
        temp = 25.0
        hum = 50.0
    try:
        pt = Point("VOC")
        pt.tag("SensorModel", "SGP40")
        pt.tag("SensorCost", "Low")
        pt = add_tags(pt, TAGS)
        pt.time(measurement_time, WritePrecision.S)
        pt = (pt.field("compensated_raw_gas",
                       int(sgp.measure_raw(temperature=temp, relative_humidity=hum)))
                .field("index",
                       int(sgp.measure_index(temperature=temp, relative_humidity=hum))))
        register_i2c_success()
        return pt
    except Exception as e:
        logger.exception("SGP40: %s", type(e).__name__)
        register_i2c_error()
        return None

# PM2.5 & PM10
def read_sps30(measurement_time):
    """
    Read data from the SPS30 using the improved library.
    get_measurement() returns the latest valid reading and clears the queue.
    """
    if pm_sensor is None:
        return []
    
    try:
        pm_data = pm_sensor.get_measurement()
        if pm_data:
            logger.info("SPS30: Lectura OK - PM2.5=%.2f ug/m3, PM10=%.2f ug/m3",
                        pm_data['sensor_data']['mass_density']['pm2.5'],
                        pm_data['sensor_data']['mass_density']['pm10'])
            
            pt_pm25 = Point("PM2_5")
            pt_pm25.tag("SensorModel", "SPS30")
            pt_pm25.tag("SensorCost", "Low")
            pt_pm25 = add_tags(pt_pm25, TAGS)
            pt_pm25.time(measurement_time, WritePrecision.S)
            pt_pm25 = pt_pm25.field("micrograms_per_cubic_meter", float(pm_data['sensor_data']['mass_density']['pm2.5']))

            pt_pm10 = Point("PM10")
            pt_pm10.tag("SensorModel", "SPS30")
            pt_pm10.tag("SensorCost", "Low")
            pt_pm10 = add_tags(pt_pm10, TAGS)
            pt_pm10.time(measurement_time, WritePrecision.S)
            pt_pm10 = pt_pm10.field("micrograms_per_cubic_meter", float(pm_data['sensor_data']['mass_density']['pm10']))

            register_i2c_success()
            return [pt_pm25, pt_pm10]
        else:
            logger.warning("SPS30: Sin datos validos disponibles")
            return []
    except Exception as e:
        logger.exception("SPS30: %s", type(e).__name__)
        register_i2c_error()
        return []

# -------------------------------------------------------------------------
# Build the list of InfluxDB Points (one measurement batch)
# -------------------------------------------------------------------------
def build_points():
    global _sps30_stats_counter

    measurement_time = datetime.datetime.utcnow()

    points = []

    # NO2
    pt = read_no2_alpha(measurement_time)
    if pt: points.append(pt)
    pt = read_no2_mgsv2(measurement_time)
    if pt: points.append(pt)

    # Ozone (O3)
    pt = read_ozone_alpha(measurement_time)
    if pt: points.append(pt)
    pt = read_ozone_mq131(measurement_time)
    if pt: points.append(pt)

    # CO
    pt = read_co_alpha(measurement_time)
    if pt: points.append(pt)
    pt = read_co_mgsv2(measurement_time)
    if pt: points.append(pt)

    # SHT45 (temperature and humidity)
    pt_temp, pt_hum, temp, hum = read_sht45_temp_and_hum(measurement_time)
    if pt_temp: points.append(pt_temp)
    if pt_hum: points.append(pt_hum)

    # SGP40 (VOC Index)
    pt = read_sgp40(temp, hum, measurement_time)
    if pt: points.append(pt)

    # SPS30 (PM2.5 & PM10)
    sps30_points = read_sps30(measurement_time)
    if sps30_points:
        points.extend(sps30_points)

    # Print SPS30 statistics every N cycles
    if pm_sensor:
        _sps30_stats_counter += 1
        if _sps30_stats_counter >= _SPS30_STATS_INTERVAL:
            _sps30_stats_counter = 0
            stats = pm_sensor.get_stats()
            logger.info("SPS30 Stats: Total=%d, OK=%d, CRC_Err=%d, I2C_Err=%d, Rate=%.1f%%",
                        stats['total_reads'], stats['successful_reads'], 
                        stats['crc_errors'], stats['i2c_errors'],
                        stats['success_rate'])

    return points

# -------------------------------------------------------------------------
# -------------- SECTION: Local database (SQLite) -------------------------
# -------------------------------------------------------------------------
LOCAL_DB_PATH = os.path.join(script_dir, "local_data.db")

def init_local_db():
    """Create the local database (if it does not exist) and the 'measurements' table."""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    c = conn.cursor()
    
    c.execute("PRAGMA journal_mode=WAL;")
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            measurement TEXT,
            sensor_model TEXT,
            fields TEXT,
            tags TEXT,
            measurement_time_utc TEXT,
            synced INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def handle_db_corruption():
    """Handle the 'database disk image is malformed' error."""
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupt_path = f"{LOCAL_DB_PATH}.corrupted_{timestamp}"
        logger.exception(f"CORRUPCION DE BD DETECTADA! Renombrando a {corrupt_path}")
        
        if os.path.exists(LOCAL_DB_PATH):
            os.rename(LOCAL_DB_PATH, corrupt_path)
            logger.warning("Base de datos corrupta aislada. Se creara una nueva.")
    except Exception as e:
        logger.exception(f"No se pudo renombrar la BD corrupta: {e}")

def store_local(points):
    """Store each Point locally in the 'measurements' table."""
    if not points:
        return
        
    conn = sqlite3.connect(LOCAL_DB_PATH)
    c = conn.cursor()

    for pt in points:
        measurement = pt._name
        tags_dict = pt._tags
        sensor_model = tags_dict.get("SensorModel", "unknown")

        fields_dict = pt._fields
        measurement_dt = pt._time or datetime.datetime.utcnow()
        measurement_time_str = measurement_dt.isoformat() + 'Z'

        fields_json = json.dumps(fields_dict)
        tags_json = json.dumps(tags_dict)

        c.execute("""
            INSERT INTO measurements (
                measurement,
                sensor_model,
                fields,
                tags,
                measurement_time_utc,
                synced
            ) VALUES (?, ?, ?, ?, ?, 0)
        """, (measurement, sensor_model, fields_json, tags_json, measurement_time_str))

    conn.commit()
    conn.close()

def get_unsynced_data_chunk():
    """Return up to BATCH_SIZE rows where synced=0."""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, measurement, sensor_model, fields, tags, measurement_time_utc
        FROM measurements
        WHERE synced=0
        ORDER BY id ASC
        LIMIT ?
    """, (BATCH_SIZE,))
    rows = c.fetchall()
    conn.close()
    return rows

def mark_as_synced(ids):
    """Mark as synced the rows whose 'id' is in the ids list."""
    if not ids:
        return
    conn = sqlite3.connect(LOCAL_DB_PATH)
    c = conn.cursor()
    c.execute(f"""
        UPDATE measurements
        SET synced=1
        WHERE id IN ({",".join("?" for _ in ids)})
    """, ids)
    conn.commit()
    conn.close()

# -------------------------------------------------------------------------
# Check the DIRECT connection to the InfluxDB server
# -------------------------------------------------------------------------
def check_influx_server():
    """Try to open a socket to the InfluxDB server."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        target_ip = parsed.hostname or "localhost"
        target_port = parsed.port or 8086
        socket.create_connection((target_ip, target_port), timeout=7)
        return True
    except OSError:
        pass
    return False

# -------------------------------------------------------------------------
# Synchronise data to InfluxDB in chunks
# -------------------------------------------------------------------------
def sync_local_data_to_influx(write_api):
    """Synchronise rows with synced=0 in batches of BATCH_SIZE."""
    total_synced = 0

    while True:
        rows = get_unsynced_data_chunk()
        if not rows:
            break

        logger.info("Sincronizando lote de %d registros...", len(rows))

        influx_points = []
        row_ids = []

        for row in rows:
            row_id = row[0]
            measurement = row[1]
            sensor_model = row[2]
            fields_json = row[3]
            tags_json = row[4]
            measurement_time_str = row[5]

            fields_dict = json.loads(fields_json)
            tags_dict = json.loads(tags_json)

            try:
                if measurement_time_str.endswith('Z'):
                    measurement_time_str = measurement_time_str[:-1]
                measurement_dt = datetime.datetime.fromisoformat(measurement_time_str)
                measurement_dt = measurement_dt.replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                measurement_dt = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

            pt = Point(measurement)

            for k, v in tags_dict.items():
                pt.tag(k, v)

            pt.time(measurement_dt, WritePrecision.S)

            for f_k, f_v in fields_dict.items():
                if f_k in ("raw", "compensated_raw_gas", "index", "op1_raw", "op2_raw"):
                    pt.field(f_k, int(f_v))
                elif f_k in ("voltage", "celsius", "percentage", "micrograms_per_cubic_meter", "op1_voltage", "op2_voltage"):
                    pt.field(f_k, float(f_v))
                else:
                    pt.field(f_k, f_v)

            influx_points.append(pt)
            row_ids.append(row_id)

        try:
            write_api.write(bucket=bucket, org=org, record=influx_points)
            mark_as_synced(row_ids)
            logger.info("Lote de %d registros sincronizado correctamente.", len(rows))
            total_synced += len(rows)
        except Exception as e:
            logger.exception("Fallo al sincronizar lote: %s", e)
            break

    if total_synced > 0:
        logger.info("Sincronizacion finalizada. Registros sincronizados: %d.", total_synced)

# -------------------------------------------------------------------------
# Main loop
# -------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("="*60)
    logger.info("NODO 3 - Version 8.0 (Debian 13 trixie)")
    logger.info("="*60)

    # IMPORTANT: enable the watchdog BEFORE initialising sensors.
    # If initialisation hangs, systemd can then restart the service.
    if SYSTEMD_NOTIFY:
        systemd_notifier.notify("READY=1")
        logger.info("Watchdog de systemd activado (1 hora)")

    # Initialise the local database
    init_local_db()

    # Initialise sensors (protected by the watchdog)
    init_all_sensors()

    with InfluxDBClient(url=url, token=token, org=org, timeout=(15000, 60000), enable_gzip=True) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)

        try:
            while True:
                # Send the watchdog keep-alive signal to systemd
                if SYSTEMD_NOTIFY:
                    systemd_notifier.notify("WATCHDOG=1")

                try:
                    # Try to reconnect any sensors that failed
                    try_reconnect_sensors()

                    # Read sensors and build points
                    points = build_points()

                    # Store locally
                    store_local(points)

                    # Synchronise to InfluxDB if there is a connection
                    if check_influx_server():
                        sync_local_data_to_influx(write_api)
                    else:
                        logger.warning("Modo Offline: No se alcanza InfluxDB. Datos en local.")

                except sqlite3.DatabaseError as db_err:
                    logger.exception("Error CRITICO de Base de Datos: %s", db_err)
                    if "malformed" in str(db_err):
                        handle_db_corruption()
                        init_local_db()
                except Exception as e:
                    logger.exception("Error durante lectura/escritura/sincronizacion: %s", e)
                
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Interrupcion por teclado. Deteniendo mediciones...")
        finally:
            logger.info("Medicion finalizada.")
