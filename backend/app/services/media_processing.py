"""Media validation and rendition pipeline.

Steps for every upload:

1. Detect the real file type from magic bytes (the client-supplied name and
   content type are not trusted) and enforce size limits.
2. Malware scan (``app.services.scanner``).
3. Extract technical metadata (Pillow for images, ffprobe for video).
4. Store the untouched original in the **private** bucket.
5. Generate watermarked, metadata-stripped previews in the **public** bucket:
   a large preview and a thumbnail for photos; a poster frame, thumbnail and
   low-resolution watermarked MP4 for video (FFmpeg).
6. Compute checksums for duplicate detection.

The module is deliberately self-contained so it can move to a dedicated worker
service (e.g. a Railway worker consuming a Redis queue) without changes.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.core.config import get_settings
from app.models import FileKind, MediaType, Orientation

log = logging.getLogger("media")

Image.MAX_IMAGE_PIXELS = 400_000_000  # guard against decompression bombs

IMAGE_FORMATS = {"jpeg": "image/jpeg", "png": "image/png", "tiff": "image/tiff", "webp": "image/webp"}
VIDEO_FORMATS = {"mp4": "video/mp4", "mov": "video/quicktime"}


class MediaValidationError(ValueError):
    pass


@dataclass
class DetectedType:
    media_type: MediaType
    file_format: str
    content_type: str


def detect_type(head: bytes) -> DetectedType:
    if head.startswith(b"\xff\xd8\xff"):
        return DetectedType(MediaType.photo, "jpeg", IMAGE_FORMATS["jpeg"])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return DetectedType(MediaType.photo, "png", IMAGE_FORMATS["png"])
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return DetectedType(MediaType.photo, "tiff", IMAGE_FORMATS["tiff"])
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return DetectedType(MediaType.photo, "webp", IMAGE_FORMATS["webp"])
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand == b"qt  ":
            return DetectedType(MediaType.video, "mov", VIDEO_FORMATS["mov"])
        return DetectedType(MediaType.video, "mp4", VIDEO_FORMATS["mp4"])
    if head[4:8] in (b"moov", b"wide", b"mdat", b"free"):
        return DetectedType(MediaType.video, "mov", VIDEO_FORMATS["mov"])
    raise MediaValidationError("Unsupported file type. Upload JPEG, PNG, TIFF, WebP, MP4 or MOV.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolution_label(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    long_edge = max(width, height)
    if long_edge >= 7680:
        return "8K"
    if long_edge >= 3840:
        return "4K"
    if long_edge >= 1280:
        return "HD"
    return "SD"


def orientation_of(width: int | None, height: int | None) -> Orientation | None:
    if not width or not height:
        return None
    if abs(width - height) <= max(width, height) * 0.02:
        return Orientation.square
    return Orientation.horizontal if width > height else Orientation.vertical


def average_hash(img: Image.Image) -> str:
    """64-bit perceptual (average) hash used to flag near-duplicate photos."""
    small = img.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return f"{int(bits, 2):016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


# --- Watermarking ---------------------------------------------------------------

def _font(size: int) -> ImageFont.ImageFont:
    for candidate in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def watermark_overlay(width: int, height: int, text: str) -> Image.Image:
    """Transparent RGBA layer with a tiled diagonal watermark."""
    font_size = max(12, min(width, height) // 20)
    font = _font(font_size)
    diag = int((width**2 + height**2) ** 0.5)
    tile = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    step_x, step_y = tw + font_size * 2, th + font_size * 3
    for row, y in enumerate(range(0, diag, step_y)):
        offset = (step_x // 2) * (row % 2)
        for x in range(-step_x, diag, step_x):
            draw.text((x + offset, y), text, font=font, fill=(255, 255, 255, 70))
    tile = tile.rotate(30, resample=Image.Resampling.BICUBIC)
    left, top = (diag - width) // 2, (diag - height) // 2
    return tile.crop((left, top, left + width, top + height))


def watermark_image(img: Image.Image, max_edge: int, text: str) -> bytes:
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    layer = watermark_overlay(img.width, img.height, text)
    composed = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    buf = io.BytesIO()
    composed.save(buf, "JPEG", quality=82, optimize=True, progressive=True)  # no EXIF copied
    return buf.getvalue()


# --- Pipeline --------------------------------------------------------------------

@dataclass
class Rendition:
    kind: FileKind
    data: bytes | None
    path: Path | None
    content_type: str
    width: int | None
    height: int | None


@dataclass
class ProcessedMedia:
    width: int | None
    height: int | None
    duration_seconds: float | None
    frame_rate: float | None
    perceptual_hash: str | None
    renditions: list[Rendition]


def process_image(path: Path, watermark_text: str) -> ProcessedMedia:
    settings = get_settings()
    try:
        with Image.open(path) as probe:
            probe.verify()
        with Image.open(path) as img:
            img.load()
            upright = ImageOps.exif_transpose(img)
            width, height = upright.size
            phash = average_hash(upright)
            preview = watermark_image(upright, settings.preview_max_edge_px, watermark_text)
            thumb = watermark_image(upright, settings.thumbnail_max_edge_px, watermark_text)
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise MediaValidationError(f"Image could not be decoded: {exc}") from exc

    def dims(data: bytes) -> tuple[int, int]:
        with Image.open(io.BytesIO(data)) as im:
            return im.size

    pw, ph = dims(preview)
    tw, th = dims(thumb)
    return ProcessedMedia(
        width=width,
        height=height,
        duration_seconds=None,
        frame_rate=None,
        perceptual_hash=phash,
        renditions=[
            Rendition(FileKind.preview, preview, None, "image/jpeg", pw, ph),
            Rendition(FileKind.thumbnail, thumb, None, "image/jpeg", tw, th),
        ],
    )


def probe_video(path: Path) -> dict:
    settings = get_settings()
    cmd = [
        settings.ffprobe_binary, "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaValidationError("Video could not be read (ffprobe failed).") from exc
    data = json.loads(out)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise MediaValidationError("No video stream found.")
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    rotation = 0
    for side in video.get("side_data_list", []) or []:
        rotation = int(side.get("rotation", 0) or 0)
    if abs(rotation) in (90, 270):
        width, height = height, width
    num, _, den = (video.get("avg_frame_rate") or "0/1").partition("/")
    fps = round(float(num) / float(den), 3) if den and float(den) else None
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0) or None
    return {"width": width, "height": height, "fps": fps, "duration": duration}


def process_video(path: Path, watermark_text: str, workdir: Path) -> ProcessedMedia:
    settings = get_settings()
    info = probe_video(path)
    seek = "1" if (info["duration"] or 0) > 2 else "0"
    poster_raw = workdir / "poster.png"
    preview_mp4 = workdir / "preview.mp4"
    wm_png = workdir / "wm.png"

    _ffmpeg(["-ss", seek, "-i", str(path), "-frames:v", "1", str(poster_raw)])
    with Image.open(poster_raw) as frame:
        frame.load()
        poster = watermark_image(frame, settings.preview_max_edge_px, watermark_text)
        thumb = watermark_image(frame, settings.thumbnail_max_edge_px, watermark_text)
        phash = average_hash(frame)

    # Low-resolution (max 960 px wide), 30-second, silent, watermarked preview.
    target_w = min(960, info["width"] or 960)
    target_w -= target_w % 2
    target_h = int(round((info["height"] or 540) * target_w / max(info["width"] or 960, 1)))
    target_h -= target_h % 2
    watermark_overlay(target_w, target_h, watermark_text).save(wm_png)
    _ffmpeg([
        "-i", str(path), "-i", str(wm_png), "-t", "30", "-an",
        "-filter_complex", f"[0:v]scale={target_w}:{target_h},setsar=1[v];[v][1:v]overlay=0:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(preview_mp4),
    ])

    def dims(data: bytes) -> tuple[int, int]:
        with Image.open(io.BytesIO(data)) as im:
            return im.size

    pw, ph = dims(poster)
    tw, th = dims(thumb)
    return ProcessedMedia(
        width=info["width"],
        height=info["height"],
        duration_seconds=info["duration"],
        frame_rate=info["fps"],
        perceptual_hash=phash,
        renditions=[
            Rendition(FileKind.poster, poster, None, "image/jpeg", pw, ph),
            Rendition(FileKind.thumbnail, thumb, None, "image/jpeg", tw, th),
            Rendition(FileKind.preview, None, preview_mp4, "video/mp4", target_w, target_h),
        ],
    )


def _ffmpeg(args: list[str]) -> None:
    cmd = [get_settings().ffmpeg_binary, "-y", "-v", "error", *args]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=1800)
    except subprocess.CalledProcessError as exc:
        raise MediaValidationError(f"FFmpeg failed: {exc.stderr.decode(errors='replace')[-500:]}") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaValidationError("FFmpeg is not available or timed out.") from exc


def storage_key(asset_id: uuid.UUID, kind: FileKind, ext: str) -> str:
    # Originals get an unguessable prefix in addition to living in the private bucket.
    prefix = uuid.uuid4().hex if kind is FileKind.original else "r"
    return f"assets/{asset_id}/{prefix}/{kind.value}.{ext}"


def new_workdir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="media-")
