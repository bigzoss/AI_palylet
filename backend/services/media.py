import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from ..config import safe_path, settings
from ..db import Media, uid


def compose_character_sheet(views, target):
    """Portrait then front/side/back; all source views are retained without cropping."""
    canvas = Image.new("RGB", (2048, 1024), "#eeeeee")
    widths = [640, 469, 469, 470]
    left = 0
    for key, width in zip(["portrait", "front", "side", "back"], widths, strict=True):
        with Image.open(views[key]) as source:
            frame = ImageOps.exif_transpose(source).convert("RGB")
            if key == "portrait":
                frame = ImageOps.fit(frame, (width, 1024), centering=(0.5, 0.4))
            else:
                # Crop horizontal margins only for the combined card; original view remains intact.
                frame = ImageOps.fit(frame, (width, 1024))
            canvas.paste(frame, (left, 0))
            left += width
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, "PNG")


def ffmpeg():
    if settings.ffmpeg_path:
        return settings.ffmpeg_path
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def command(args, timeout=120):
    result = subprocess.run(
        args, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    if result.returncode:
        raise ValueError("媒体解码失败，请检查文件编码和完整性")
    return result


def probe(path: Path):
    binary = settings.ffprobe_path or shutil.which("ffprobe")
    if binary:
        result = command([binary, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
        info = json.loads(result.stdout)
        video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
        if not video:
            raise ValueError("文件中没有视频轨道")
        return {
            "duration_ms": int(float(info["format"]["duration"]) * 1000),
            "width": video["width"],
            "height": video["height"],
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        }
    # Bundled FFmpeg fallback for machines without a system FFprobe.
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    report = result.stderr.decode("utf-8", errors="replace")
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", report)
    size = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", report)
    if not duration or not size:
        raise ValueError("无法识别视频信息")
    h, m, sec = map(float, duration.groups())
    return {
        "duration_ms": round((h * 3600 + m * 60 + sec) * 1000),
        "width": int(size[1]),
        "height": int(size[2]),
        "has_audio": "Audio:" in report,
    }


def register(db, project_id, path: Path, kind, name=None, info=None):
    record = Media(
        id=uid("med_"),
        project_id=project_id,
        kind=kind,
        path=path.resolve().relative_to(settings.storage).as_posix(),
        name=name or path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        info=info or {},
    )
    db.add(record)
    db.flush()
    return record


def verify_image(path):
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("图片文件无效或尺寸过大") from exc


def parse_srt(text, duration_ms):
    pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")

    def timestamp(value):
        h, m, s, ms = map(int, pattern.search(value).groups())
        return ((h * 60 + m) * 60 + s) * 1000 + ms

    output = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = block.splitlines()
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if index is None:
            continue
        left, right = lines[index].split("-->", 1)
        if not pattern.search(left) or not pattern.search(right):
            raise ValueError("字幕时间格式无效")
        start, end = timestamp(left), min(timestamp(right), duration_ms)
        if not 0 <= start < end:
            raise ValueError("字幕时间范围无效或超出视频")
        output.append(
            {
                "start_ms": start,
                "end_ms": end,
                "text": " ".join(lines[index + 1 :]),
                "speaker": "unknown",
                "basis": "subtitle",
            }
        )
    if not output:
        raise ValueError("字幕文件没有有效片段")
    return output


def prepare(db, record, check_cancel):
    from scenedetect import ContentDetector, detect

    source = safe_path(record.path)
    directory = safe_path(f"{record.project_id}/processed/{record.sha256[:16]}")
    directory.mkdir(parents=True, exist_ok=True)
    preview = directory / "preview.mp4"
    if not preview.exists():
        temporary_preview = directory / "preview.part.mp4"
        command(
            [
                ffmpeg(),
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "25",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temporary_preview),
            ],
            timeout=300,
        )
        temporary_preview.replace(preview)
    check_cancel()
    scenes = detect(str(preview), ContentDetector(threshold=27), start_in_scene=True)
    duration = record.info["duration_ms"]
    ranges = [(round(a.seconds * 1000), min(duration, round(b.seconds * 1000))) for a, b in scenes]
    if not ranges:
        ranges = [(0, duration)]
    # Long takes are sampled without inventing additional cut boundaries.
    if len(ranges) > settings.max_frames:
        raise ValueError("候选镜头超过抽帧预算，请截取更短片段后重试")
    sampled = []
    budget = settings.max_frames - len(ranges)
    for index, (start, end) in enumerate(ranges):
        check_cancel()
        points = [(start + end) // 2]
        extras = min(max(0, (end - start) // 10000), budget)
        budget -= extras
        points.extend(start + (end - start) * (j + 1) // (extras + 2) for j in range(extras))
        frames = []
        for frame_index, point in enumerate(sorted(set(points))):
            path = directory / f"shot_{index:04}_{frame_index}_{point}.jpg"
            if not path.exists():
                command(
                    [
                        ffmpeg(),
                        "-y",
                        "-ss",
                        str(point / 1000),
                        "-i",
                        str(preview),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=768:-2",
                        "-q:v",
                        "3",
                        str(path),
                    ]
                )
            frames.append({"path": path.relative_to(settings.storage).as_posix(), "timestamp_ms": point})
        sampled.append({"id": f"SRC_SH_{index + 1:03}", "start_ms": start, "end_ms": end, "frames": frames})
    preview_record = register(db, record.project_id, preview, "preview", info=record.info)
    audio = directory / "audio.mp3"
    if record.info["has_audio"]:
        command(
            [ffmpeg(), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(audio)]
        )
    return {
        "shots": sampled,
        "preview_media_id": preview_record.id,
        "audio_path": audio.relative_to(settings.storage).as_posix() if audio.exists() else None,
    }
