"""Local UI and HTTP data server for the Vkinging VE3664N DAQ."""

from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import math
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

CHANNEL_NAMES = tuple(f"AIN{i}" for i in range(1, 5))
TRIGGER_SOURCES = tuple(f"DIN1.{i}" for i in range(1, 5))
INPUT_RANGES = {
    "±10 V": 10.0, "±5 V": 5.0, "±2.5 V": 2.5, "±1 V": 1.0,
    "±500 mV": 0.5, "±100 mV": 0.1, "±20 mV": 0.02,
}
MIN_SAMPLE_RATE = 1.0
MAX_SAMPLE_RATE = 102_400.0
MAX_POINTS = 2_000_000
MIN_HTTP_PORT = 1
MAX_HTTP_PORT = 65_535
PROJECT_DIR = Path(__file__).resolve().parent
DEVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def default_settings_path(
    platform_name: str | None = None,
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> Path:
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    explicit = environ.get("DAQ_SERVER_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    if platform_name.startswith("win"):
        base = Path(environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "DAQ-server" / "config.json"


def load_saved_settings(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        return {}, ""
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("the JSON root must be an object")
        return payload, ""
    except (OSError, ValueError) as exc:
        return {}, f"Unable to load settings from {path}: {exc}"


def local_address_for_display(bind_host: str) -> str:
    if bind_host not in {"0.0.0.0", "::"}:
        return bind_host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
            if address:
                return address
    except OSError:
        pass
    try:
        address = socket.gethostbyname(socket.gethostname())
        if address:
            return address
    except OSError:
        pass
    return "127.0.0.1"


def dat_endpoint_addresses(host: str, port: int) -> list[str]:
    display_host = local_address_for_display(host)
    url_host = f"[{display_host}]" if ":" in display_host else display_host
    return [f"http://{url_host}:{port}/ch{index}.dat" for index in range(1, 5)]


def _first_existing_file(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def find_vkdaq_library(
    platform_name: str | None = None,
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> Path | None:
    """Find the vendor shared library without loading it."""
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    is_windows = platform_name.startswith("win")
    names = ("libvkdaq.dll", "vkdaq.dll") if is_windows else ("libvkdaq.so",)
    candidates: list[Path] = []

    explicit = environ.get("VKDAQ_LIBRARY")
    if explicit:
        candidates.append(Path(explicit).expanduser())

    home = environ.get("VKDAQ_HOME")
    if home:
        home_path = Path(home).expanduser()
        candidates.extend(home_path / folder / name
                          for folder in ("", "lib", "bin") for name in names)

    for name in names:
        executable = shutil.which(name, path=environ.get("PATH"))
        if executable:
            candidates.append(Path(executable))

    if is_windows:
        roots = [PROJECT_DIR, PROJECT_DIR / "windows_driver",
                 PROJECT_DIR / "windows_installer"]
        roots.extend(Path(value) for key in ("PROGRAMFILES", "PROGRAMFILES(X86)",
                                              "LOCALAPPDATA")
                     if (value := environ.get(key)))
        vendor_folders = ("", "VKDAQ", "VkDaq", "Vkinging", "VK-DAQ")
        for root in roots:
            candidates.extend(root / vendor / folder / name
                              for vendor in vendor_folders
                              for folder in ("", "lib", "bin") for name in names)
        for search_root in (PROJECT_DIR / "windows_driver",
                            PROJECT_DIR / "windows_installer"):
            if search_root.is_dir():
                for name in names:
                    candidates.extend(search_root.rglob(name))
    else:
        candidates.extend(Path("/opt/vkdaq") / folder / name
                          for folder in ("lib", "bin") for name in names)

    return _first_existing_file(candidates)


def find_daq_assistant(
    platform_name: str | None = None,
    environ: dict[str, str] | os._Environ[str] | None = None,
) -> Path | None:
    """Find VkDaqAssistant on Windows or Linux."""
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    is_windows = platform_name.startswith("win")
    name = "VkDaqAssistant.exe" if is_windows else "VkDaqAssistant"
    candidates: list[Path] = []

    explicit = environ.get("VKDAQ_ASSISTANT")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    home = environ.get("VKDAQ_HOME")
    if home:
        home_path = Path(home).expanduser()
        candidates.extend(home_path / folder / name for folder in ("", "bin"))
    executable = shutil.which(name, path=environ.get("PATH"))
    if executable:
        candidates.append(Path(executable))

    if is_windows:
        roots = [PROJECT_DIR, PROJECT_DIR / "windows_driver",
                 PROJECT_DIR / "windows_installer"]
        roots.extend(Path(value) for key in ("PROGRAMFILES", "PROGRAMFILES(X86)",
                                              "LOCALAPPDATA")
                     if (value := environ.get(key)))
        for root in roots:
            candidates.extend(root / vendor / folder / name
                              for vendor in ("", "VKDAQ", "VkDaq", "Vkinging", "VK-DAQ")
                              for folder in ("", "bin"))
        for search_root in (PROJECT_DIR / "windows_driver",
                            PROJECT_DIR / "windows_installer"):
            if search_root.is_dir():
                candidates.extend(search_root.rglob(name))
    else:
        candidates.append(Path("/opt/vkdaq/bin/VkDaqAssistant"))

    return _first_existing_file(candidates)


@dataclass
class ChannelConfig:
    enabled: bool
    voltage_range: float = 0.5


@dataclass
class AcquisitionConfig:
    device_name: str = "dev1"
    sample_rate: float = 3990.0
    points: int = 390
    trigger_source: str = "DIN1.1"
    trigger_edge: str = "rising"
    simulation: bool = False
    channels: dict[str, ChannelConfig] = field(default_factory=lambda: {
        name: ChannelConfig(enabled=index < 2)
        for index, name in enumerate(CHANNEL_NAMES)
    })


class DAQController:
    """Owns DAQ state and serializes hardware access in one worker thread."""

    def __init__(
        self,
        force_simulation: bool = False,
        saved_settings: dict[str, Any] | None = None,
        settings_path: Path | None = None,
        settings_error: str = "",
    ) -> None:
        self.lock = threading.RLock()
        self.wake_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.settings_path = settings_path
        self.settings_error = settings_error
        self.config = self._config_from_settings(saved_settings or {})
        try:
            saved_port = int((saved_settings or {}).get("http_port", 8001))
            self.http_port = (
                saved_port if MIN_HTTP_PORT <= saved_port <= MAX_HTTP_PORT else 8001
            )
        except (TypeError, ValueError):
            self.http_port = 8001
        if force_simulation:
            self.config.simulation = True
        self.acquiring = False
        self.needs_reinit = True
        self.worker_thread: threading.Thread | None = None
        self.driver: Any | None = None
        self.driver_wrapper_path = PROJECT_DIR / "libvkdaq.py"
        self.driver_path = find_vkdaq_library()
        self.driver_selection_path: Path = (
            self.driver_path or self.driver_wrapper_path
        )
        self._dll_directory_handles: list[Any] = []
        self.driver_error = ""
        self.assistant_path = find_daq_assistant()
        self.assistant_process: subprocess.Popen[Any] | None = None
        self.assistant_status = "Not started"
        self.status = "Stopped"
        self.last_error = ""
        self.last_points = 0
        self.capture_count = 0
        self.timestamp = 0.0
        self.data: dict[str, list[float] | None] = {name: None for name in CHANNEL_NAMES}
        self._restore_saved_paths(saved_settings or {})
        self._load_driver()

    @staticmethod
    def _config_from_settings(settings: dict[str, Any]) -> AcquisitionConfig:
        config = AcquisitionConfig()
        device_name = str(settings.get("device_name", config.device_name)).strip()
        if DEVICE_NAME_PATTERN.fullmatch(device_name):
            config.device_name = device_name
        try:
            sample_rate = float(settings.get("sample_rate", config.sample_rate))
            if MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
                config.sample_rate = sample_rate
        except (TypeError, ValueError):
            pass
        try:
            points = int(settings.get("points", config.points))
            if 1 <= points <= MAX_POINTS:
                config.points = points
        except (TypeError, ValueError):
            pass
        trigger_source = settings.get("trigger_source")
        if trigger_source in TRIGGER_SOURCES:
            config.trigger_source = trigger_source
        trigger_edge = settings.get("trigger_edge")
        if trigger_edge in {"rising", "falling"}:
            config.trigger_edge = trigger_edge
        if isinstance(settings.get("simulation"), bool):
            config.simulation = settings["simulation"]

        saved_channels = settings.get("channels")
        if isinstance(saved_channels, dict):
            for name, channel in config.channels.items():
                saved_channel = saved_channels.get(name)
                if not isinstance(saved_channel, dict):
                    continue
                if isinstance(saved_channel.get("enabled"), bool):
                    channel.enabled = saved_channel["enabled"]
                try:
                    voltage_range = float(saved_channel.get("range"))
                    if voltage_range in INPUT_RANGES.values():
                        channel.voltage_range = voltage_range
                except (TypeError, ValueError):
                    pass
            if not any(channel.enabled for channel in config.channels.values()):
                config.channels["AIN1"].enabled = True
        return config

    def _restore_saved_paths(self, settings: dict[str, Any]) -> None:
        selected_driver = settings.get("driver_or_wrapper_path")
        if isinstance(selected_driver, str) and selected_driver.strip():
            path = Path(selected_driver).expanduser()
            if path.is_file():
                path = path.resolve()
                if path.suffix.lower() == ".py":
                    self.driver_wrapper_path = path
                    if path != (PROJECT_DIR / "libvkdaq.py").resolve():
                        self.driver_path = None
                    self.driver_selection_path = path
                elif path.suffix.lower() in {".dll", ".so", ".dylib"}:
                    self.driver_path = path
                    self.driver_selection_path = path
            else:
                self.settings_error = f"Saved driver path not found: {path}"
        selected_assistant = settings.get("assistant_path")
        if isinstance(selected_assistant, str) and selected_assistant.strip():
            path = Path(selected_assistant).expanduser()
            if path.is_file():
                self.assistant_path = path.resolve()
            elif not self.settings_error:
                self.settings_error = f"Saved DAQ Assistant path not found: {path}"

    @property
    def hardware_available(self) -> bool:
        return self.driver is not None

    @staticmethod
    def _validate_driver_module(module: Any) -> None:
        required = (
            "VkDaqCreateTask", "VkDaqClearTask", "VkDaqStartTask",
            "VkDaqStopTask", "VkDaqCreateAIVoltageChan",
            "VkDaqCfgSampClkTiming", "VkDaqCfgDigEdgeRefTrig",
            "VkDaqGetTaskData",
        )
        missing = [name for name in required if not hasattr(module, name)]
        if missing:
            raise ImportError(
                "Selected wrapper is missing required functions: "
                + ", ".join(missing)
            )

    def _import_driver_wrapper(self, wrapper_path: Path) -> Any:
        module_name = f"_vkdaq_wrapper_{id(self)}_{time.time_ns()}"
        spec = importlib.util.spec_from_file_location(module_name, wrapper_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to import wrapper: {wrapper_path}")
        module = importlib.util.module_from_spec(spec)
        wrapper_directory = str(wrapper_path.parent)
        sys.path.insert(0, wrapper_directory)
        try:
            spec.loader.exec_module(module)
        finally:
            if sys.path and sys.path[0] == wrapper_directory:
                sys.path.pop(0)
        self._validate_driver_module(module)
        return module

    def _load_driver(self) -> None:
        using_bundled_wrapper = (
            self.driver_wrapper_path.resolve() == (PROJECT_DIR / "libvkdaq.py").resolve()
        )
        if self.driver_path is None and using_bundled_wrapper:
            expected = "libvkdaq.dll or vkdaq.dll" if sys.platform.startswith("win") \
                else "libvkdaq.so"
            self.driver = None
            self.driver_error = (
                f"DAQ driver not found ({expected}). Set VKDAQ_LIBRARY or VKDAQ_HOME."
            )
            self.config.simulation = True
            return
        try:
            if self.driver_path is not None:
                os.environ["VKDAQ_LIBRARY"] = str(self.driver_path)
            self.driver = self._import_driver_wrapper(self.driver_wrapper_path)
            reported_path = getattr(self.driver, "VKDAQ_LIBRARY_PATH", None)
            if reported_path:
                self.driver_path = Path(reported_path).resolve()
            self.driver_error = ""
        except BaseException as exc:
            self.driver = None
            self.driver_error = str(exc)
            self.config.simulation = True

    def reload_driver(self, selected_path: str) -> Path:
        """Load a manually selected libvkdaq.py or native .so/.dll file."""
        with self.lock:
            if self.acquiring:
                raise ValueError("Stop acquisition before changing the DAQ driver")

        text = selected_path.strip()
        if text:
            path = Path(text).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f"Driver or wrapper file not found: {path}")
            if path.suffix.lower() == ".py":
                wrapper_path = path
                native_path = None
                if sys.platform.startswith("win") and hasattr(os, "add_dll_directory"):
                    self._dll_directory_handles.append(
                        os.add_dll_directory(str(path.parent))
                    )
            elif path.suffix.lower() in {".dll", ".so", ".dylib"}:
                wrapper_path = PROJECT_DIR / "libvkdaq.py"
                native_path = path
            else:
                raise ValueError(
                    "Select libvkdaq.py, libvkdaq.so, libvkdaq.dll, or vkdaq.dll"
                )
        else:
            wrapper_path = PROJECT_DIR / "libvkdaq.py"
            native_path = find_vkdaq_library()
            if native_path is None:
                raise ValueError(
                    "No DAQ library was found automatically. Select a wrapper or driver file."
                )
        selection_path = path if text else (native_path or wrapper_path)

        try:
            if native_path is not None:
                os.environ["VKDAQ_LIBRARY"] = str(native_path)
            module = self._import_driver_wrapper(wrapper_path)
        except BaseException as exc:
            with self.lock:
                self.driver = None
                self.driver_wrapper_path = wrapper_path
                self.driver_path = native_path
                self.driver_selection_path = selection_path
                self.driver_error = f"Failed to load DAQ driver: {exc}"
                self.config.simulation = True
            raise ValueError(self.driver_error) from exc

        reported_path = getattr(module, "VKDAQ_LIBRARY_PATH", None)
        with self.lock:
            self.driver = module
            self.driver_wrapper_path = wrapper_path
            self.driver_path = Path(reported_path).resolve() if reported_path else native_path
            self.driver_selection_path = selection_path
            self.driver_error = ""
            self.config.simulation = False
            self.needs_reinit = True
            self.status = "Driver loaded"
        self.save_settings()
        return self.driver_selection_path

    def set_assistant_path(self, selected_path: str) -> Path:
        """Set an Assistant executable selected in the UI, or re-run discovery."""
        text = selected_path.strip()
        path = Path(text).expanduser().resolve() if text else find_daq_assistant()
        if path is None or not path.is_file():
            raise ValueError(f"DAQ Assistant executable not found: {text or 'automatic search'}")
        with self.lock:
            self.assistant_path = path
            self.assistant_status = "Path set"
        self.save_settings()
        return path

    def _settings_payload(self) -> dict[str, Any]:
        with self.lock:
            return {
                "version": 1,
                "http_port": self.http_port,
                "device_name": self.config.device_name,
                "sample_rate": self.config.sample_rate,
                "points": self.config.points,
                "trigger_source": self.config.trigger_source,
                "trigger_edge": self.config.trigger_edge,
                "simulation": self.config.simulation,
                "channels": {
                    name: {
                        "enabled": channel.enabled,
                        "range": channel.voltage_range,
                    }
                    for name, channel in self.config.channels.items()
                },
                "driver_or_wrapper_path": str(self.driver_selection_path),
                "assistant_path": str(self.assistant_path) if self.assistant_path else "",
            }

    def save_settings(self) -> bool:
        if self.settings_path is None:
            return True
        payload = self._settings_payload()
        temporary_path = self.settings_path.with_name(self.settings_path.name + ".tmp")
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            os.replace(temporary_path, self.settings_path)
            self.settings_error = ""
            return True
        except OSError as exc:
            self.settings_error = f"Unable to save settings to {self.settings_path}: {exc}"
            return False

    def set_http_port(self, port: int) -> None:
        if not MIN_HTTP_PORT <= port <= MAX_HTTP_PORT:
            raise ValueError(
                f"HTTP port must be between {MIN_HTTP_PORT} and {MAX_HTTP_PORT}"
            )
        with self.lock:
            self.http_port = int(port)
        self.save_settings()

    def start_worker(self) -> None:
        with self.lock:
            if self.worker_thread and self.worker_thread.is_alive():
                return
            self.shutdown_event.clear()
            self.worker_thread = threading.Thread(
                target=self._worker_loop, name="daq-worker", daemon=True
            )
            self.worker_thread.start()

    def update_config(
        self, *, device_name: str, sample_rate: float, points: int, trigger_source: str,
        trigger_edge: str, simulation: bool, channels: dict[str, ChannelConfig],
    ) -> None:
        device_name = device_name.strip()
        if not DEVICE_NAME_PATTERN.fullmatch(device_name):
            raise ValueError(
                "Device name may contain only letters, numbers, dots, underscores, and hyphens"
            )
        if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
            raise ValueError(
                f"Sample rate must be between {MIN_SAMPLE_RATE:g} and "
                f"{MAX_SAMPLE_RATE:g} Hz"
            )
        if not 1 <= points <= MAX_POINTS:
            raise ValueError(f"Samples per trigger must be between 1 and {MAX_POINTS}")
        if trigger_source not in TRIGGER_SOURCES:
            raise ValueError("Invalid trigger input")
        if trigger_edge not in {"rising", "falling"}:
            raise ValueError("Invalid trigger edge")
        if not any(channel.enabled for channel in channels.values()):
            raise ValueError("At least one analog input channel must be enabled")
        if not simulation and not self.hardware_available:
            raise ValueError(
                f"DAQ driver unavailable: {self.driver_error or 'unknown error'}"
            )

        with self.lock:
            self.config = AcquisitionConfig(
                device_name=device_name,
                sample_rate=float(sample_rate), points=int(points),
                trigger_source=trigger_source, trigger_edge=trigger_edge,
                simulation=bool(simulation),
                channels={name: ChannelConfig(channels[name].enabled, channels[name].voltage_range)
                          for name in CHANNEL_NAMES},
            )
            self.needs_reinit = True
            for name, channel in self.config.channels.items():
                if not channel.enabled:
                    self.data[name] = None
            self.last_error = ""
        self.wake_event.set()
        self.save_settings()

    def start_acquisition(self) -> None:
        with self.lock:
            self.acquiring = True
            self.needs_reinit = True
            self.status = "Initializing"
            self.last_error = ""
        self.wake_event.set()

    def stop_acquisition(self) -> None:
        with self.lock:
            self.acquiring = False
            self.needs_reinit = True
            self.status = "Stopping"
        self.wake_event.set()

    def shutdown(self) -> None:
        self.save_settings()
        self.shutdown_event.set()
        self.stop_acquisition()
        thread = self.worker_thread
        if thread and thread.is_alive():
            thread.join(timeout=2.5)

    def launch_assistant(self) -> None:
        with self.lock:
            process = self.assistant_process
            if process and process.poll() is None:
                self.assistant_status = "Running"
                return
            self.assistant_path = self.assistant_path or find_daq_assistant()
            if self.assistant_path is None:
                self.assistant_status = (
                    "Not found. Set VKDAQ_ASSISTANT to the executable path."
                )
                return
            if sys.platform.startswith("win"):
                command = [str(self.assistant_path)]
                self.assistant_status = "Starting"
            else:
                command = ["sudo", str(self.assistant_path)]
                self.assistant_status = (
                    "Starting (enter the sudo password in the terminal if requested)"
                )
        try:
            process = subprocess.Popen(
                command, stdin=None, cwd=str(self.assistant_path.parent),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            with self.lock:
                self.assistant_process = process
                self.assistant_status = "Launch command sent"
        except Exception as exc:
            with self.lock:
                self.assistant_status = f"Launch failed: {exc}"

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            process = self.assistant_process
            assistant_status = self.assistant_status
            if process and process.poll() is not None:
                assistant_status = f"Exited (code {process.returncode})"
                self.assistant_status = assistant_status
            return {
                "status": self.status, "acquiring": self.acquiring,
                "settings_path": str(self.settings_path) if self.settings_path else None,
                "settings_error": self.settings_error,
                "http_port": self.http_port,
                "mode": "simulation" if self.config.simulation else "hardware",
                "hardware_available": self.hardware_available,
                "driver_path": str(self.driver_path) if self.driver_path else None,
                "driver_wrapper_path": str(self.driver_wrapper_path),
                "driver_error": self.driver_error,
                "assistant_path": (
                    str(self.assistant_path) if self.assistant_path else None
                ),
                "assistant_status": assistant_status,
                "device_name": self.config.device_name,
                "sample_rate": self.config.sample_rate,
                "points_requested": self.config.points,
                "points_read": self.last_points,
                "capture_count": self.capture_count,
                "timestamp": self.timestamp,
                "trigger_source": self.config.trigger_source,
                "trigger_edge": self.config.trigger_edge,
                "channels": {name: {"enabled": channel.enabled, "range": channel.voltage_range}
                             for name, channel in self.config.channels.items()},
                "last_error": self.last_error,
            }

    def channel_text(self, name: str) -> str:
        with self.lock:
            values = self.data[name]
            timestamp = self.timestamp or time.time()
            if values is None:
                return f"{timestamp}\n0.0"
            return f"{timestamp}\n" + "\n".join(f"{value:.6f}" for value in values)

    def _config_snapshot(self) -> AcquisitionConfig:
        with self.lock:
            return AcquisitionConfig(
                device_name=self.config.device_name,
                sample_rate=self.config.sample_rate, points=self.config.points,
                trigger_source=self.config.trigger_source,
                trigger_edge=self.config.trigger_edge,
                simulation=self.config.simulation,
                channels={name: ChannelConfig(channel.enabled, channel.voltage_range)
                          for name, channel in self.config.channels.items()},
            )

    def _worker_loop(self) -> None:
        task_name = f"VkDaqServer_{random.randint(1000, 9999)}".encode("utf-8")
        task_pointer = ctypes.c_char_p(task_name)
        task_created = False
        while not self.shutdown_event.is_set():
            with self.lock:
                acquiring = self.acquiring
            if not acquiring:
                if task_created:
                    self._clear_task(task_pointer)
                    task_created = False
                with self.lock:
                    self.status = "Stopped"
                self.wake_event.wait(0.2)
                self.wake_event.clear()
                continue

            config = self._config_snapshot()
            try:
                if config.simulation:
                    if task_created:
                        self._clear_task(task_pointer)
                        task_created = False
                    with self.lock:
                        self.needs_reinit = False
                        self.status = "Simulated acquisition running"
                    self._simulate_capture(config)
                    continue
                if self.driver is None:
                    raise RuntimeError(self.driver_error or "DAQ driver unavailable")

                with self.lock:
                    needs_reinit = self.needs_reinit
                if needs_reinit:
                    if task_created:
                        self._clear_task(task_pointer)
                        task_created = False
                    self._configure_hardware(task_pointer, config)
                    task_created = True
                    with self.lock:
                        self.needs_reinit = False
                        self.status = "Waiting for trigger"

                enabled_names = [name for name, channel in config.channels.items() if channel.enabled]
                buffer = (ctypes.c_double * (config.points * len(enabled_names)))()
                read = self.driver.VkDaqGetTaskData(task_pointer, buffer, config.points, 1, 1.0)
                if read > 0:
                    array = np.ctypeslib.as_array(buffer)
                    captured = min(int(read), config.points)
                    channel_data = {
                        name: array[index * config.points:index * config.points + captured].tolist()
                        for index, name in enumerate(enabled_names)
                    }
                    self._publish_capture(channel_data, captured, "Waiting for trigger")
                    time.sleep(0.05)
            except Exception as exc:
                if task_created:
                    self._clear_task(task_pointer)
                    task_created = False
                with self.lock:
                    self.last_error = str(exc)
                    self.status = "Acquisition error"
                    self.needs_reinit = True
                self.wake_event.wait(1.0)
                self.wake_event.clear()
        if task_created:
            self._clear_task(task_pointer)

    def _configure_hardware(self, task_pointer: ctypes.c_char_p, config: AcquisitionConfig) -> None:
        assert self.driver is not None
        self._check_result(self.driver.VkDaqCreateTask(task_pointer), "Create DAQ task")
        try:
            for name, channel in config.channels.items():
                if not channel.enabled:
                    continue
                result = self.driver.VkDaqCreateAIVoltageChan(
                    task_pointer,
                    ctypes.c_char_p(f"{config.device_name}/{name}".encode()),
                    ctypes.c_char_p(b""),
                    0, -channel.voltage_range, channel.voltage_range, 0, ctypes.c_char_p(b""),
                )
                self._check_result(result, f"Configure {name}")
            result = self.driver.VkDaqCfgSampClkTiming(
                task_pointer, 0, config.sample_rate, 1, 1, config.points
            )
            self._check_result(result, "Configure sample clock")
            edge = 1 if config.trigger_edge == "rising" else 0
            result = self.driver.VkDaqCfgDigEdgeRefTrig(
                task_pointer,
                ctypes.c_char_p(
                    f"{config.device_name}/{config.trigger_source}".encode()
                ),
                edge,
                0,
            )
            self._check_result(result, "Configure digital trigger")
            self._check_result(self.driver.VkDaqStartTask(task_pointer), "Start DAQ task")
        except Exception:
            self._clear_task(task_pointer)
            raise

    @staticmethod
    def _check_result(result: Any, action: str) -> None:
        if isinstance(result, int) and result < 0:
            raise RuntimeError(f"{action} failed; driver returned {result}")

    def _clear_task(self, task_pointer: ctypes.c_char_p) -> None:
        if self.driver is None:
            return
        try:
            self.driver.VkDaqStopTask(task_pointer)
        except Exception:
            pass
        try:
            self.driver.VkDaqClearTask(task_pointer)
        except Exception:
            pass

    def _simulate_capture(self, config: AcquisitionConfig) -> None:
        enabled_names = [name for name, channel in config.channels.items() if channel.enabled]
        t = np.arange(config.points, dtype=float) / config.sample_rate
        capture_number = self.capture_count + 1
        channel_data: dict[str, list[float]] = {}
        for index, name in enumerate(enabled_names):
            amplitude = config.channels[name].voltage_range * 0.2
            frequency = 25.0 * (index + 1)
            rng = np.random.default_rng(capture_number * 10 + index)
            signal = amplitude * np.sin(2.0 * math.pi * frequency * t)
            noise = rng.normal(0.0, max(amplitude * 0.01, 1e-7), config.points)
            channel_data[name] = (signal + noise).tolist()
        self._publish_capture(
            channel_data, config.points, "Simulated acquisition running"
        )
        delay = min(max(config.points / config.sample_rate, 0.1), 1.0)
        self.wake_event.wait(delay)
        self.wake_event.clear()

    def _publish_capture(self, channel_data: dict[str, list[float]], points: int, next_status: str) -> None:
        with self.lock:
            for name in CHANNEL_NAMES:
                if name in channel_data:
                    self.data[name] = channel_data[name]
            self.timestamp = time.time()
            self.last_points = points
            self.capture_count += 1
            self.status = next_status
            self.last_error = ""


SETTINGS_PATH = default_settings_path()
SAVED_SETTINGS, SETTINGS_LOAD_ERROR = load_saved_settings(SETTINGS_PATH)
controller = DAQController(
    saved_settings=SAVED_SETTINGS,
    settings_path=SETTINGS_PATH,
    settings_error=SETTINGS_LOAD_ERROR,
)
app = FastAPI(title="VE3664N DAQ Server")


@app.on_event("startup")
def startup_event() -> None:
    controller.start_worker()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    status = controller.snapshot()
    return ("<html><body><h1>VE3664N DAQ Server</h1>"
            f"<p>Status: {status['status']}</p>"
            f"<p>Last capture: {status['points_read']} points</p>"
            "<p>Use the local control window to configure acquisition.</p></body></html>")


@app.get("/status")
def get_status() -> dict[str, Any]:
    return controller.snapshot()


@app.post("/configure")
def configure(sample_rate: float = 3990, points: int = 400) -> dict[str, str]:
    """Backward-compatible API for updating sample rate and point count."""
    current = controller._config_snapshot()
    try:
        controller.update_config(
            device_name=current.device_name,
            sample_rate=sample_rate, points=points,
            trigger_source=current.trigger_source, trigger_edge=current.trigger_edge,
            simulation=current.simulation, channels=current.channels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "message": "Configuration updated"}


def _channel_response(name: str) -> PlainTextResponse:
    return PlainTextResponse(controller.channel_text(name))


@app.get("/ch1.dat", response_class=PlainTextResponse)
def get_ch1() -> PlainTextResponse:
    return _channel_response("AIN1")


@app.get("/ch2.dat", response_class=PlainTextResponse)
def get_ch2() -> PlainTextResponse:
    return _channel_response("AIN2")


@app.get("/ch3.dat", response_class=PlainTextResponse)
def get_ch3() -> PlainTextResponse:
    return _channel_response("AIN3")


@app.get("/ch4.dat", response_class=PlainTextResponse)
def get_ch4() -> PlainTextResponse:
    return _channel_response("AIN4")


class HTTPServerManager:
    """Start and restart Uvicorn when the user changes the HTTP port."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()

    def _port_available(self, port: int) -> bool:
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        bind_host = self.host
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((bind_host, port))
            return True
        except OSError:
            return False

    def start(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            config = uvicorn.Config(
                app, host=self.host, port=self.port, log_level="info"
            )
            self.server = uvicorn.Server(config)
            self.thread = threading.Thread(
                target=self.server.run, name="http-server", daemon=True
            )
            self.thread.start()
            server = self.server
            thread = self.thread

        deadline = time.time() + 4.0
        while thread.is_alive() and not server.started and time.time() < deadline:
            time.sleep(0.05)
        if not server.started:
            server.should_exit = True
            thread.join(timeout=1.0)
            raise RuntimeError(
                f"Unable to start HTTP server on {self.host}:{self.port}"
            )

    def stop(self) -> None:
        with self.lock:
            server = self.server
            thread = self.thread
        if server is not None:
            server.should_exit = True
        if thread and thread.is_alive():
            thread.join(timeout=4.0)
        with self.lock:
            self.server = None
            self.thread = None

    def restart(self, port: int) -> None:
        if not MIN_HTTP_PORT <= port <= MAX_HTTP_PORT:
            raise ValueError(
                f"HTTP port must be between {MIN_HTTP_PORT} and {MAX_HTTP_PORT}"
            )
        if port == self.port:
            return
        if not self._port_available(port):
            raise ValueError(f"HTTP port {port} is already in use")

        previous_port = self.port
        self.stop()
        self.port = port
        try:
            self.start()
        except Exception as exc:
            self.port = previous_port
            try:
                self.start()
            except Exception:
                pass
            raise ValueError(str(exc)) from exc


class DAQControlWindow:
    def __init__(
        self, daq_controller: DAQController, server_manager: HTTPServerManager
    ) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        self.tk, self.ttk = tk, ttk
        self.filedialog, self.messagebox = filedialog, messagebox
        self.controller, self.server_manager = daq_controller, server_manager
        self.root = tk.Tk()
        self.root.title("VE3664N DAQ Controller")
        self.root.geometry("900x700")
        self.root.minsize(800, 650)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        config = self.controller._config_snapshot()
        self.sample_rate_var = tk.StringVar(value=f"{config.sample_rate:g}")
        self.points_var = tk.StringVar(value=str(config.points))
        self.device_var = tk.StringVar(value=config.device_name)
        self.port_var = tk.StringVar(value=str(self.server_manager.port))
        self.trigger_var = tk.StringVar(value=config.trigger_source)
        self.edge_var = tk.StringVar(value=config.trigger_edge)
        self.simulation_var = tk.BooleanVar(value=config.simulation)
        initial_driver_path = (
            self.controller.driver_path or self.controller.driver_wrapper_path
        )
        self.driver_path_var = tk.StringVar(value=str(initial_driver_path))
        self.assistant_path_var = tk.StringVar(
            value=str(self.controller.assistant_path or "")
        )
        self.channel_enabled_vars: dict[str, Any] = {}
        self.channel_range_vars: dict[str, Any] = {}
        self.status_var = tk.StringVar(value="Starting")
        self.assistant_var = tk.StringVar(value="Starting")
        self.mode_var = tk.StringVar(value="")
        self.points_read_var = tk.StringVar(value="0")
        self.endpoint_var = tk.StringVar(value=self._endpoint_text())
        self.error_var = tk.StringVar(value="")
        self._build_ui(config)
        self.root.after(200, self._refresh_status)

    def _build_ui(self, config: AcquisitionConfig) -> None:
        ttk = self.ttk
        root_frame = ttk.Frame(self.root, padding=16)
        root_frame.pack(fill="both", expand=True)
        root_frame.columnconfigure(0, weight=1)
        ttk.Label(root_frame, text="VE3664N DAQ Controller", font=("Sans", 18, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        status_frame = ttk.LabelFrame(root_frame, text="System Status", padding=10)
        status_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        status_frame.columnconfigure(1, weight=1)
        self._status_row(status_frame, 0, "DAQ:", self.status_var)
        self._status_row(status_frame, 1, "Mode:", self.mode_var)
        self._status_row(status_frame, 2, "DAQ Assistant:", self.assistant_var)
        self._status_row(status_frame, 3, "Last sample count:", self.points_read_var)
        self._status_row(
            status_frame, 4, "DAT addresses:", self.endpoint_var, wraplength=700
        )

        settings = ttk.LabelFrame(root_frame, text="Acquisition Settings", padding=10)
        settings.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        ttk.Label(settings, text="Sample rate (Hz, 1-102400)").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(settings, textvariable=self.sample_rate_var).grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=5)
        ttk.Label(settings, text="Device").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=5)
        ttk.Combobox(settings, textvariable=self.device_var,
                     values=("dev1", "dev2"), state="normal").grid(
            row=0, column=3, sticky="ew", pady=5
        )
        ttk.Label(settings, text="Samples per trigger").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        ttk.Entry(settings, textvariable=self.points_var).grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=5)
        ttk.Label(settings, text="Trigger input").grid(row=1, column=2, sticky="w", padx=(0, 8), pady=5)
        ttk.Combobox(settings, textvariable=self.trigger_var, values=TRIGGER_SOURCES, state="readonly").grid(row=1, column=3, sticky="ew", pady=5)
        ttk.Label(settings, text="Trigger edge").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=5)
        edge_frame = ttk.Frame(settings)
        edge_frame.grid(row=2, column=1, sticky="w", pady=5)
        ttk.Radiobutton(edge_frame, text="Rising", variable=self.edge_var, value="rising").pack(side="left")
        ttk.Radiobutton(edge_frame, text="Falling", variable=self.edge_var, value="falling").pack(side="left", padx=(12, 0))
        ttk.Checkbutton(edge_frame, text="Simulation mode",
                        variable=self.simulation_var).pack(side="left", padx=(24, 0))
        ttk.Label(settings, text="HTTP port").grid(
            row=2, column=2, sticky="w", padx=(0, 8), pady=5
        )
        ttk.Entry(settings, textvariable=self.port_var).grid(
            row=2, column=3, sticky="ew", pady=5
        )

        channels_frame = ttk.LabelFrame(root_frame, text="Analog Input Channels", padding=10)
        channels_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        channels_frame.columnconfigure(2, weight=1)
        ttk.Label(channels_frame, text="Channel").grid(row=0, column=0, sticky="w", padx=(0, 20))
        ttk.Label(channels_frame, text="Enabled").grid(row=0, column=1, sticky="w", padx=(0, 20))
        ttk.Label(channels_frame, text="Input range").grid(row=0, column=2, sticky="w")
        for row, name in enumerate(CHANNEL_NAMES, start=1):
            enabled_var = self.tk.BooleanVar(value=config.channels[name].enabled)
            range_label = next(label for label, value in INPUT_RANGES.items()
                               if value == config.channels[name].voltage_range)
            range_var = self.tk.StringVar(value=range_label)
            self.channel_enabled_vars[name] = enabled_var
            self.channel_range_vars[name] = range_var
            ttk.Label(channels_frame, text=name).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Checkbutton(channels_frame, variable=enabled_var).grid(row=row, column=1, sticky="w", pady=4)
            ttk.Combobox(channels_frame, textvariable=range_var, values=list(INPUT_RANGES),
                         state="readonly", width=18).grid(row=row, column=2, sticky="w", pady=4)

        button_frame = ttk.Frame(root_frame)
        button_frame.grid(row=4, column=0, sticky="ew", pady=(2, 8))
        ttk.Button(button_frame, text="Apply Settings", command=self.apply_config).pack(side="left")
        ttk.Button(button_frame, text="Start Acquisition", command=self.start).pack(side="left", padx=(8, 0))
        ttk.Button(button_frame, text="Stop Acquisition", command=self.stop).pack(side="left", padx=(8, 0))
        ttk.Button(button_frame, text="Launch DAQ Assistant",
                   command=self.controller.launch_assistant).pack(side="right")
        ttk.Button(button_frame, text="Device Paths...",
                   command=self.open_paths_dialog).pack(side="right", padx=(0, 8))
        ttk.Label(root_frame, textvariable=self.error_var, foreground="#b00020",
                  wraplength=700).grid(row=5, column=0, sticky="ew")

    def _status_row(
        self, frame: Any, row: int, label: str, variable: Any,
        wraplength: int = 0,
    ) -> None:
        self.ttk.Label(frame, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=2)
        self.ttk.Label(
            frame, textvariable=variable, wraplength=wraplength,
            justify="left",
        ).grid(row=row, column=1, sticky="nw", pady=2)

    def _endpoint_text(self) -> str:
        return "  |  ".join(
            dat_endpoint_addresses(self.server_manager.host, self.server_manager.port)
        )

    def open_paths_dialog(self) -> None:
        existing = getattr(self, "paths_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        dialog = self.tk.Toplevel(self.root)
        self.paths_dialog = dialog
        dialog.title("Device Paths")
        dialog.geometry("780x150")
        dialog.minsize(680, 140)
        dialog.transient(self.root)
        frame = self.ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        self.ttk.Label(frame, text="libvkdaq.py / native driver").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=6
        )
        self.ttk.Entry(frame, textvariable=self.driver_path_var).grid(
            row=0, column=1, sticky="ew", pady=6
        )
        self.ttk.Button(frame, text="Browse...", command=self.browse_driver).grid(
            row=0, column=2, padx=(8, 0), pady=6
        )
        self.ttk.Button(frame, text="Load Driver", command=self.load_driver).grid(
            row=0, column=3, padx=(8, 0), pady=6
        )
        self.ttk.Label(frame, text="VkDaqAssistant executable").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=6
        )
        self.ttk.Entry(frame, textvariable=self.assistant_path_var).grid(
            row=1, column=1, sticky="ew", pady=6
        )
        self.ttk.Button(frame, text="Browse...", command=self.browse_assistant).grid(
            row=1, column=2, padx=(8, 0), pady=6
        )
        self.ttk.Button(frame, text="Set Path", command=self.set_assistant_path).grid(
            row=1, column=3, padx=(8, 0), pady=6
        )

    def browse_driver(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Select libvkdaq wrapper or native driver",
            filetypes=(
                ("Vkinging DAQ files", "libvkdaq.py libvkdaq.so libvkdaq.dll vkdaq.dll"),
                ("Python files", "*.py"),
                ("Shared libraries", "*.so *.dll *.dylib"),
                ("All files", "*"),
            ),
        )
        if path:
            self.driver_path_var.set(path)

    def browse_assistant(self) -> None:
        path = self.filedialog.askopenfilename(
            title="Select VkDaqAssistant executable",
            filetypes=(("VkDaqAssistant", "VkDaqAssistant VkDaqAssistant.exe"),
                       ("All files", "*")),
        )
        if path:
            self.assistant_path_var.set(path)

    def load_driver(self) -> None:
        try:
            loaded_path = self.controller.reload_driver(self.driver_path_var.get())
            self.driver_path_var.set(str(loaded_path))
            self.simulation_var.set(False)
            self.error_var.set("")
            self.status_var.set("Driver loaded")
        except ValueError as exc:
            self.simulation_var.set(True)
            self.error_var.set(str(exc))
            self.messagebox.showerror("Driver Load Error", str(exc))

    def set_assistant_path(self) -> None:
        try:
            path = self.controller.set_assistant_path(self.assistant_path_var.get())
            self.assistant_path_var.set(str(path))
            self.assistant_var.set("Path set")
            self.error_var.set("")
        except ValueError as exc:
            self.error_var.set(str(exc))
            self.messagebox.showerror("Assistant Path Error", str(exc))

    def apply_config(self, show_confirmation: bool = True) -> bool:
        try:
            port = int(self.port_var.get())
            if not MIN_HTTP_PORT <= port <= MAX_HTTP_PORT:
                raise ValueError(
                    f"HTTP port must be between {MIN_HTTP_PORT} and {MAX_HTTP_PORT}"
                )
            channels = {name: ChannelConfig(
                enabled=bool(self.channel_enabled_vars[name].get()),
                voltage_range=INPUT_RANGES[self.channel_range_vars[name].get()])
                for name in CHANNEL_NAMES}
            self.controller.update_config(
                device_name=self.device_var.get(),
                sample_rate=float(self.sample_rate_var.get()), points=int(self.points_var.get()),
                trigger_source=self.trigger_var.get(), trigger_edge=self.edge_var.get(),
                simulation=bool(self.simulation_var.get()), channels=channels,
            )
            if port != self.server_manager.port:
                self.server_manager.restart(port)
            self.controller.set_http_port(port)
            self.endpoint_var.set(self._endpoint_text())
            self.error_var.set("")
            if show_confirmation:
                self.status_var.set("Settings applied")
            return True
        except (ValueError, KeyError) as exc:
            self.error_var.set(str(exc))
            self.messagebox.showerror("Invalid Settings", str(exc))
            return False

    def start(self) -> None:
        if self.apply_config(show_confirmation=False):
            self.controller.start_acquisition()

    def stop(self) -> None:
        self.controller.stop_acquisition()

    def _refresh_status(self) -> None:
        snapshot = self.controller.snapshot()
        self.status_var.set(snapshot["status"])
        self.mode_var.set(
            "Simulation" if snapshot["mode"] == "simulation" else "Hardware DAQ"
        )
        self.assistant_var.set(snapshot["assistant_status"])
        self.points_read_var.set(str(snapshot["points_read"]))
        self.endpoint_var.set(self._endpoint_text())
        error_messages = [snapshot["last_error"]]
        if not snapshot["hardware_available"]:
            error_messages.append(snapshot["driver_error"])
        error_messages.append(snapshot["settings_error"])
        self.error_var.set(" | ".join(message for message in error_messages if message))
        self.root.after(250, self._refresh_status)

    def close(self) -> None:
        self.server_manager.stop()
        self.controller.shutdown()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VE3664N DAQ control server")
    parser.add_argument("--simulation", action="store_true", help="force simulation mode")
    parser.add_argument("--no-ui", action="store_true", help="run only the HTTP server")
    parser.add_argument("--no-assistant", action="store_true", help="do not launch DAQ Assistant")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None,
                        help="override the saved HTTP port")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.simulation:
        with controller.lock:
            controller.config.simulation = True
    port = args.port if args.port is not None else controller.http_port
    if not MIN_HTTP_PORT <= port <= MAX_HTTP_PORT:
        raise ValueError(f"HTTP port must be between {MIN_HTTP_PORT} and {MAX_HTTP_PORT}")
    controller.set_http_port(port)
    if not args.no_assistant:
        controller.launch_assistant()
    if args.no_ui:
        try:
            uvicorn.run(app, host=args.host, port=port)
        finally:
            controller.shutdown()
        return

    server_manager = HTTPServerManager(args.host, port)
    server_manager.start()
    try:
        DAQControlWindow(controller, server_manager).run()
    except Exception as exc:
        server_manager.stop()
        controller.shutdown()
        print(f"Unable to start local UI: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
