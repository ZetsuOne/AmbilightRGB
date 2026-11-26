"""Screen-synced ambient color for every OpenRGB device."""

from __future__ import annotations

import atexit
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

import mss
import numpy as np
from openrgb import OpenRGBClient
from openrgb.utils import DeviceType, OpenRGBDisconnected, RGBColor

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - tray is optional at runtime
    pystray = None
    Image = None
    ImageDraw = None

__version__ = "1.1.0"

FPS_LIMIT = (1.0, 30.0)
SMOOTH_LIMIT = (0.05, 1.0)
BRIGHTNESS_LIMIT = (0.0, 1.0)
HUE_BIN_LIMIT = (6, 48)
LUMA_MIN = 40.0
CHROMA_MIN = 45.0
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
_OPENRGB_SOCKET_ERRORS = (
    OpenRGBDisconnected,
    BrokenPipeError,
    ConnectionResetError,
    TimeoutError,
    ConnectionAbortedError,
    ConnectionRefusedError,
    OSError,
)
KNOWN_DEVICE_TYPES = {item.name.lower() for item in DeviceType}

APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
OPENRGB_EXE = APP_DIR / "bin" / "OpenRGB" / "openrgb.exe"
CONFIG_PATH = APP_DIR / "ambilight.json"

log = logging.getLogger("ambilight")

_openrgb_proc: subprocess.Popen | None = None
_elevate_attempted = False
_missing_logged = False
_mutex_handle = None
_icon = None
_icon_lock = threading.Lock()
_config_lock = threading.Lock()


@dataclass(frozen=True)
class Settings:
    fps: float = 5.0
    smooth_alpha: float = 0.4
    max_brightness: int = 250
    brightness: float = 1.0
    idle_color: tuple[int, int, int] = (20, 35, 65)
    max_idle_brightness: int = 60
    monitor: int = 1
    exclude_devices: tuple[str, ...] = ()
    hue_bins: int = 24
    openrgb_host: str = "127.0.0.1"
    openrgb_port: int = 6742
    on_exit: str = "leave"
    locked_sleep: float = 5.0
    pause_when_locked: bool = True


class AppState:
    def __init__(self, brightness: float) -> None:
        self.stop = threading.Event()
        self.status = "запуск"
        self._lock = threading.Lock()
        self._paused = False
        self._brightness = brightness
        self._exit_mode = "leave"
        self._send_gen = 0

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def toggle_paused(self) -> bool:
        with self._lock:
            self._paused = not self._paused
            return self._paused

    def brightness(self) -> float:
        with self._lock:
            return self._brightness

    def set_brightness(self, scale: float) -> None:
        with self._lock:
            self._brightness = scale
            self._send_gen += 1

    def request_send(self) -> None:
        with self._lock:
            self._send_gen += 1

    def send_token(self) -> int:
        with self._lock:
            return self._send_gen

    def set_exit_mode(self, mode: str) -> None:
        with self._lock:
            self._exit_mode = mode

    def exit_mode(self) -> str:
        with self._lock:
            return self._exit_mode


def setup_logging() -> None:
    log.setLevel(logging.INFO)
    log.handlers.clear()
    log.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        log_dir = Path(os.environ.get("LOCALAPPDATA") or APP_DIR) / "AmbilightRGB"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "ambilight.log",
            maxBytes=512_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    except Exception:
        pass
    stream = sys.stderr
    if stream is not None and getattr(stream, "isatty", lambda: False)():
        console = logging.StreamHandler(stream)
        console.setFormatter(formatter)
        log.addHandler(console)
    if not log.handlers:
        log.addHandler(logging.NullHandler())


def _clamp_float(value, default: float, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(lo, min(hi, number))


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def default_config() -> dict:
    settings = Settings()
    return {
        "fps": settings.fps,
        "smooth_alpha": settings.smooth_alpha,
        "max_brightness": settings.max_brightness,
        "brightness": settings.brightness,
        "idle_color": list(settings.idle_color),
        "max_idle_brightness": settings.max_idle_brightness,
        "monitor": settings.monitor,
        "exclude_devices": list(settings.exclude_devices),
        "hue_bins": settings.hue_bins,
        "openrgb_host": settings.openrgb_host,
        "openrgb_port": settings.openrgb_port,
        "on_exit": settings.on_exit,
        "locked_sleep": settings.locked_sleep,
        "pause_when_locked": settings.pause_when_locked,
    }


def write_default_config(path: Path) -> None:
    path.write_text(
        json.dumps(default_config(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _parse_color(value, default: list[int]) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return tuple(default)  # type: ignore[return-value]
    try:
        return tuple(_clamp_int(channel, default[i], 0, 255) for i, channel in enumerate(value))  # type: ignore[return-value]
    except (TypeError, ValueError):
        return tuple(default)  # type: ignore[return-value]


def _parse_exclude(value) -> tuple[tuple[str, ...], list[str]]:
    if value is None:
        return (), []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return (), []
    known: list[str] = []
    unknown: list[str] = []
    for item in value:
        name = str(item).strip().lower()
        if not name:
            continue
        if name in KNOWN_DEVICE_TYPES:
            if name not in known:
                known.append(name)
        else:
            unknown.append(name)
    return tuple(known), unknown


def settings_from_mapping(data: dict | None) -> tuple[Settings, list[str]]:
    base = default_config()
    source = data or {}
    exclude, unknown = _parse_exclude(source.get("exclude_devices", base["exclude_devices"]))
    on_exit = source.get("on_exit", base["on_exit"])
    if on_exit not in {"leave", "idle", "off"}:
        on_exit = "leave"
    host = source.get("openrgb_host", base["openrgb_host"])
    if not isinstance(host, str) or not host.strip():
        host = str(base["openrgb_host"])
    pause_when_locked = source.get("pause_when_locked", base["pause_when_locked"])
    settings = Settings(
        fps=_clamp_float(source.get("fps", base["fps"]), float(base["fps"]), *FPS_LIMIT),
        smooth_alpha=_clamp_float(
            source.get("smooth_alpha", base["smooth_alpha"]),
            float(base["smooth_alpha"]),
            *SMOOTH_LIMIT,
        ),
        max_brightness=_clamp_int(
            source.get("max_brightness", base["max_brightness"]),
            int(base["max_brightness"]),
            1,
            255,
        ),
        brightness=_clamp_float(
            source.get("brightness", base["brightness"]),
            float(base["brightness"]),
            *BRIGHTNESS_LIMIT,
        ),
        idle_color=_parse_color(source.get("idle_color", base["idle_color"]), list(base["idle_color"])),
        max_idle_brightness=_clamp_int(
            source.get("max_idle_brightness", base["max_idle_brightness"]),
            int(base["max_idle_brightness"]),
            0,
            255,
        ),
        monitor=_clamp_int(source.get("monitor", base["monitor"]), int(base["monitor"]), 0, 16),
        exclude_devices=exclude,
        hue_bins=_clamp_int(source.get("hue_bins", base["hue_bins"]), int(base["hue_bins"]), *HUE_BIN_LIMIT),
        openrgb_host=host.strip(),
        openrgb_port=_clamp_int(
            source.get("openrgb_port", base["openrgb_port"]),
            int(base["openrgb_port"]),
            1,
            65535,
        ),
        on_exit=on_exit,
        locked_sleep=_clamp_float(
            source.get("locked_sleep", base["locked_sleep"]),
            float(base["locked_sleep"]),
            0.5,
            120.0,
        ),
        pause_when_locked=bool(pause_when_locked),
    )
    return settings, unknown


def load_settings() -> Settings:
    if not CONFIG_PATH.is_file():
        try:
            write_default_config(CONFIG_PATH)
        except Exception:
            log.warning("Не удалось записать %s", CONFIG_PATH, exc_info=True)
        return Settings()
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.warning("Не читается %s, беру значения по умолчанию", CONFIG_PATH, exc_info=True)
        return Settings()
    if not isinstance(raw, dict):
        log.warning("В %s ожидался объект JSON", CONFIG_PATH)
        return Settings()
    settings, unknown = settings_from_mapping(raw)
    if unknown:
        log.warning("Неизвестные типы в exclude_devices: %s", ", ".join(unknown))
    return settings


def persist_brightness(scale: float) -> None:
    with _config_lock:
        data = default_config()
        if CONFIG_PATH.is_file():
            try:
                loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data.update(loaded)
            except Exception:
                log.warning("Не удалось обновить %s", CONFIG_PATH, exc_info=True)
                return
        data["brightness"] = scale
        try:
            CONFIG_PATH.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception:
            log.warning("Не удалось записать %s", CONFIG_PATH, exc_info=True)


def idle_color_for(mean_luma: float, settings: Settings) -> tuple[int, int, int]:
    brightness = min(float(settings.max_idle_brightness), max(0.0, mean_luma))
    if brightness < 1.0:
        return tuple(int(channel * 0.4) for channel in settings.idle_color)
    base = np.array(settings.idle_color, dtype=np.float64)
    peak = float(base.max()) or 1.0
    scaled = base * (brightness / peak)
    return int(scaled[0]), int(scaled[1]), int(scaled[2])


def _hues_bgr(bgr: np.ndarray, chroma: np.ndarray) -> np.ndarray:
    blue = bgr[:, 0]
    green = bgr[:, 1]
    red = bgr[:, 2]
    hue = np.empty(len(bgr), dtype=np.float64)
    safe = np.maximum(chroma, 1e-6)
    red_max = (red >= green) & (red >= blue)
    green_max = (green > red) & (green >= blue)
    blue_max = ~(red_max | green_max)
    hue[red_max] = np.mod((green[red_max] - blue[red_max]) / safe[red_max], 6.0)
    hue[green_max] = ((blue[green_max] - red[green_max]) / safe[green_max]) + 2.0
    hue[blue_max] = ((red[blue_max] - green[blue_max]) / safe[blue_max]) + 4.0
    return np.mod(hue * 60.0, 360.0)


def dominant_from_bgr(image, settings: Settings) -> tuple[int, int, int]:
    """Одна корзина оттенка с наибольшим весом chroma². Противоположные цвета не смешиваются."""
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[2] < 3 or arr.shape[0] == 0 or arr.shape[1] == 0:
        return idle_color_for(0.0, settings)

    bgr = np.ascontiguousarray(arr[:, :, :3], dtype=np.float64).reshape(-1, 3)
    if bgr.size == 0:
        return idle_color_for(0.0, settings)

    peak = bgr.max(axis=1)
    chroma = peak - bgr.min(axis=1)
    mask = (peak > LUMA_MIN) & (chroma > CHROMA_MIN)
    if not np.any(mask):
        return idle_color_for(float(bgr.mean()), settings)

    valid = bgr[mask]
    weights = np.square(chroma[mask])
    bins = max(1, int(settings.hue_bins))
    bin_idx = np.minimum(((_hues_bgr(valid, chroma[mask]) * bins) / 360.0).astype(np.int32), bins - 1)
    bin_weight = np.bincount(bin_idx, weights=weights, minlength=bins).astype(np.float64)
    score = bin_weight + 0.25 * (np.roll(bin_weight, 1) + np.roll(bin_weight, -1))
    winner = int(score.argmax())
    selected = bin_idx == winner
    if not np.any(selected):
        selected = np.ones(len(valid), dtype=bool)

    chosen_weights = weights[selected]
    weight_sum = float(chosen_weights.sum())
    if weight_sum <= 0:
        return idle_color_for(float(bgr.mean()), settings)

    blue, green, red = (valid[selected] * chosen_weights[:, None]).sum(axis=0) / weight_sum
    rgb = np.array([red, green, blue], dtype=np.float64)
    rgb -= rgb.min()
    rgb_peak = float(rgb.max())
    if rgb_peak <= 0:
        return idle_color_for(float(bgr.mean()), settings)
    rgb = rgb / rgb_peak * float(settings.max_brightness)
    return tuple(_clamp_channel(channel) for channel in rgb)


def rgb_to_hsv(red: int, green: int, blue: int) -> tuple[float, float, float]:
    rf, gf, bf = red / 255.0, green / 255.0, blue / 255.0
    peak = max(rf, gf, bf)
    floor = min(rf, gf, bf)
    delta = peak - floor
    if delta < 1e-8:
        hue = 0.0
    elif peak == rf:
        hue = (60.0 * ((gf - bf) / delta) + 360.0) % 360.0
    elif peak == gf:
        hue = (60.0 * ((bf - rf) / delta) + 120.0) % 360.0
    else:
        hue = (60.0 * ((rf - gf) / delta) + 240.0) % 360.0
    saturation = 0.0 if peak < 1e-8 else delta / peak
    return hue, saturation, peak


def hsv_to_rgb(hue: float, saturation: float, value: float) -> tuple[float, float, float]:
    hue = hue % 360.0
    saturation = min(1.0, max(0.0, saturation))
    value = min(1.0, max(0.0, value))
    chroma = value * saturation
    mix = chroma * (1.0 - abs((hue / 60.0) % 2.0 - 1.0))
    floor = value - chroma
    if hue < 60:
        red, green, blue = chroma, mix, 0.0
    elif hue < 120:
        red, green, blue = mix, chroma, 0.0
    elif hue < 180:
        red, green, blue = 0.0, chroma, mix
    elif hue < 240:
        red, green, blue = 0.0, mix, chroma
    elif hue < 300:
        red, green, blue = mix, 0.0, chroma
    else:
        red, green, blue = chroma, 0.0, mix
    return (red + floor) * 255.0, (green + floor) * 255.0, (blue + floor) * 255.0


def lerp_hsv(
    origin: tuple[float, float, float],
    target: tuple[float, float, float],
    amount: float,
) -> tuple[float, float, float]:
    amount = min(1.0, max(0.0, amount))
    delta_hue = (target[0] - origin[0] + 180.0) % 360.0 - 180.0
    return (
        (origin[0] + delta_hue * amount) % 360.0,
        origin[1] + (target[1] - origin[1]) * amount,
        origin[2] + (target[2] - origin[2]) * amount,
    )


def pick_monitor(monitors, index: int):
    if len(monitors) == 0:
        raise RuntimeError("нет мониторов")
    if 0 <= index < len(monitors):
        return monitors[index]
    return monitors[1] if len(monitors) > 1 else monitors[0]


def get_dominant_color(sct, monitor, settings: Settings) -> tuple[int, int, int]:
    shot = sct.grab(monitor)
    # Copy before the mss buffer is released.
    frame = np.array(shot, copy=True)[::16, ::16, :3]
    return dominant_from_bgr(frame, settings)


def _port_open(settings: Settings, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((settings.openrgb_host, settings.openrgb_port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port(stop: threading.Event, settings: Settings, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stop.is_set():
            return False
        if _port_open(settings):
            return True
        if stop.wait(0.2):
            return False
    return _port_open(settings)


def _needs_driver_init() -> bool:
    service_missing = False
    try:
        result = subprocess.run(
            ["sc", "query", "WinRing0_1_2_0"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        service_missing = result.returncode != 0
    except Exception:
        service_missing = False
    appdata = os.environ.get("APPDATA")
    profile_missing = bool(appdata) and not (Path(appdata) / "OpenRGB").exists()
    return service_missing or profile_missing


def _launch_elevated() -> bool:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    result = shell32.ShellExecuteW(
        None,
        "runas",
        str(OPENRGB_EXE),
        "--server --startminimized",
        str(OPENRGB_EXE.parent),
        7,
    )
    return int(result or 0) > 32


def ensure_openrgb(stop: threading.Event, settings: Settings) -> None:
    """Start the portable SDK server when the port is closed."""
    global _openrgb_proc, _elevate_attempted, _missing_logged
    if _port_open(settings):
        return
    if not OPENRGB_EXE.is_file():
        if not _missing_logged:
            log.warning("Порт %s закрыт и нет %s", settings.openrgb_port, OPENRGB_EXE)
            _missing_logged = True
        return
    if _openrgb_proc is not None and _openrgb_proc.poll() is None:
        _wait_for_port(stop, settings, 5.0)
        return
    if _needs_driver_init() and not _elevate_attempted:
        _elevate_attempted = True
        log.info("Первый запуск OpenRGB: запрос прав для драйвера SMBus")
        if _launch_elevated():
            _wait_for_port(stop, settings, 60.0)
            return
        log.warning("Повышение прав отклонено, запускаю OpenRGB без администратора")
    log.info("Запуск OpenRGB SDK")
    _openrgb_proc = subprocess.Popen(
        [str(OPENRGB_EXE), "--server", "--startminimized"],
        cwd=str(OPENRGB_EXE.parent),
        creationflags=CREATE_NO_WINDOW,
    )
    _wait_for_port(stop, settings, 8.0)


def stop_owned_openrgb() -> None:
    """Terminate only the OpenRGB process this app started."""
    global _openrgb_proc
    proc = _openrgb_proc
    _openrgb_proc = None
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass


def device_type_name(device) -> str:
    kind = getattr(device, "type", None)
    name = getattr(kind, "name", None)
    if name:
        return str(name).lower()
    return str(kind or "").lower()


def selected_devices(devices, settings: Settings) -> list:
    excluded = set(settings.exclude_devices)
    return [device for device in devices if device_type_name(device) not in excluded]


def _mode_names(device) -> set[str]:
    try:
        return {mode.name.lower() for mode in (device.modes or [])}
    except Exception:
        return set()


def ensure_device_mode(device) -> None:
    available = _mode_names(device)
    for mode_name in ("direct", "static"):
        if available and mode_name not in available:
            continue
        try:
            device.set_mode(mode_name)
            return
        except Exception:
            continue


def ensure_devices_modes(devices) -> None:
    ordered = sorted(
        devices,
        key=lambda device: 0 if getattr(device, "type", None) == DeviceType.GPU else 1,
    )
    for device in ordered:
        try:
            ensure_device_mode(device)
        except Exception:
            log.debug("Режим не переключён: %s", getattr(device, "name", "?"), exc_info=True)


def connect_openrgb(settings: Settings) -> OpenRGBClient:
    client = OpenRGBClient(settings.openrgb_host, settings.openrgb_port, name="AmbilightRGB")
    ensure_devices_modes(selected_devices(client.devices, settings))
    return client


def close_client(client):
    if client is None:
        return None
    try:
        client.disconnect()
    except Exception:
        pass
    return None


def send_color(client, rgb: tuple[int, int, int], settings: Settings) -> None:
    color = RGBColor(*rgb)
    for device in selected_devices(client.devices, settings):
        try:
            device.set_color(color)
        except _OPENRGB_SOCKET_ERRORS:
            raise
        except Exception:
            log.debug("Пропуск %s", getattr(device, "name", "?"), exc_info=True)


def apply_exit(client, settings: Settings, mode: str) -> None:
    if client is None or mode == "leave":
        return
    color = (0, 0, 0) if mode == "off" else settings.idle_color
    try:
        send_color(client, color, settings)
    except Exception:
        log.warning("Не удалось сменить цвет при выходе", exc_info=True)


def set_icon(icon) -> None:
    global _icon
    with _icon_lock:
        _icon = icon


def set_status(state: AppState, text: str) -> None:
    state.status = text
    with _icon_lock:
        icon = _icon
    if icon is None:
        return
    try:
        icon.title = f"AmbilightRGB — {text}"
    except Exception:
        pass


def session_locked() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.argtypes = [ctypes.c_uint, ctypes.c_bool, ctypes.c_uint]
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    user32.CloseDesktop.restype = ctypes.c_bool
    ctypes.set_last_error(0)
    desktop = user32.OpenInputDesktop(0, False, 0x0001)
    if desktop:
        user32.CloseDesktop(desktop)
        return False
    return True


def _device_summary(devices) -> str:
    names = [getattr(device, "name", "?") for device in devices]
    return ", ".join(names) if names else "нет"


def run_loop(state: AppState, settings: Settings) -> None:
    client = None
    capture = None
    prev_hsv = None
    last_sent = None
    applied_token = -1
    last_refresh = 0.0
    started = time.monotonic()
    last_count = -1
    was_locked = False
    next_connect_log = 0.0

    try:
        while not state.stop.is_set():
            if state.is_paused():
                set_status(state, "пауза")
                if state.stop.wait(0.25):
                    break
                continue

            locked = session_locked() if settings.pause_when_locked else False
            if locked != was_locked:
                if locked:
                    log.info("Экран заблокирован, захват приостановлен")
                    set_status(state, "экран заблокирован")
                else:
                    log.info("Экран разблокирован")
                was_locked = locked
            if locked:
                if state.stop.wait(settings.locked_sleep):
                    break
                continue

            if client is None:
                try:
                    ensure_openrgb(state.stop, settings)
                    if state.stop.is_set():
                        break
                    client = connect_openrgb(settings)
                    devices = selected_devices(client.devices, settings)
                    last_count = len(list(client.devices))
                    last_refresh = time.monotonic()
                    state.request_send()
                    log.info("OpenRGB: %s", _device_summary(devices))
                    set_status(state, f"устройств: {len(devices)}")
                    next_connect_log = 0.0
                except Exception as exc:
                    now = time.monotonic()
                    if now >= next_connect_log:
                        log.warning("Нет соединения с OpenRGB: %s", exc)
                        next_connect_log = now + 30.0
                    set_status(state, "переподключение")
                    client = close_client(client)
                    if state.stop.wait(2.0):
                        break
                    continue

            now = time.monotonic()
            refresh_every = 5.0 if now - started < 30.0 else 45.0
            if now - last_refresh >= refresh_every:
                try:
                    client.update()
                    devices = list(client.devices)
                    if len(devices) != last_count:
                        chosen = selected_devices(devices, settings)
                        ensure_devices_modes(chosen)
                        log.info("Список устройств обновлён (%s): %s", len(chosen), _device_summary(chosen))
                        set_status(state, f"устройств: {len(chosen)}")
                        state.request_send()
                    last_count = len(devices)
                    last_refresh = now
                except _OPENRGB_SOCKET_ERRORS as exc:
                    log.warning("Сокет OpenRGB закрыт: %s", exc)
                    client = close_client(client)
                    state.request_send()
                    if state.stop.wait(1.0):
                        break
                    continue
                except Exception:
                    log.warning("Не удалось обновить устройства", exc_info=True)
                    last_refresh = now

            if capture is None:
                try:
                    capture = mss.MSS()
                except Exception:
                    log.warning("Захват экрана недоступен", exc_info=True)
                    if state.stop.wait(2.0):
                        break
                    continue

            frame_start = time.perf_counter()
            try:
                monitor = pick_monitor(capture.monitors, settings.monitor)
                target = get_dominant_color(capture, monitor, settings)
            except Exception:
                log.warning("Кадр не снят", exc_info=True)
                try:
                    capture.close()
                except Exception:
                    pass
                capture = None
                if state.stop.wait(2.0):
                    break
                continue

            target_hsv = rgb_to_hsv(*target)
            prev_hsv = target_hsv if prev_hsv is None else lerp_hsv(prev_hsv, target_hsv, settings.smooth_alpha)
            red, green, blue = hsv_to_rgb(*prev_hsv)
            scale = state.brightness()
            current = tuple(_clamp_channel(channel * scale) for channel in (red, green, blue))
            token = state.send_token()
            if current != last_sent or token != applied_token:
                try:
                    send_color(client, current, settings)
                except _OPENRGB_SOCKET_ERRORS as exc:
                    log.warning("Сокет OpenRGB закрыт: %s", exc)
                    client = close_client(client)
                    state.request_send()
                    if state.stop.wait(1.0):
                        break
                    continue
                except Exception:
                    log.warning("Цвет не отправлен", exc_info=True)
                    client = close_client(client)
                    state.request_send()
                    if state.stop.wait(1.0):
                        break
                    continue
                last_sent = current
                applied_token = token

            delay = max(0.0, (1.0 / settings.fps) - (time.perf_counter() - frame_start))
            if state.stop.wait(delay):
                break
    finally:
        apply_exit(client, settings, state.exit_mode())
        if capture is not None:
            try:
                capture.close()
            except Exception:
                pass
        close_client(client)
        stop_owned_openrgb()


def _make_icon(paused: bool):
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if paused:
        outer, mid, inner = (70, 80, 100, 255), (120, 130, 145, 255), (170, 174, 182, 255)
    else:
        outer, mid, inner = (16, 32, 64, 255), (30, 170, 255, 255), (255, 70, 150, 255)
    draw.ellipse((2, 2, 61, 61), fill=outer)
    draw.ellipse((14, 14, 49, 49), fill=mid)
    draw.ellipse((24, 24, 39, 39), fill=inner)
    return image


def run_tray(state: AppState, settings: Settings) -> None:
    if pystray is None or Image is None or ImageDraw is None:
        raise RuntimeError("pystray недоступен")

    images = {"run": _make_icon(False), "pause": _make_icon(True)}

    def on_pause(icon, _item) -> None:
        paused = state.toggle_paused()
        icon.icon = images["pause"] if paused else images["run"]
        set_status(state, "пауза" if paused else "работает")

    def on_quit(icon, mode: str) -> None:
        state.set_exit_mode(mode)
        state.stop.set()
        icon.stop()

    def on_open_config(_icon, _item) -> None:
        if not CONFIG_PATH.is_file():
            try:
                write_default_config(CONFIG_PATH)
            except Exception:
                log.warning("Не удалось записать %s", CONFIG_PATH, exc_info=True)
                return
        os.startfile(CONFIG_PATH)  # noqa: S606 - user-requested config open on Windows

    def brightness_item(label: str, scale: float):
        def chosen(icon, _item, scale: float = scale) -> None:
            state.set_brightness(scale)
            persist_brightness(scale)
            try:
                icon.update_menu()
            except Exception:
                log.debug("Меню не обновилось", exc_info=True)

        def is_checked(_item, scale: float = scale) -> bool:
            return abs(state.brightness() - scale) < 0.02

        return pystray.MenuItem(label, chosen, checked=is_checked, radio=True)

    menu = pystray.Menu(
        pystray.MenuItem(lambda _item: state.status, lambda _icon, _item: None, enabled=False),
        pystray.MenuItem(lambda _item: "Продолжить" if state.is_paused() else "Пауза", on_pause),
        pystray.MenuItem(
            "Яркость",
            pystray.Menu(
                brightness_item("100%", 1.0),
                brightness_item("75%", 0.75),
                brightness_item("50%", 0.5),
                brightness_item("25%", 0.25),
            ),
        ),
        pystray.MenuItem("Настройки", on_open_config),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", lambda icon, _item: on_quit(icon, settings.on_exit)),
        pystray.MenuItem("Выключить свет и выйти", lambda icon, _item: on_quit(icon, "off")),
    )
    icon = pystray.Icon("AmbilightRGB", images["run"], "AmbilightRGB", menu)
    set_icon(icon)
    icon.run()


def acquire_single_instance() -> bool:
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    ctypes.set_last_error(0)
    handle = kernel32.CreateMutexW(None, True, "Local\\AmbilightRGB")
    if not handle:
        return False
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def _notify_already_running() -> None:
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "AmbilightRGB уже запущен. Иконка в трее у часов.",
            "AmbilightRGB",
            0x00050040,
        )
    except Exception:
        pass


def main() -> None:
    setup_logging()
    log.info("AmbilightRGB %s", __version__)
    if not acquire_single_instance():
        log.error("AmbilightRGB уже запущен")
        _notify_already_running()
        return

    atexit.register(stop_owned_openrgb)
    settings = load_settings()
    log.info("Конфиг: %s", CONFIG_PATH)
    state = AppState(settings.brightness)
    worker = threading.Thread(target=run_loop, args=(state, settings), name="ambilight", daemon=False)
    worker.start()
    tray_failed = False
    try:
        run_tray(state, settings)
    except KeyboardInterrupt:
        log.info("Остановка")
    except Exception:
        tray_failed = True
        log.exception("Трей недоступен, работаю без иконки")
    if tray_failed:
        try:
            while worker.is_alive():
                worker.join(0.5)
        except KeyboardInterrupt:
            log.info("Остановка")
    state.stop.set()
    worker.join(timeout=8)


if __name__ == "__main__":
    main()
