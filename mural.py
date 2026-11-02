from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse


TRUSTED_EMBED_HOSTS = {"www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com",
                       "www.youtube-nocookie.com", "youtube-nocookie.com"}
VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}
EXTERNAL_LINK_HOSTS = {"aguaviva.actsp.com.br"}
VIMEO_HASH_PATTERN = re.compile(r"^[A-Za-z0-9]{6,64}$")
YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,}$")
REQUIRED_COLUMNS = {"title", "description", "category", "poster", "provider"}


@dataclass(frozen=True)
class VideoItem:
    id: int
    title: str
    description: str
    category: str
    year: int
    duration: str
    rating: str
    poster: str
    banner: str
    video: str
    provider: str = "local"
    embed_url: str | None = None
    caption: str | None = None
    featured: bool = False
    open_on_select: bool = False
    external_url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_VIDEOS = (
    VideoItem(
        id=1,
        title="SindCON ERP",
        description="Demonstração da plataforma SindCON, solução digital para apoiar gestão, processos e organização operacional.",
        category="Sistema ERP",
        year=2026,
        duration="Demonstração",
        rating="Livre",
        poster="SindCON_ERP_App.png",
        banner="banner1.jpg",
        video="",
        provider="youtube",
        embed_url="https://www.youtube.com/embed/SD5lW53LIE4",
        featured=True,
    ),
    VideoItem(
        id=2,
        title="Soluções Digitais em Campo",
        description="Demonstração de como aplicações web e mobile ajudam equipes a coletar dados e acompanhar rotinas.",
        category="Tecnologia",
        year=2026,
        duration="3 min",
        rating="Livre",
        poster="App_Geomap_616x465.png",
        banner="banner.jpg",
        video="",
        provider="external",
        external_url="https://aguaviva.actsp.com.br/",
        open_on_select=True,
    ),
    VideoItem(
        id=3,
        title="Capacitações e Educação Corporativa",
        description="Conteúdo demonstrativo sobre treinamentos, onboarding e formação prática para equipes.",
        category="Capacitação",
        year=2026,
        duration="4 min",
        rating="Livre",
        poster="ACT-SP_Capacitacoes.png",
        banner="banner0.jpg",
        video="",
        provider="youtube",
        embed_url="https://www.youtube.com/embed/_LKoHd-cVJ8",
        open_on_select=True,
    ),
)


def list_videos(video_library_path: str | None = None, data_path: str | Path | None = None) -> list[VideoItem]:
    return load_video_items(data_path) if data_path else list(DEFAULT_VIDEOS)


def get_video_categories(videos: list[VideoItem] | tuple[VideoItem, ...]) -> list[str]:
    return sorted({video.category for video in videos if video.category})


def load_video_items(data_path: str | Path | None) -> list[VideoItem]:
    if not data_path:
        return list(DEFAULT_VIDEOS)

    path = Path(data_path)
    if not path.exists():
        return list(DEFAULT_VIDEOS)

    if path.suffix.lower() != ".csv":
        if path.suffix.lower() == ".json":
            return load_video_items_from_json(path)
        return list(DEFAULT_VIDEOS)

    return load_video_items_from_csv(path)


def load_video_items_from_csv(path: Path) -> list[VideoItem]:
    with path.open("r", encoding="utf-8-sig", newline="") as video_file:
        sample = video_file.read(2048)
        video_file.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;") if sample.strip() else csv.excel
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"
        reader = csv.DictReader(video_file, dialect=dialect)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
            return list(DEFAULT_VIDEOS)
        return rows_to_video_items(reader)


def load_video_items_from_json(path: Path) -> list[VideoItem]:
    with path.open(encoding="utf-8") as metadata_file:
        data = json.load(metadata_file)

    rows = []
    for item in data.get("videos", []):
        rows.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "description": item.get("description"),
                "category": item.get("category"),
                "year": item.get("year"),
                "duration": item.get("duration"),
                "rating": item.get("rating"),
                "poster": item.get("poster") or item.get("thumbnail") or "banner.jpg",
                "banner": item.get("banner") or item.get("backdrop") or item.get("thumbnail") or "banner.jpg",
                "video": item.get("video") or item.get("filename"),
                "provider": item.get("provider") or "local",
                "embed_url": item.get("embed_url") or item.get("url"),
                "caption": item.get("caption"),
                "featured": item.get("featured"),
                "open_on_select": item.get("open_on_select"),
                "external_url": item.get("external_url"),
            }
        )

    return rows_to_video_items(rows)


def rows_to_video_items(rows) -> list[VideoItem]:
    items = []
    for fallback_id, row in enumerate(rows, start=1):
        item = video_item_from_row(row, fallback_id=fallback_id)
        if item:
            items.append(item)
    return items or list(DEFAULT_VIDEOS)


def video_item_from_row(row: dict[str, str | None], fallback_id: int) -> VideoItem | None:
    provider = clean_text(row.get("provider")).lower() or "local"
    if provider not in {"local", "youtube", "vimeo", "embed", "external"}:
        return None

    title = clean_text(row.get("title"))
    description = clean_text(row.get("description"))
    category = clean_text(row.get("category"))
    poster = clean_static_file_name(row.get("poster"))
    banner = clean_static_file_name(row.get("banner")) or poster
    raw_video = clean_text(row.get("video"))
    video = clean_static_file_name(raw_video)
    caption = clean_static_file_name(row.get("caption")) or None
    external_url = normalize_external_url(row.get("external_url"))
    if provider == "external" and not external_url:
        return None
    embed_url = normalize_video_embed_url(row.get("embed_url") or row.get("url") or raw_video)
    detected_provider = "vimeo" if embed_url and "player.vimeo.com" in embed_url else "youtube"
    if provider == "embed" or (provider == "local" and embed_url and not video):
        provider = detected_provider

    if not title or not description or not category or not poster:
        return None
    if provider in {"youtube", "vimeo"} and (not embed_url or provider != detected_provider):
        return None
    if provider == "local" and not video:
        return None

    return VideoItem(
        id=clean_int(row.get("id"), fallback_id),
        title=title,
        description=description,
        category=category,
        year=clean_int(row.get("year"), 2026),
        duration=clean_text(row.get("duration")) or "Vídeo",
        rating=clean_text(row.get("rating")) or "Livre",
        poster=poster,
        banner=banner,
        video=video if provider == "local" else "",
        provider=provider,
        embed_url=embed_url if provider != "local" else None,
        caption=caption,
        featured=clean_bool(row.get("featured")),
        open_on_select=clean_bool(row.get("open_on_select")),
        external_url=external_url if provider == "external" else None,
    )


def mark_local_availability(items: list[VideoItem], video_library_path: str) -> list[VideoItem]:
    library = Path(video_library_path)
    if not library.exists():
        return items

    available = {path.name for path in library.glob("*.mp4")}
    return [
        item
        for item in items
        if item.provider != "local" or item.video in available
    ] or items


def normalize_external_url(value: str | None) -> str | None:
    """Allow HTTPS navigation only to explicitly approved mural sites."""
    url = clean_text(value)
    if not url or any(ord(char) < 32 for char in url) or "\\" in url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() not in EXTERNAL_LINK_HOSTS:
            return None
    except ValueError:
        return None
    return url


def normalize_video_embed_url(value: str | None) -> str | None:
    url = clean_text(value)
    if not url:
        return None

    if any(ord(char) < 32 for char in url) or "\\" in url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"https", "http"}:
        return None
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    if host == "youtu.be" and path:
        video_id = path.split("/")[0]
        return build_youtube_embed_url(video_id)

    if host in TRUSTED_EMBED_HOSTS:
        if path.startswith("embed/"):
            video_id = path.split("/", 1)[1].split("/")[0]
            return build_youtube_embed_url(video_id)
        if path == "watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            return build_youtube_embed_url(video_id)
        if path.startswith("shorts/"):
            video_id = path.split("/", 1)[1].split("/")[0]
            return build_youtube_embed_url(video_id)
        if path.startswith("live/"):
            return build_youtube_embed_url(path.split("/", 1)[1].split("/")[0])

    if host in VIMEO_HOSTS:
        match = re.fullmatch(r"(?:video/)?([1-9][0-9]{0,14})(?:/([A-Za-z0-9]{6,64}))?", path)
        if not match:
            return None
        video_id, path_hash = match.groups()
        hashes = parse_qs(parsed.query, keep_blank_values=True).get("h", [])
        if len(hashes) > 1:
            return None
        privacy_hash = hashes[0] if hashes else path_hash
        if privacy_hash is not None and not VIMEO_HASH_PATTERN.fullmatch(privacy_hash):
            return None
        embed_url = f"https://player.vimeo.com/video/{video_id}"
        return embed_url + ("?" + urlencode({"h": privacy_hash}) if privacy_hash else "")

    return None


def build_youtube_embed_url(video_id: str) -> str | None:
    if not YOUTUBE_ID_PATTERN.fullmatch(video_id):
        return None
    return f"https://www.youtube.com/embed/{video_id}"


def clean_static_file_name(value: str | None) -> str:
    file_name = clean_text(value)
    if not file_name:
        return ""

    safe_name = Path(file_name).name
    if safe_name != file_name or safe_name.startswith("."):
        return ""
    return safe_name


def clean_text(value: str | None) -> str:
    return (value or "").strip()


def clean_int(value: str | None, default: int) -> int:
    try:
        return int(float(clean_text(value)))
    except (TypeError, ValueError):
        return default


def clean_bool(value: str | None) -> bool:
    if isinstance(value, bool):
        return value
    return clean_text(value).lower() in {"1", "true", "yes", "sim", "destaque"}
