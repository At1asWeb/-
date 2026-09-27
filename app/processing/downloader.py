from pathlib import Path

import yt_dlp

from app.config import settings


class DownloadError(RuntimeError):
    """Ошибка, текст которой можно показать пользователю."""


def download_video(url: str, output_dir: Path) -> Path:
    """
    Скачивает видео в output_dir/source.mp4.

    Проверяет длительность и размер по лимитам из .env.
    Если cookies браузера недоступны — повторяет без них.
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    for old_file in output_dir.glob("source.*"):
        old_file.unlink(missing_ok=True)

    cookie_options = _cookie_options()

    try:
        return _download(url, output_dir, cookie_options)

    except DownloadError:
        raise

    except Exception as error:
        if not cookie_options:
            raise

        print(
            "Скачивание с cookies не удалось "
            f"({type(error).__name__}: {error}). Пробую без cookies."
        )

        return _download(url, output_dir, {})


def _download(url: str, output_dir: Path, extra_options: dict) -> Path:
    max_bytes = settings.max_input_size_mb * 1024 * 1024

    options = {
        "outtmpl": str(output_dir / "source.%(ext)s"),
        # Лучшие отдельные видео- и аудиопотоки. Раньше выбирался только MP4
        # (H.264) — у YouTube он заметно хуже VP9 при том же разрешении.
        "format": "bv*+ba/b",
        "format_sort": [
            "res:2160",      # максимальное разрешение (до 4K)
            "fps",           # 60 fps лучше 30
            "hdr:SDR",       # SDR: HDR после перекодирования выглядит блёкло
            "vcodec:vp9",    # VP9 > H.265 > H.264; AV1 — только если нет другого
            "acodec",        # лучший звук (Opus/AAC)
            "vbr",
        ],
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "proxy": _build_proxy(),
        "socket_timeout": 30,
        "retries": 3,
        **extra_options,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)

        if info is None:
            raise DownloadError("Не удалось получить информацию о видео.")

        if info.get("_type") == "playlist":
            raise DownloadError("Ссылка ведёт на плейлист, а не на видео.")

        duration = info.get("duration") or 0

        if duration and duration > settings.max_video_duration:
            raise DownloadError(
                f"Видео слишком длинное: {int(duration)} сек. "
                f"Максимум — {settings.max_video_duration} сек."
            )

        expected_size = info.get("filesize") or info.get("filesize_approx") or 0

        if expected_size and expected_size > max_bytes:
            raise DownloadError(
                f"Видео слишком большое. "
                f"Максимум — {settings.max_input_size_mb} MB."
            )

        ydl.process_info(info)

    result_file = output_dir / "source.mp4"

    if not result_file.exists():
        candidates = sorted(output_dir.glob("source.*"))

        if not candidates:
            raise FileNotFoundError("Видео скачано, но файл не найден.")

        candidates[0].replace(result_file)

    if result_file.stat().st_size == 0:
        raise RuntimeError("Скачанный видеофайл пустой.")

    if result_file.stat().st_size > max_bytes:
        result_file.unlink(missing_ok=True)
        raise DownloadError(
            f"Видео слишком большое. "
            f"Максимум — {settings.max_input_size_mb} MB."
        )

    return result_file


def _cookie_options() -> dict:
    if settings.ytdlp_cookies_file:
        cookies_file = Path(settings.ytdlp_cookies_file)

        if not cookies_file.is_absolute():
            cookies_file = settings.base_dir / cookies_file

        if cookies_file.exists():
            return {"cookiefile": str(cookies_file)}

        print(f"Файл cookies не найден: {cookies_file}")

    if settings.ytdlp_cookies_browser:
        return {"cookiesfrombrowser": (settings.ytdlp_cookies_browser,)}

    return {}


def _build_proxy() -> str | None:
    if not settings.proxy_enabled:
        return None

    if not settings.proxy_host or not settings.proxy_port:
        return None

    if settings.proxy_username and settings.proxy_password:
        return (
            f"socks5://"
            f"{settings.proxy_username}:"
            f"{settings.proxy_password}@"
            f"{settings.proxy_host}:"
            f"{settings.proxy_port}"
        )

    return f"socks5://{settings.proxy_host}:{settings.proxy_port}"
