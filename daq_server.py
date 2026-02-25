import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, HTMLResponse
import ctypes
from ctypes import *
import numpy as np
import time
import sys
import threading
import random

# --- 1. Import DAQ Driver ---
# We try to import the proprietary C-library wrapper 'libvkdaq'
try:
    import libvkdaq
    print("[DAQ Server] Library imported.")
except Exception as e:
    print(f"[DAQ Server] Error: {e}")
    sys.exit(1)

app = FastAPI()

# --- 2. Global Shared Memory ---
# Because data acquisition happens in a background thread and FastAPI serves requests 
# in other threads, we use a dictionary and a Lock to safely share data between them.
SHARED_MEMORY = {
    "ch1": None,
    "ch2": None, # The original demo only used CH1, but we sample CH2 here to prevent frontend web errors.
    "timestamp": 0.0,
    "lock": threading.Lock() # Prevents data corruption when reading/writing at the same time
}

# Default DAQ hardware configuration (Clone of the original demo: 400 points, 3990Hz)
CONFIG = {
    ###CHANGE HERE### if you want to change the sample rate and namber
    "fsamp": 3990,      # Sampling frequency in Hz. 
    "Npoint": 390,      # Number of points to read per trigger
    "running": True,    # Controls the background worker loop
    "needs_reinit": True # Flag to tell the worker to re-apply settings
}

# --- 3. Core Logic (Minimalist Demo Clone) ---
def daq_worker_loop():
    """
    This function runs continuously in a background thread.
    It communicates with the DAQ hardware via ctypes and updates SHARED_MEMORY.
    """
    print("[Worker] Started (Concise Demo Clone).")
    
    # Use a random task name to prevent conflicts if the server restarts quickly
    task_name = f"VkDaqServer_{random.randint(1000,9999)}".encode('utf-8')
    task_p = c_char_p(task_name)
    task_created = False

    while CONFIG["running"]:
        try:
            # === Initialization Phase (Corresponds to the beginning of main() in the demo) ===
            if CONFIG["needs_reinit"]:
                # If a task already exists, stop and clear it before making a new one
                if task_created:
                    libvkdaq.VkDaqStopTask(task_p)
                    libvkdaq.VkDaqClearTask(task_p)
                
                Npoint = int(CONFIG["Npoint"])
                fsamp = int(CONFIG["fsamp"])
                
                # 1. Create Task in the DAQ API
                libvkdaq.VkDaqCreateTask(task_p)
                task_created = True
                
                # 2. Configure Channels 
                # The original demo only used AIN1, but we open two channels for server compatibility.
                # Arguments: Task, Channel Name, Terminal Config, Min Val, Max Val, Units, Custom Scale
                libvkdaq.VkDaqCreateAIVoltageChan(task_p, b"dev1/AIN1", b"", 0, -0.2, 0.2, 0, b"") ## CHANGE THE V limit "dev1 is your DAQ name which can be found and renamed in DAQ assistant. AIN1 is channel 1.
                libvkdaq.VkDaqCreateAIVoltageChan(task_p, b"dev1/AIN2", b"", 0, -0.2, 0.2, 0, b"") ## CHANGE THE V limit
                
                # 3. Configure Sample Clock Timing 
                # Arguments: Task, Source, Rate, ActiveEdge (1=Rising), SampleMode (1=Finite), SamplesPerChan
                libvkdaq.VkDaqCfgSampClkTiming(task_p, 0, float(fsamp), 1, 1, Npoint)
                
                # 4. Configure Digital Edge Reference Trigger
                libvkdaq.VkDaqCfgDigEdgeRefTrig(task_p, b"dev1/DIN1.1", 1, 0) 
                
                # 5. Start Task (Important: Start the task OUTSIDE the reading loop!)
                libvkdaq.VkDaqStartTask(task_p)
                print("[Worker] Task Started. Waiting for triggers...")
                
                # Reset the flag so we don't re-initialize on the next loop iteration
                CONFIG["needs_reinit"] = False

            # === Continuous Reading Phase (Corresponds to 'while True' in the demo) ===
            
            # Prepare a ctypes buffer array to hold the incoming C data (2 channels * Npoint)
            pts = int(CONFIG["Npoint"])
            data_buffer = (ctypes.c_double * (pts * 2))()
            
            # Read data from the DAQ 
            # Arguments: Task, Buffer, Points to read, FillMode (1=GroupByChannel), Timeout (1.0s)
            read = libvkdaq.VkDaqGetTaskData(task_p, data_buffer, pts, 1, 1.0)
            
            if read > 0:
                print(f"[Worker] Captured {read} pts.")
                
                # Parse data from the raw ctypes buffer to a manageable numpy array
                arr = np.ctypeslib.as_array(data_buffer)
                
                # Since FillMode is GroupByChannel (1), the first half of the array is CH1, 
                # and the second half is CH2. We use a Lock here so FastAPI doesn't read half-written data.
                with SHARED_MEMORY["lock"]:
                    SHARED_MEMORY["ch1"] = arr[0:pts].tolist()
                    SHARED_MEMORY["ch2"] = arr[pts:2*pts].tolist()
                    SHARED_MEMORY["timestamp"] = time.time()
                
                # [Crucial] Simulate the delay of np.savetxt() from the original demo. 
                # This slight delay gives the hardware a brief moment to breathe and 
                # prevents it from triggering multiple times too rapidly.
                time.sleep(0.05) 
                
        except Exception as e:
            print(f"[Worker Error] {e}")
            time.sleep(1) # Pause briefly to prevent console spamming on error
            CONFIG["needs_reinit"] = True # Force re-initialization on the next loop

    # Cleanup: Stop and clear the task gracefully when the server shuts down
    if task_created:
        libvkdaq.VkDaqStopTask(task_p)
        libvkdaq.VkDaqClearTask(task_p)

# --- 4. FastAPI Startup & Endpoints ---

@app.on_event("startup")
def startup_event():
    # Start the DAQ worker in a separate thread when the server starts.
    # daemon=True means this thread will automatically close when the main program closes.
    t = threading.Thread(target=daq_worker_loop, daemon=True)
    t.start()

@app.on_event("shutdown")
def shutdown_event():
    # Tell the worker loop to stop safely
    CONFIG["running"] = False

@app.post("/configure")
def configure(sample_rate: int = 3990, points: int = 400):
    """ Allows users to dynamically change the DAQ parameters via an API call. """
    CONFIG["fsamp"] = sample_rate
    CONFIG["Npoint"] = points
    CONFIG["needs_reinit"] = True
    return {"status": "ok", "message": "Re-initializing with new settings..."}

# Keep the API endpoints unchanged so the existing frontend works smoothly.
@app.get("/", response_class=HTMLResponse)
def index(): 
    return "<html><body><h1>DAQ Server (Demo Clone)</h1><p>Server is running.</p></body></html>"

@app.get("/ch1.dat", response_class=PlainTextResponse)
def get_ch1():
    """ Returns Channel 1 data in plain text format. """
    with SHARED_MEMORY["lock"]:
        if SHARED_MEMORY["ch1"] is None: 
            return f"{time.time()}\n0.0"
        
        # Format: First line is the timestamp, followed by data points separated by newlines
        return f"{SHARED_MEMORY['timestamp']}\n" + "\n".join([f"{v:.6f}" for v in SHARED_MEMORY["ch1"]])

@app.get("/ch2.dat", response_class=PlainTextResponse)
def get_ch2():
    """ Returns Channel 2 data in plain text format. """
    with SHARED_MEMORY["lock"]:
        if SHARED_MEMORY["ch2"] is None: 
            return f"{time.time()}\n0.0"
            
        return f"{SHARED_MEMORY['timestamp']}\n" + "\n".join([f"{v:.6f}" for v in SHARED_MEMORY["ch2"]])

if __name__ == "__main__":
    # Start the web server on all network interfaces (0.0.0.0) at port 8001
    uvicorn.run(app, host="0.0.0.0", port=8001)