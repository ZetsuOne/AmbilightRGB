import atexit
import socket
import subprocess
import sys
import time
from pathlib import Path

import mss
import numpy as np
from openrgb import OpenRGBClient
from openrgb.utils import DeviceType, RGBColor, OpenRGBDisconnected

FPS = 5
IDLE_COLOR = (20, 35, 65)  # спокойный приглушённый оттенок для ахроматических сцен
MAX_IDLE_BRIGHTNESS = 60
OPENRGB_HOST = "127.0.0.1"
OPENRGB_PORT = 6742
CREATE_NO_WINDOW = 0x08000000

BASE_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
OPENRGB_EXE = BASE_DIR / "bin" / "OpenRGB" / "openrgb.exe"

_OPENRGB_SOCKET_ERRORS = (
    OpenRGBDisconnected,
    BrokenPipeError,
    ConnectionResetError,
    TimeoutError,
    ConnectionAbortedError,
    ConnectionRefusedError,
    OSError,
)

_openrgb_proc: subprocess.Popen | None = None


def get_dominant_color(sct, monitor) -> tuple[int, int, int]:
    img = np.asarray(sct.grab(monitor))[::16, ::16, :3]  # BGR
    bgr = img.reshape(-1, 3).astype(np.float32)
    if bgr.size == 0:
        return IDLE_COLOR

    mx = bgr.max(axis=1)
    mn = bgr.min(axis=1)
    chroma = mx - mn  # чистота цвета (отсекаем серый и белый)
    mask = (mx > 40) & (chroma > 45)
    valid = bgr[mask]

    if len(valid) == 0:
        # Белый / чёрный / серый кадр: не держим старый цвет — цель = приглушённый idle
        # с яркостью от средней яркости кадра (потолок MAX_IDLE_BRIGHTNESS).
        mean_luma = float(bgr.mean())
        brightness = min(MAX_IDLE_BRIGHTNESS, max(0.0, mean_luma))
        base = np.array(IDLE_COLOR, dtype=np.float32)
        peak = float(base.max()) or 1.0
        scaled = base * (brightness / peak)
        if brightness < 1.0:
            return tuple(int(c * 0.4) for c in IDLE_COLOR)
        return int(scaled[0]), int(scaled[1]), int(scaled[2])

    # Взвешиваем по квадрату насыщенности, чтобы акценты побеждали фон
    weights = (chroma[mask] ** 2)[:, None]
    wsum = float(weights.sum())
    if wsum <= 0:
        return IDLE_COLOR
    b, g, r = (valid * weights).sum(axis=0) / wsum
    rgb = np.array([r, g, b], dtype=np.float32)
    # Обнуляем самый слабый канал — убираем пастель и белизну
    rgb -= rgb.min()
    peak = float(rgb.max())
    if peak <= 0:
        return IDLE_COLOR
    rgb = (rgb / peak) * 250.0
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def _port_open(host: str = OPENRGB_HOST, port: int = OPENRGB_PORT, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_openrgb(wait_s: float = 5.0) -> None:
    """If SDK port is closed, quietly start portable OpenRGB next to this app."""
    global _openrgb_proc
    if _port_open():
        return
    if not OPENRGB_EXE.is_file():
        return
    if _openrgb_proc is not None and _openrgb_proc.poll() is None:
        # Already spawned by us; just wait for the port
        pass
    else:
        _openrgb_proc = subprocess.Popen(
            [str(OPENRGB_EXE), "--server", "--startminimized"],
            cwd=str(OPENRGB_EXE.parent),
            creationflags=CREATE_NO_WINDOW,
        )
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _port_open():
            return
        time.sleep(0.1)


def stop_owned_openrgb() -> None:
    """Terminate only the OpenRGB process we started."""
    global _openrgb_proc
    if _openrgb_proc is None:
        return
    try:
        if _openrgb_proc.poll() is None:
            _openrgb_proc.terminate()
            try:
                _openrgb_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                _openrgb_proc.kill()
    except Exception:
        pass
    _openrgb_proc = None


DEVICE_REFRESH_INTERVAL = 5.0
DEVICE_REFRESH_WINDOW = 30.0


def _mode_names(dev) -> set[str]:
    try:
        return {m.name.lower() for m in (dev.modes or [])}
    except Exception:
        return set()


def ensure_device_mode(dev) -> None:
    """Try 'direct', then 'static'; ignore if the mode is fixed/unavailable."""
    available = _mode_names(dev)
    for mode_name in ("direct", "static"):
        if available and mode_name not in available:
            continue
        try:
            dev.set_mode(mode_name)
            return
        except Exception:
            continue


def ensure_devices_modes(devices) -> None:
    # Prefer GPUs first — they often appear late via I2C/NvAPI after motherboard HID.
    ordered = sorted(
        devices,
        key=lambda d: 0 if getattr(d, "type", None) == DeviceType.GPU else 1,
    )
    for dev in ordered:
        try:
            ensure_device_mode(dev)
        except Exception:
            pass


def connect_openrgb() -> OpenRGBClient:
    ensure_openrgb()
    client = OpenRGBClient()
    ensure_devices_modes(client.devices)
    return client


def create_mss(retry_delay: float = 2.0):
    """Create an mss capture session; retry while the desktop is not ready yet."""
    while True:
        try:
            return mss.MSS()
        except Exception:
            time.sleep(retry_delay)


def main():
    atexit.register(stop_owned_openrgb)
    ensure_openrgb()

    rgb = None
    for _ in range(15):
        try:
            rgb = connect_openrgb()
            break
        except Exception:
            ensure_openrgb()
            time.sleep(0.4)
    if rgb is None:
        rgb = connect_openrgb()

    prev = (0, 0, 0)
    started_at = time.time()
    last_device_refresh = 0.0
    last_device_count = len(list(rgb.devices))
    sct = create_mss()
    try:
        while True:
            now = time.time()
            device_count = len(list(rgb.devices))
            need_device_refresh = (
                device_count != last_device_count
                or (
                    now - started_at < DEVICE_REFRESH_WINDOW
                    and now - last_device_refresh >= DEVICE_REFRESH_INTERVAL
                )
            )
            if need_device_refresh:
                try:
                    rgb.update()
                    devices = list(rgb.devices)
                    new_count = len(devices)
                    # Late GPU via I2C/NvAPI: apply direct/static before set_color
                    if new_count != last_device_count:
                        ensure_devices_modes(devices)
                    last_device_count = new_count
                    last_device_refresh = now
                except _OPENRGB_SOCKET_ERRORS:
                    time.sleep(1)
                    try:
                        ensure_openrgb()
                        rgb = connect_openrgb()
                        last_device_count = len(list(rgb.devices))
                        last_device_refresh = time.time()
                    except Exception:
                        pass
                    continue
                except Exception:
                    last_device_refresh = now

            # --- захват экрана ---
            try:
                monitor = sct.monitors[1]
                target = get_dominant_color(sct, monitor)
            except Exception:
                try:
                    sct.close()
                except Exception:
                    pass
                time.sleep(2)
                sct = create_mss()
                continue

            # Плавное сглаживание перехода (EMA), чтобы подсветка не дёргалась
            curr = tuple(int(prev[i] * 0.6 + target[i] * 0.4) for i in range(3))

            # --- отправка в OpenRGB ---
            try:
                if curr != prev:
                    color = RGBColor(*curr)
                    for dev in rgb.devices:
                        try:
                            # Mode is prepared on connect / device-list refresh
                            dev.set_color(color)
                        except _OPENRGB_SOCKET_ERRORS:
                            raise
                        except Exception:
                            pass
                    prev = curr
            except _OPENRGB_SOCKET_ERRORS:
                time.sleep(1)
                try:
                    ensure_openrgb()
                    rgb = connect_openrgb()
                    last_device_count = len(list(rgb.devices))
                    last_device_refresh = time.time()
                except Exception:
                    pass
                continue
            except Exception:
                time.sleep(1)
                try:
                    ensure_openrgb()
                    rgb = connect_openrgb()
                    last_device_count = len(list(rgb.devices))
                    last_device_refresh = time.time()
                except Exception:
                    pass
                continue

            time.sleep(1.0 / FPS)
    finally:
        try:
            sct.close()
        except Exception:
            pass
        stop_owned_openrgb()


if __name__ == "__main__":
    main()
