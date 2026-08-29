# Wiring

All sensors connect to the Raspberry Pi Zero 2 W over I2C (3.3 V logic; the
SPS30, MGSv2, MQ131 and the Alphasense boards are powered from 5 V).

## SHT45 (temperature / humidity)

```
     SHT45             Raspberry Pi Zero W 2
     ---------------------------------------
     1 VIN ---------------- 3.3V - Pin 1
     2 GND ---------------- GND - Pin 6
     3 SCL ---------------- SCL - Pin 5
     4 SDA ---------------- SDA - Pin 3
```

## SGP40 (VOC index)

```
     SGP40             Raspberry Pi Zero W 2
     ---------------------------------------
     1 VIN ---------------- 3.3V - Pin 1
     2 GND ---------------- GND - Pin 6
     3 SCL ---------------- SCL - Pin 5
     4 SDA ---------------- SDA - Pin 3
```

## SPS30 (PM2.5 / PM10)

```
      SPS30                        Raspberry Pi Zero W 2
     --------------------------------------------------
     Pin 1 - VDD ---------------- 5V - Pin 2/4
     Pin 2 - SDA ---------------- SDA - Pin 3
     Pin 3 - SCL ---------------- SCL - Pin 5
     Pin 4 - SEL ----.----------- GND - Pin 6/9
     Pin 5 - GND ----'

        .---------------------------------------------------.
        |  SPS30 pinout after Dave (https://github.com/dvsu) |
        '---------------------------------------------------'
                                          Pin 1   Pin 5
                                           |       |
                                           V       V
        .------------------------------------------------.
        |                                .-----------.   |
        |                                | x x x x x |   |
        |                                '-----------'   |
        |     []          []          []          []     |
        '------------------------------------------------'
```

## Grove Multichannel Gas v2 (NO2 / CO, low-cost)

```
     Grove Multichannel Gas V2         Raspberry Pi Zero W 2
     -------------------------------------------------------
         1 GND -------------------------- GND - Pin 6/9
         2 VCC -------------------------- 5V - Pin 2/4
         3 SDA -------------------------- SDA - Pin 3
         4 SCL -------------------------- SCL - Pin 5
```

## MQ131 (O3, with FC-22 board) via ADS1115 #1 (0x48)

```
    Raspberry Pi Zero W 2              ADS1115_1         MQ131 (FC-22 board)
    ----------------------------------------------------------------------------
        SCL - Pin 5    ----------------- SCL
        SDA - Pin 3    ----------------- SDA
        5V - Pin 2/4   ----------------- VIN ----------------- VCC
        GND - Pin 6/9  ----------------- GND ----------------- GND
                                          A1 ----------------- A0
```

## Mid-cost Alphasense set (nodes 3 and 5 only)

NO2-B43F on ADS1115 #2 (0x49):

```
     Raspberry Pi Zero W 2              ADS1115_2      NO2-B43F (Alphasense, ISB)
     ----------------------------------------------------------------------------
         SCL - Pin 5    ----------------- SCL
         SDA - Pin 3    ----------------- SDA
         5V - Pin 2/4   ----------------- VIN ----------------- VCC
         GND - Pin 6/9  ----------------- GND ----------------- GND
                                           A0 ----------------- OP1
                                           A1 ----------------- OP2
```

OX-B431 (O3) and CO-B4 share ADS1115 #3 (0x4A), wired the same way
(OX-B431 on A0/A1, CO-B4 on A2/A3), each through its Alphasense ISB.

## I2C address map

| Device | Address |
|---|---|
| ADS1115 #1 (MQ131) | 0x48 |
| ADS1115 #2 (Alphasense NO2) | 0x49 |
| ADS1115 #3 (Alphasense O3 + CO) | 0x4A |
| SHT45 | 0x44 |
| SGP40 | 0x59 |
| MGSv2 | 0x08 |
| SPS30 | 0x69 |
