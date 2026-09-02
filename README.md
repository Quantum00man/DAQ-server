# DAQ Server Project

This repository contains the software, drivers, and documentation needed to run a
VE3664N data-acquisition server. The main application (`daq_server.py`) provides a
local Tkinter control window while a FastAPI server continues to expose the latest
captured frame over HTTP.

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

## 🚀 How to Run the DAQ Controller

Once your hardware drivers are installed and your Python environment is ready, you can start the DAQ server.

1. Open a terminal and navigate to the project's root directory (where `daq_server.py` is located).
2. Run the controller from a terminal on Linux:

    python3 daq_server.py

   Or run it from PowerShell or Command Prompt on Windows:

    py daq_server.py

3. On Linux, the program runs `sudo /opt/vkdaq/bin/VkDaqAssistant`. Enter the sudo
   password in the terminal if requested. On Windows, it searches for and starts
   `VkDaqAssistant.exe` directly. The local control window then lets you:
   * enable any combination of AIN1 through AIN4;
   * select `dev1`, `dev2`, or enter another DAQ device name;
   * select an independent voltage range for every channel;
   * enter any sampling rate from 1 to 102400 Hz;
   * change the number of points acquired after each trigger;
   * choose DIN1.1 through DIN1.4 and a rising or falling trigger edge;
   * apply parameters and start or stop acquisition; and
   * use simulated data when the driver or hardware is unavailable.
4. The HTTP server remains available on port `8001`:
    * **Server Status:** `http://localhost:8001/`
    * **JSON Status:** `http://localhost:8001/status`
    * **Channel 1 Data Stream:** `http://localhost:8001/ch1.dat`
    * **Channel 2 Data Stream:** `http://localhost:8001/ch2.dat`
    * **Channel 3 Data Stream:** `http://localhost:8001/ch3.dat`
    * **Channel 4 Data Stream:** `http://localhost:8001/ch4.dat`

The `.dat` endpoints keep the original format: the first line is the Unix timestamp
and each following line is one sample from the latest frame. No `.dat` file is written
to disk. A disabled channel returns a timestamp followed by `0.0`.

For development without a DAQ or without starting DAQ Assistant, use:

    python3 daq_server.py --simulation --no-assistant

On Windows, use:

    py daq_server.py --simulation --no-assistant

For a headless HTTP-only process, add `--no-ui`.

### Windows driver discovery

The Windows UI and simulation mode work without the vendor driver. For real hardware,
the application searches for `libvkdaq.dll` or `vkdaq.dll` in:

* the path specified by `VKDAQ_LIBRARY`;
* `VKDAQ_HOME`, including its `lib` and `bin` subfolders;
* the system `PATH`;
* this project's `windows_driver` and `windows_installer` folders; and
* common Vkinging/VkDaq folders under Program Files and Local AppData.

It searches for `VkDaqAssistant.exe` in the same locations. Exact paths can be set in
PowerShell before launching the controller:

    $env:VKDAQ_LIBRARY = "C:\path\to\libvkdaq.dll"
    $env:VKDAQ_ASSISTANT = "C:\path\to\VkDaqAssistant.exe"
    py daq_server.py

Keep dependent vendor DLLs beside `libvkdaq.dll`; Python registers that directory for
Windows DLL dependency loading automatically.

The same paths can be selected from the UI's **Device Paths...** dialog:

* **libvkdaq.py / native driver** accepts a vendor `libvkdaq.py` wrapper or a native
  `libvkdaq.so`, `libvkdaq.dll`, or `vkdaq.dll` file. Stop acquisition before loading
  a different driver.
* **VkDaqAssistant executable** accepts `VkDaqAssistant` on Linux or
  `VkDaqAssistant.exe` on Windows. After setting the path, use **Launch DAQ Assistant**.

Use **Browse...** to select a file, or type/paste an absolute path into either field.

### Saved JSON settings

The controller saves all UI settings automatically when settings or paths are applied
and when the application closes. This includes the device name, sample rate, points per
trigger, trigger input and edge, simulation mode, every channel's enabled state and
input range, the driver/wrapper path, and the DAQ Assistant path.

The JSON file is stored at:

* Linux: `~/.config/DAQ-server/config.json`
* Windows: `%APPDATA%\DAQ-server\config.json`

Set `DAQ_SERVER_CONFIG` before starting the controller to use a different JSON path.
The saved configuration is validated and restored automatically at the next launch.

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
