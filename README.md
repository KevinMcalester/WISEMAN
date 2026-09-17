# WiSeMAN

## Wireless Sensor and Mobile Autonomous Networks

This repository serves as a shared software development and research continuity environment for **WiSeMAN students**.

The repository is centered around the **Ground Control System (GCS)** and the software developed for WiSeMAN's **QDrone, QCar, and QBot autonomous systems**.

## Repository Structure

    WISEMAN/
    │
    ├── Ground_Control/
    │   ├── gcs_src/
    │   ├── config/
    │   └── logs/
    │
    ├── QDrones/
    │   ├── Uav_Control/
    │   │   ├── uav_src/
    │   │   ├── config/
    │   │   ├── ca/
    │   │   ├── certs/
    │   │   └── keys/
    │   └── README.md
    │
    ├── QCars/
    │   ├── software/
    │   │   ├── src/
    │   │   └── config/
    │   └── README.md
    │
    ├── QBots/
    │   ├── software/
    │   │   ├── src/
    │   │   └── config/
    │   └── README.md
    │
    ├── Testing_Area/
    │
    ├── .gitignore
    └── README.md

## Ground Control System (GCS)

The `Ground_Control` directory contains software associated with the WiSeMAN Ground Control System.

The GCS provides the common software environment used to communicate with, monitor, control, and visualize supported WiSeMAN autonomous systems.

Its development may include communication, telemetry, visualization, system control, data processing, security, and coordination between Q systems.

## QDrones

The `QDrones` directory contains software developed for WiSeMAN QDrone systems.

`Uav_Control` contains the QDrone-side software used for communication with the Ground Control System and other QDrone functionality.

Refer to the WiSeMAN public documentation for information regarding QDrone architecture, hardware, operation, and research.

## QCars

The `QCars` directory contains software developed for WiSeMAN QCar autonomous vehicle systems.

Software associated with QCar communication, control, localization, perception, navigation, and integration with the GCS may be maintained within this directory.

Refer to the WiSeMAN public documentation for information regarding QCar architecture, hardware, operation, and research.

## QBots

The `QBots` directory contains software developed for WiSeMAN QBot autonomous mobile robot systems.

Software associated with QBot communication, control, localization, perception, navigation, and integration with the GCS may be maintained within this directory.

Refer to the WiSeMAN public documentation for information regarding QBot architecture, hardware, operation, and research.

## Testing Area

The `Testing_Area` directory contains experimental software, prototypes, hardware tests, and other code that has not yet been integrated into the primary WiSeMAN system directories.

Stable software should eventually be moved from the testing area into the appropriate Q system or Ground Control directory.

## Research Documentation

Research papers, reports, presentations, documentation, and other research materials are maintained separately in the shared WiSeMAN Google Drive.

WiSeMAN Research Drive:

https://drive.google.com/drive/folders/1vsXuX5AX9wRYF_PphS6HWOaG4aMnDjbv?usp=drive_link

The repository should primarily contain software, configurations, and other files necessary to develop and maintain the WiSeMAN systems.

For documentation regarding the Q systems, refer to their associated public documentation..
