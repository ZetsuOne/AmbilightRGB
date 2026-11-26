# AmbilightRGB

[English](README.md) | **Русский**

Фоновая подсветка в такт экрану. Без ИИ. **5 FPS**, почти нулевая нагрузка, все устройства OpenRGB красятся каждый кадр.

Windows · Python 3.10+ · [OpenRGB](https://openrgb.org/) SDK · MIT

### Зачем это

Для фоновой подсветки в такт экрану **не нужен ИИ**. Даунсэмпл кадра отбрасывает белое, серое и чёрное, а оставшиеся пиксели голосуют в корзины оттенка с весом `chroma²`. Побеждает одна корзина: красный и зелёный на одном кадре не смешиваются в коричневый. Сглаживание в HSV на **5 FPS** даёт синхронный glow при **~0% нагрузки на GPU** и минимальном следе в системе. OpenRGB рассылает один `RGBColor` на **все** устройства — материнскую плату, кулеры и видеокарту. Типы из `exclude_devices` не трогаются.

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

В трее у часов появляется иконка: пауза, яркость, настройки, выход. Повторный запуск второй процесс не создаёт.

**Самый первый запуск:** если нет службы `WinRing0_1_2_0` или папки профиля OpenRGB, приложение **один раз** запросит права администратора и запустит `bin/OpenRGB/openrgb.exe --server --startminimized`. Дальше SDK поднимается без UAC. Уже открытый порт `127.0.0.1:6742` используется как есть.

Рядом со скриптом или с `ambilight.exe` при первом запуске создаётся `ambilight.json` (`fps`, `max_brightness`, `brightness`, `monitor`, `exclude_devices`, `hue_bins`, `on_exit`, `pause_when_locked`). Лог: `%LOCALAPPDATA%\AmbilightRGB\ambilight.log`.

### Структура

| Путь | Назначение |
| --- | --- |
| `ambilight.py` | Захват → корзина оттенка → сглаживание HSV → бродкаст OpenRGB |
| `ambilight.pyw` | Тот же вход без консоли |
| `start_ambilight.bat` | Запуск в один клик через `pythonw` |
| `ambilight.json` | Создаётся при первом запуске рядом с приложением |
| `bin/OpenRGB/` | Portable OpenRGB (`openrgb.exe` — скачивается отдельно) |
| `docs/` | Фото-пруфы |
| `requirements.txt` | `openrgb-python`, `mss`, `numpy`, `Pillow`, `pystray` |

### Лицензия

MIT — файл [LICENSE](LICENSE).
