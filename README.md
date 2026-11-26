# AmbilightRGB

**English** | [Русский](README_RU.md)

Screen-synced ambient RGB. No AI. **5 FPS**, near-zero GPU/CPU cost, all OpenRGB devices painted every frame.

Windows · Python 3.10+ · [OpenRGB](https://openrgb.org/) SDK · MIT

### Why this exists

You do not need AI, ML, or edge detection for background Ambilight. A downsampled screen grab drops whites, greys, and blacks, then votes the remaining pixels into hue bins weighted by chroma squared. The winning bin paints the room, so red and green on the same frame stay one pure color instead of blending into brown. HSV smoothing at **5 FPS** keeps the glow in sync while using **~0% GPU** and a tiny CPU footprint. OpenRGB then broadcasts one `RGBColor` to every device — motherboard ARGB, coolers, and the GPU alike. Device types listed in `exclude_devices` are left alone.

On empty or achromatic frames (loading screens, black scenes, full white), the target fades to a calm muted blue instead of freezing on the last random color. If the OpenRGB socket drops, the script waits and reconnects on its own.

### Hidden GPU RGB unlock

Many GPUs (for example **Palit RTX 3060 Dual**) look “stuck” on a single white / unmanaged color in:

- the vendor tool (**ThunderMaster**), and
- the OpenRGB **GUI**

A direct SDK broadcast via `device.set_color(...)` unlocks full RGB on those cards. This project sets mode `direct` where possible and paints **all** OpenRGB devices every frame.

#### Photo proofs

| Cyan / teal | Magenta-red | Violet-pink |
| :---: | :---: | :---: |
| ![ARGB cyan](docs/ARGB.jpg) | ![ARGB red](docs/ARGB-2.jpg) | ![ARGB violet](docs/ARGB-3.jpg) |

### Requirements

- Windows 10/11
- Python 3.10+
- Portable [OpenRGB](https://openrgb.org/) unpacked to `bin/OpenRGB/openrgb.exe`  
  *(or a ready bundle from **Releases** — OpenRGB binaries are not in this repo)*

### Quick start

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
start_ambilight.bat
```

Or run the script directly (OpenRGB SDK server must already be listening on `127.0.0.1:6742`):

```bat
python ambilight.py
```

Silent (no console): double-click `ambilight.pyw` / `pythonw ambilight.pyw`.

A tray icon appears next to the clock: pause, brightness, settings, quit. Starting the app again does not launch a second copy.

**First launch:** if the `WinRing0_1_2_0` service or the OpenRGB profile folder is missing, the app asks **once** for Administrator rights and starts `bin/OpenRGB/openrgb.exe --server --startminimized`. Later runs start the SDK server with normal rights and no UAC. An OpenRGB that is already listening on `127.0.0.1:6742` is reused.

`ambilight.json` is created next to the script or `ambilight.exe` on first launch (`fps`, `max_brightness`, `brightness`, `monitor`, `exclude_devices`, `hue_bins`, `on_exit`, `pause_when_locked`). The log is `%LOCALAPPDATA%\AmbilightRGB\ambilight.log`.

### Layout

| Path | Role |
| --- | --- |
| `ambilight.py` | Capture → hue-bin vote → HSV smooth → OpenRGB broadcast |
| `ambilight.pyw` | Same entry, no console window |
| `start_ambilight.bat` | One-click launch via `pythonw` |
| `ambilight.json` | Created on first launch, next to the app |
| `bin/OpenRGB/` | Portable OpenRGB (`openrgb.exe` — download separately) |
| `docs/` | Photo proofs |
| `requirements.txt` | `openrgb-python`, `mss`, `numpy`, `Pillow`, `pystray` |

### License

MIT — see [LICENSE](LICENSE).
