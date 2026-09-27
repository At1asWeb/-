import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


# Корень проекта
BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем .env
load_dotenv(BASE_DIR / ".env")


def get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_int(name: str, default: int = 0) -> int:
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    return int(value)


def get_float(name: str, default: float = 0.0) -> float:
    value = os.getenv(name)

    if value is None or not value.strip():
        return default

    return float(value)


def get_admin_ids() -> list[int]:
    value = os.getenv("ADMIN_IDS", "").strip()

    if not value:
        return []

    return [
        int(admin_id.strip())
        for admin_id in value.split(",")
        if admin_id.strip()
    ]


@dataclass(frozen=True)
class Settings:
    # Telegram
    bot_token: str
    admin_ids: list[int]

    # Proxy
    proxy_enabled: bool
    proxy_host: str
    proxy_port: int
    proxy_username: str
    proxy_password: str

    # Banner
    banner_width_percent: int
    banner_height_percent: int
    banner_fit: str
    banner_top_offset_percent: int
    banner_opacity: float
    banner_loop: bool

    # Music
    music_volume_min: float
    music_volume_max: float

    # Limits
    temp_file_max_age_hours: int
    processing_timeout_seconds: int
    max_video_duration: int
    max_batch_size: int
    max_input_size_mb: int
    max_output_size_mb: int
    telegram_upload_limit_mb: int
    telegram_api_url: str

    # Качество видео
    video_crf: int
    video_preset: str
    audio_bitrate_kbps: int

    # Subtitles
    whisper_language: str

    # yt-dlp
    ytdlp_cookies_browser: str
    ytdlp_cookies_file: str

    # Paths
    base_dir: Path
    assets_dir: Path
    banners_dir: Path
    backgrounds_dir: Path
    music_dir: Path
    fonts_dir: Path
    outro_dir: Path
    models_dir: Path
    work_dir: Path
    input_dir: Path
    temp_dir: Path
    output_dir: Path
    data_dir: Path
    database_path: Path


settings = Settings(
    # Telegram
    bot_token=os.getenv("BOT_TOKEN", "").strip(),
    admin_ids=get_admin_ids(),

    # Proxy
    proxy_enabled=get_bool("PROXY_ENABLED", True),
    proxy_host=os.getenv("PROXY_HOST", "").strip(),
    proxy_port=get_int("PROXY_PORT", 0),
    proxy_username=os.getenv("PROXY_USERNAME", "").strip(),
    proxy_password=os.getenv("PROXY_PASSWORD", "").strip(),

    # Banner
    banner_width_percent=get_int("BANNER_WIDTH_PERCENT", 75),
    # 0 = высота подбирается автоматически по пропорциям баннера.
    banner_height_percent=get_int("BANNER_HEIGHT_PERCENT", 0),
    # fit — вписать без искажений, crop — заполнить с обрезкой краёв,
    # stretch — растянуть точно под заданный размер.
    banner_fit=os.getenv("BANNER_FIT", "fit").strip().lower() or "fit",
    banner_top_offset_percent=get_int("BANNER_TOP_OFFSET_PERCENT", 10),
    banner_opacity=get_float("BANNER_OPACITY", 0.95),
    banner_loop=get_bool("BANNER_LOOP", True),

    # Music
    music_volume_min=get_float("MUSIC_VOLUME_MIN", 0.01),
    music_volume_max=get_float("MUSIC_VOLUME_MAX", 0.03),

    # Limits
    temp_file_max_age_hours=get_int("TEMP_FILE_MAX_AGE_HOURS", 6),
    processing_timeout_seconds=get_int(
        "PROCESSING_TIMEOUT_SECONDS",
        1800,
    ),
    max_video_duration=get_int("MAX_VIDEO_DURATION", 300),
    # Сколько ссылок можно отправить одним списком.
    max_batch_size=get_int("MAX_BATCH_SIZE", 30),
    max_input_size_mb=get_int("MAX_INPUT_SIZE_MB", 200),
    max_output_size_mb=get_int("MAX_OUTPUT_SIZE_MB", 200),
    # Лимит Telegram Bot API на отправку файлов ботом (50 МБ).
    # Увеличивайте только при использовании локального Bot API сервера.
    # С локальным Bot API сервером лимит — 2000 МБ.
    telegram_upload_limit_mb=get_int(
        "TELEGRAM_UPLOAD_LIMIT_MB",
        2000 if os.getenv("TELEGRAM_API_URL", "").strip() else 50,
    ),
    telegram_api_url=os.getenv("TELEGRAM_API_URL", "").strip().rstrip("/"),

    # Качество видео: CRF меньше = лучше и тяжелее (17–18 — визуально
    # без потерь). Preset медленнее = лучше сжатие при том же качестве.
    video_crf=get_int("VIDEO_CRF", 17),
    video_preset=os.getenv("VIDEO_PRESET", "slow").strip() or "slow",
    audio_bitrate_kbps=get_int("AUDIO_BITRATE_KBPS", 256),

    # Subtitles
    whisper_language=os.getenv("WHISPER_LANGUAGE", "ru").strip() or "ru",

    # yt-dlp
    ytdlp_cookies_browser=os.getenv(
        "YTDLP_COOKIES_BROWSER",
        "chrome",
    ).strip(),
    ytdlp_cookies_file=os.getenv("YTDLP_COOKIES_FILE", "").strip(),

    # Paths
    base_dir=BASE_DIR,
    assets_dir=BASE_DIR / "assets",
    banners_dir=BASE_DIR / "assets" / "banners",
    backgrounds_dir=BASE_DIR / "assets" / "backgrounds",
    music_dir=BASE_DIR / "assets" / "music",
    # Шрифты для субтитров (TTF/OTF), доступны в шаблонах пользователей
    fonts_dir=BASE_DIR / "assets" / "fonts",
    # Картинка-концовка (3 сек в конце каждого видео)
    outro_dir=BASE_DIR / "assets" / "outro",
    models_dir=BASE_DIR / "assets" / "models",
    work_dir=BASE_DIR / "work",
    input_dir=BASE_DIR / "work" / "input",
    temp_dir=BASE_DIR / "work" / "temp",
    output_dir=BASE_DIR / "work" / "output",
    data_dir=BASE_DIR / "data",
    database_path=BASE_DIR / "data" / "app.db",
)