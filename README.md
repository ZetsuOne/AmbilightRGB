# AmbilightRGB

**EN:** Screen-synced ambient RGB in ~100 lines of math. No AI. **5 FPS**, near-zero GPU/CPU cost, all OpenRGB devices painted every frame.

**RU:** Фоновая подсветка в такт экрану на ~100 строках математики. Без ИИ. **5 FPS**, почти нулевая нагрузка, все устройства OpenRGB красятся каждый кадр.

Windows · Python 3.10+ · [OpenRGB](https://openrgb.org/) SDK · MIT

---

## English

### Why this exists

You do not need AI, ML, or edge detection for background Ambilight. A downsampled screen grab, chroma-weighted mean RGB (whites/greys/blacks filtered out), and exponential smoothing at **5 FPS** keep the glow in sync with the picture while using **~0% GPU** and a tiny CPU footprint. OpenRGB then broadcasts one `RGBColor` to every device — motherboard ARGB, coolers, and the GPU alike.

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

**First launch:** Windows will ask **once** for Administrator rights so OpenRGB can register the SMBus driver (`WinRing0x64.sys`) for motherboard lighting. After that, every later run starts fully in the background with **no** UAC prompts.

`start_ambilight.bat` checks for the `WinRing0_1_2_0` service and `%APPDATA%\OpenRGB`. On first run it elevates `bin/OpenRGB/openrgb.exe` once; afterward it starts `openrgb.exe --server --startminimized` with normal rights.

### Layout

| Path | Role |
| --- | --- |
| `ambilight.py` | Capture → chroma filter → EMA smooth → OpenRGB broadcast |
| `ambilight.pyw` | Same entry, no console window |
| `start_ambilight.bat` | One-click launch + first-run driver init |
| `bin/OpenRGB/` | Portable OpenRGB (`openrgb.exe` — download separately) |
| `docs/` | Photo proofs |
| `requirements.txt` | `openrgb-python`, `mss`, `numpy`, `Pillow` |

### License

MIT — see [LICENSE](LICENSE).

---

## Русский

### Зачем это

Для фоновой подсветки в такт экрану **не нужен ИИ**. Даунсэмпл кадра, средний RGB с весом по насыщенности (белое / серое / чёрное отфильтровано) и экспоненциальное сглаживание на **5 FPS** дают синхронный glow при **~0% нагрузки на GPU** и минимальном следе в системе. OpenRGB рассылает один `RGBColor` на **все** устройства — материнскую плату, кулеры и видеокарту.

На пустых и ахроматических кадрах (загрузка, чёрная сцена, белый экран) цель плавно уходит в спокойный приглушённый синий, а не зависает на последнем случайном цвете. При обрыве сокета OpenRGB скрипт сам ждёт и переподключается.

### Hidden GPU RGB Unlock

На ряде видеокарт (например **Palit RTX 3060 Dual**) подсветка в фирменной утилите (**ThunderMaster**) и в **GUI OpenRGB** выглядит заблокированной: одноцветная белая / неуправляемая.

Прямой бродкаст через OpenRGB SDK — `device.set_color(...)` — разблокирует полноценный RGB. Скрипт по возможности включает режим `direct` и каждый кадр красит все устройства целиком.

#### Фото-пруфы

| Голубой / бирюзовый | Малиново-красный | Фиолетово-розовый |
| :---: | :---: | :---: |
| ![ARGB cyan](docs/ARGB.jpg) | ![ARGB red](docs/ARGB-2.jpg) | ![ARGB violet](docs/ARGB-3.jpg) |

### Требования

- Windows 10/11
- Python 3.10+
- Portable [OpenRGB](https://openrgb.org/) в `bin/OpenRGB/openrgb.exe`  
  *(или готовая сборка из **Releases** — бинарники OpenRGB в репозиторий не входят)*

### Быстрый старт

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
start_ambilight.bat
```

Или напрямую (SDK-сервер OpenRGB уже должен слушать `127.0.0.1:6742`):

```bat
python ambilight.py
```

Тихий режим (без консоли): `ambilight.pyw` / `pythonw ambilight.pyw`.

**Самый первый запуск:** Windows **один раз** запросит права администратора, чтобы OpenRGB зарегистрировал драйвер SMBus (`WinRing0x64.sys`) для подсветки материнской платы. Все последующие запуски идут полностью в фоне **без** UAC.

`start_ambilight.bat` проверяет службу `WinRing0_1_2_0` и папку `%APPDATA%\OpenRGB`. При первом запуске поднимает `bin/OpenRGB/openrgb.exe` с повышением прав; дальше — `openrgb.exe --server --startminimized` с обычными правами.

### Структура

| Путь | Назначение |
| --- | --- |
| `ambilight.py` | Захват → фильтр chroma → EMA → бродкаст OpenRGB |
| `ambilight.pyw` | Тот же вход без консоли |
| `start_ambilight.bat` | Запуск в один клик + инициализация драйвера |
| `bin/OpenRGB/` | Portable OpenRGB (`openrgb.exe` — скачивается отдельно) |
| `docs/` | Фото-пруфы |
| `requirements.txt` | `openrgb-python`, `mss`, `numpy`, `Pillow` |

### Лицензия

MIT — файл [LICENSE](LICENSE).
