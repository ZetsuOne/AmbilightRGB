import time
import mss
import numpy as np
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor, OpenRGBDisconnected

FPS = 5
IDLE_COLOR = (20, 35, 65)  # спокойный приглушённый оттенок для ахроматических сцен
MAX_IDLE_BRIGHTNESS = 60

_OPENRGB_SOCKET_ERRORS = (
    OpenRGBDisconnected,
    BrokenPipeError,
    ConnectionResetError,
    TimeoutError,
    ConnectionAbortedError,
    ConnectionRefusedError,
    OSError,
)


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


def connect_openrgb() -> OpenRGBClient:
    client = OpenRGBClient()
    for dev in client.devices:
        try:
            dev.set_mode("direct")
        except Exception:
            pass
    return client


def main():
    rgb = connect_openrgb()
    prev = (0, 0, 0)
    sct = mss.MSS()
    try:
        while True:
            # --- захват экрана ---
            try:
                monitor = sct.monitors[1]
                target = get_dominant_color(sct, monitor)
            except Exception:
                try:
                    sct.close()
                except Exception:
                    pass
                time.sleep(1)
                try:
                    sct = mss.MSS()
                except Exception:
                    pass
                continue

            # Плавное сглаживание перехода (EMA), чтобы подсветка не дёргалась
            curr = tuple(int(prev[i] * 0.6 + target[i] * 0.4) for i in range(3))

            # --- отправка в OpenRGB ---
            try:
                if curr != prev:
                    color = RGBColor(*curr)
                    for dev in rgb.devices:
                        try:
                            dev.set_color(color)
                        except _OPENRGB_SOCKET_ERRORS:
                            raise
                        except Exception:
                            pass
                    prev = curr
            except _OPENRGB_SOCKET_ERRORS:
                time.sleep(1)
                try:
                    rgb = connect_openrgb()
                except Exception:
                    pass
                continue
            except Exception:
                time.sleep(1)
                try:
                    rgb = connect_openrgb()
                except Exception:
                    pass
                continue

            time.sleep(1.0 / FPS)
    finally:
        try:
            sct.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
