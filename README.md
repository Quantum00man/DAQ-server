# DAQ Server Project

This repository contains the software, drivers, and documentation needed to set up and run a Data Acquisition (DAQ) server. The main application (`daq_server.py`) uses FastAPI to continuously read data from the DAQ hardware via a background worker thread and serves it over HTTP endpoints.

## 📁 Project Structure

* **`doc/`**: Contains all necessary instruction manuals and documentation.
    * `DAQ_card_setup_instruction.pdf`: A step-by-step guide on how to configure the DAQ hardware and install the drivers. **(Start here!)**
    * `Quick usage guide v1.3 En.pdf`: The hardware manufacturer's official quick start guide.
    * `VE3658,VE3668 Hardware manual.pdf`: The manufacturer's detailed hardware specifications manual.
* **`linux_installer/`**: Contains the DAQ Assistance (driver) installation packages for various Linux distributions. 
    * You will need to select the `.deb` package that exactly matches your Ubuntu version and architecture (e.g., Ubuntu 20.04, 22.04, 24.04, or ARM64).
* **`daq_server.py`**: The main FastAPI server application. It handles the hardware initialization, data collection, and web routing.
* **`libvkdaq.py`**: The core dependency library. This acts as a Python wrapper to interface with the underlying DAQ C-library.
* **`Testcodev0.py`**: A basic Python script used to test the DAQ functionality independently of the web server.

---

## ⚙️ Prerequisites & Setup

### 1. Hardware & Driver Installation
Before running any Python code, you must install the DAQ hardware drivers.
1. Navigate to the `linux_installer/` folder.
2. Choose the correct `.deb` package for your specific Ubuntu version.
3. For exact installation commands, please follow the instructions found in `doc/DAQ_card_setup_instruction.pdf`.

### 2. Python Environment Setup
Ensure you have Python 3 installed on your system. You will need to install a few external Python packages to run the web server. Open your terminal and run:

    pip install fastapi uvicorn numpy

*(Note: Modules like `ctypes`, `threading`, `sys`, and `time` are built into Python's standard library and do not require installation.)*

---

## 🚀 How to Run the DAQ Server

Once your hardware drivers are installed and your Python environment is ready, you can start the DAQ server.

1. Open a terminal and navigate to the project's root directory (where `daq_server.py` is located).
2. Run the server script:

    python3 daq_server.py

3. The terminal will display startup logs. If successful, it will indicate that the worker thread has started and the Uvicorn server is running on port `8001`.
4. You can now access the DAQ data by opening your web browser or using a tool like `curl`:
    * **Server Status:** `http://localhost:8001/`
    * **Channel 1 Data Stream:** `http://localhost:8001/ch1.dat`
    * **Channel 2 Data Stream:** `http://localhost:8001/ch2.dat`

### 🛠️ Troubleshooting & Testing

If the main server isn't working or the data streams are empty, you can isolate the issue by running the test script. This will verify if Python can communicate with the hardware without the web server involved:

    python3 Testcodev0.py

## 📊 VE3664N Noise Floor (uVrms)

The following table shows the **noise floor (RMS, µV)** of the VE3664N DAQ device under different **input ranges** and **sampling rates**.

| Input Range | 1.2 kS/s | 2.4 kS/s | 4.8 kS/s | 9.6 kS/s | 12.8 kS/s | 25.6 kS/s | 51.2 kS/s | 102.4 kS/s |
|------------|----------|----------|----------|----------|------------|------------|------------|-------------|
| ±10 V  | 120.6 µVrms | 181.6 µVrms | 244.0 µVrms | 478.2 µVrms | 490.7 µVrms | 856.6 µVrms | 1164.4 µVrms | 3548.6 µVrms |
| ±5 V   | 61.0 µVrms  | 93.6 µVrms  | 122.0 µVrms | 192.0 µVrms | 253.0 µVrms | 350.7 µVrms | 566.2 µVrms  | 1774.3 µVrms |
| ±2.5 V | 35.0 µVrms  | 46.6 µVrms  | 68.0 µVrms  | 98.1 µVrms  | 120.3 µVrms | 184.8 µVrms | 268.4 µVrms  | 887.8 µVrms  |
| ±1 V   | 16.0 µVrms  | 22.4 µVrms  | 32.9 µVrms  | 52.5 µVrms  | 66.0 µVrms  | 90.2 µVrms  | 134.9 µVrms  | 443.9 µVrms  |
| ±500 mV | 7.9 µVrms  | 11.9 µVrms  | 18.4 µVrms  | 29.1 µVrms  | 32.8 µVrms  | 50.5 µVrms  | 76.7 µVrms   | 221.9 µVrms  |
| ±100 mV | 3.5 µVrms  | 4.8 µVrms   | 7.1 µVrms   | 10.7 µVrms  | 13.4 µVrms  | 18.4 µVrms  | 30.0 µVrms   | 72.1 µVrms   |
| ±20 mV  | 2.8 µVrms  | 4.3 µVrms   | 5.8 µVrms   | 9.3 µVrms   | 10.0 µVrms  | 16.5 µVrms  | 23.7 µVrms   | 37.5 µVrms   |

### 💡 Notes
- Units: **µVrms (microvolts RMS)**
- Noise increases with **sampling rate**
- Lower input ranges generally provide **better noise performance**