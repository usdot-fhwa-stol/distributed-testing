# Trajectory Files

This document describes the structure and variables contained within the trajectory configuration/log files.

---

## 1. Trajectory (`[trajectory]`)

General metadata and timing information regarding the recorded trajectory and GPS receiver state.

* **`trajectory_id`**: Unique identifier for the recorded trajectory.
* **`data_rate_hz`**: Logging frequency of the trajectory data in Hertz (Hz).
* **`fix_quality`**: GPS Fix Quality Indicator (e.g., Invalid, GPS Fix, or DGPS Fix).
* **`gps_mode`**: Operating mode of the GPS receiver (e.g., Fix not available, 2D Fix, or 3D Fix).
* **`satellites_in_view`**: Total number of satellites visible to the receiver.
* **`gps_time_of_week_ms`**: Time elapsed since the start of the current GPS week, measured in milliseconds.
* **`utcDay`**: Day of the month in UTC time (1–31).
* **`utcMonth`**: Month of the year in UTC time (1–12).
* **`utdYear`**: Year in UTC time.

---

## 2. Dilution of Precision (`[dop]`)

Metrics measuring the multiplicative effect of satellite geometry on positional measurement precision. Lower values indicate better accuracy.

* **`pdop`**: **Position Dilution of Precision:** Overall 3D spatial positioning accuracy.
* **`hdop`**: **Horizontal Dilution of Precision:** Horizontal 2D positioning accuracy.
* **`vdop`**: **Vertical Dilution of Precision:** Elevation/vertical positioning accuracy.

---

## 3. Satellites (`[satellites]`)

Detailed telemetry for visible satellites.

* **`satellites_json`**: A JSON string containing an array of tracked satellite objects. Each object includes:
* **`satellite_id`**: Unique PRN identifier for the satellite.
* **`elevation_degree`**: Angle of the satellite above the horizon in degrees (0° to 90°).
* **`azimuth_degree`**: Compass direction of the satellite in degrees relative to true north (0° to 359°).
* **`snr`**: Signal-to-Noise Ratio (C/N0) in dB-Hz, indicating signal strength.