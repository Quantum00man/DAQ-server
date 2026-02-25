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