# Windows DAQ Driver

Place the Vkinging Windows runtime files in this folder when they become available.
The controller automatically searches this folder and its subfolders for:

* `libvkdaq.dll` or `vkdaq.dll`
* `VkDaqAssistant.exe`
* any dependent DLLs supplied by the vendor

The UI and simulation mode do not require these files. For a nonstandard installation,
set the `VKDAQ_LIBRARY`, `VKDAQ_ASSISTANT`, or `VKDAQ_HOME` environment variable as
documented in the project README.
