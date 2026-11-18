"""Local animation studio: media library, Claude analysis, script writing, and MP4 rendering.
Run with: uvicorn app:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

import anthropic
import edge_tts
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DATA = BASE / "data"
LIB, OUT, TMP = DATA / "library", DATA / "output", DATA / "tmp"
for folder in (LIB, OUT, TMP):
    folder.mkdir(parents=True, exist_ok=True)
LIB_JSON, STYLE_JSON, TEMPLATES_JSON = DATA / "library.json", DATA / "style.json", DATA / "templates.json"
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
SIZES = {"16:9": (1280, 720), "9:16": (720, 1280)}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VID_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
MAX_UPLOAD = 100 * 1024 * 1024
FONTS = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf"]

app = FastAPI(title="Xưởng phim mẫu", version="1.0.0")
_client = None
_whisper_model = None
_rembg_session = None


def claude():
    global _client
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "Chưa cấu hình ANTHROPIC_API_KEY trong file .env")
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ask(content, system, max_tokens=2000):
    try:
        response = claude().messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                                             messages=[{"role": "user", "content": content}])
        return "".join(block.text for block in response.content if block.type == "text")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Lỗi gọi Claude: {exc}") from exc


def parse_json(text):
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise HTTPException(502, "Claude không trả về JSON hợp lệ")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise HTTPException(502, "JSON Claude trả về không hợp lệ") from exc


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def img_block(path: Path):
    with Image.open(path) as image:
        im = image.convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                          "data": base64.b64encode(buf.getvalue()).decode("ascii")}}


def describe(path: Path):
    prompt = ('Phân tích tài nguyên hình ảnh cho thư viện dựng phim. Chọn type đúng trong '
              'character, background, prop. Chỉ trả JSON theo mẫu: '
              '{"description":"mô tả ngắn","style":"phong cách","type":"character|background|prop",'
              '"tags":["tag1","tag2"]}.')
    data = parse_json(ask([img_block(path), {"type": "text", "text": prompt}],
                          "Bạn là trợ lý phân loại hình ảnh cho xưởng phim. Trả lời tiếng Việt.", 600))
    kind = data.get("type", "prop")
    data["type"] = kind if kind in {"character", "background", "prop"} else "prop"
    data["tags"] = [str(tag)[:40] for tag in data.get("tags", [])[:20]]
    data["description"] = str(data.get("description", ""))[:500]
    data["style"] = str(data.get("style", ""))[:300]
    return data


def run(cmd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except FileNotFoundError as exc:
        raise HTTPException(503, "Không tìm thấy FFmpeg/ffprobe. Hãy cài FFmpeg và thêm vào PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "FFmpeg chạy quá thời gian cho phép") from exc
    if result.returncode:
        raise HTTPException(500, "FFmpeg lỗi: " + result.stderr[-1200:])
    return result.stdout.strip()


def remove_background(source: Path, dest: Path):
    global _rembg_session
    try:
        from rembg import new_session, remove
        if _rembg_session is None:
            _rembg_session = new_session()
        dest.write_bytes(remove(source.read_bytes(), session=_rembg_session))
    except ImportError as exc:
        raise HTTPException(503, "Tách nền chưa cài. Chạy setup_windows.bat để cài rembg.") from exc
    except Exception as exc:
        raise HTTPException(500, f"Không tách được nền: {exc}") from exc


def transcribe_video(video: Path):
    global _whisper_model
    try:
        from faster_whisper import WhisperModel
        if _whisper_model is None:
            model_size = os.getenv("WHISPER_MODEL", "small")
            _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = _whisper_model.transcribe(str(video), vad_filter=True)
        transcript = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                      for s in segments]
        return transcript, info.language
    except ImportError as exc:
        raise HTTPException(503, "Phân tích video chưa cài faster-whisper. Chạy setup_windows.bat.") from exc
    except Exception as exc:
        raise HTTPException(500, f"Whisper không phân tích được video: {exc}") from exc


def safe_id(value: str):
    if not re.fullmatch(r"[a-f0-9]{8,32}(?:_\d{2})?", value):
        raise HTTPException(400, "ID tài nguyên không hợp lệ")
    return value


@app.get("/api/health")
def health():
    return {"ok": True, "claude_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
            "ffmpeg": subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0}


@app.get("/api/library")
def get_library():
    return {"items": load(LIB_JSON, []), "style": load(STYLE_JSON, {}).get("guide", ""),
            "templates": load(TEMPLATES_JSON, [])}


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), remove_background_enabled: bool = Form(False)):
    added, templates = [], []
    for upload_file in files:
        ext = Path(upload_file.filename or "").suffix.lower()
        content = await upload_file.read(MAX_UPLOAD + 1)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "Mỗi tệp tải lên tối đa 100 MB")
        uid = uuid.uuid4().hex[:12]
        if ext in IMG_EXT:
            raw = LIB / f"{uid}{ext}"
            raw.write_bytes(content)
            target = raw
            if remove_background_enabled:
                target = LIB / f"{uid}_transparent.png"
                remove_background(raw, target)
            info = describe(target)
            item = {"id": target.stem, "file": target.name, **info,
                    "transparent": remove_background_enabled, "source": "image"}
            added.append(item)
        elif ext in VID_EXT:
            src = TMP / f"{uid}{ext}"
            src.write_bytes(content)
            duration = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "default=nw=1:nk=1", str(src)]))
            samples_dir = TMP / uid
            samples_dir.mkdir()
            run(["ffmpeg", "-y", "-i", str(src), "-vf", "fps=1/3,scale=1280:-2",
                 "-frames:v", "12", str(samples_dir / "frame_%02d.jpg")])
            transcript, language = transcribe_video(src)
            frames = sorted(samples_dir.glob("frame_*.jpg"))
            for index, frame in enumerate(frames):
                dest = LIB / f"{uid}_{index + 1:02d}.jpg"
                dest.write_bytes(frame.read_bytes())
                info = describe(dest)
                item = {"id": dest.stem, "file": dest.name, **info,
                        "source": "video", "source_video": uid}
                added.append(item)
            scene_count = max(1, len(frames))
            template = {"id": uid, "filename": Path(upload_file.filename or "video").name,
                        "duration_seconds": round(duration, 2), "sampled_frames": len(frames),
                        "approx_scene_seconds": round(duration / scene_count, 2),
                        "transcript": transcript, "language": language}
            templates.append(template)
            saved_templates = load(TEMPLATES_JSON, [])
            saved_templates.append(template)
            save(TEMPLATES_JSON, saved_templates)
            src.unlink(missing_ok=True)
            for frame in frames:
                frame.unlink(missing_ok=True)
            samples_dir.rmdir()
        else:
            raise HTTPException(400, f"Định dạng không hỗ trợ: {ext}")
    library = load(LIB_JSON, [])
    library.extend(added)
    save(LIB_JSON, library)
    return {"added": added, "templates": templates}


class LibraryUpdate(BaseModel):
    type: str | None = None
    tags: list[str] | None = None


@app.patch("/api/library/{item_id}")
def update_item(item_id: str, req: LibraryUpdate):
    safe_id(item_id)
    library = load(LIB_JSON, [])
    item = next((entry for entry in library if entry["id"] == item_id), None)
    if not item:
        raise HTTPException(404, "Không tìm thấy tài nguyên")
    if req.type is not None:
        if req.type not in {"character", "background", "prop"}:
            raise HTTPException(400, "Loại tài nguyên không hợp lệ")
        item["type"] = req.type
    if req.tags is not None:
        item["tags"] = [str(tag).strip()[:40] for tag in req.tags if str(tag).strip()][:20]
    save(LIB_JSON, library)
    return item


@app.delete("/api/library/{item_id}")
def delete_item(item_id: str):
    safe_id(item_id)
    library = load(LIB_JSON, [])
    removed = [item for item in library if item["id"] == item_id]
    save(LIB_JSON, [item for item in library if item["id"] != item_id])
    for item in removed:
        (LIB / item["file"]).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/style")
def build_style():
    library = load(LIB_JSON, [])
    if not library:
        raise HTTPException(400, "Hãy nạp ảnh mẫu trước")
    content = [img_block(LIB / item["file"]) for item in library[:6]]
    content.append({"type": "text", "text": "Tổng hợp phong cách chung (bảng màu, nét vẽ, nhân vật, bố cục, tông cảm xúc), tối đa 120 từ."})
    guide = ask(content, "Bạn là art director phim hoạt hình. Trả lời tiếng Việt, súc tích.", 600)
    save(STYLE_JSON, {"guide": guide})
    return {"guide": guide}


class ScriptReq(BaseModel):
    idea: str = Field(min_length=1, max_length=3000)
    scenes: int = Field(default=6, ge=2, le=20)
    language: str = "Tiếng Việt"


@app.post("/api/script")
def make_script(req: ScriptReq):
    library = load(LIB_JSON, [])
    if not library:
        raise HTTPException(400, "Hãy nạp ảnh mẫu trước")
    catalog = [{"id": i["id"], "description": i.get("description"), "type": i.get("type"),
                "tags": i.get("tags", [])} for i in library]
    guide = load(STYLE_JSON, {}).get("guide", "")
    templates = [{"duration_seconds": t["duration_seconds"],
                  "approx_scene_seconds": t["approx_scene_seconds"], "transcript": t["transcript"][:30]}
                 for t in load(TEMPLATES_JSON, [])[-3:]]
    prompt = (f"Ý tưởng: {req.idea}\nSố cảnh: {req.scenes}\nNgôn ngữ: {req.language}\n"
              f"Phong cách: {guide}\nNhịp/template video tham khảo: {json.dumps(templates, ensure_ascii=False)}\n"
              f"Thư viện: {json.dumps(catalog, ensure_ascii=False)}\n"
              "Tạo kịch bản mới, không sao chép lời thoại/nội dung mẫu. Chọn image_id hợp lý; ưu tiên background cho bối cảnh, "
              "character cho nhân vật, prop cho đồ vật. Chỉ trả JSON: {\"title\":\"...\",\"scenes\":["
              "{\"image_id\":\"...\",\"caption\":\"phụ đề ngắn\",\"narration\":\"1-2 câu\"}]}")
    data = parse_json(ask(prompt, "Bạn là biên kịch phim ngắn, cuốn hút và chính xác.", 3000))
    ids = {i["id"] for i in library}
    for index, scene in enumerate(data.get("scenes", [])):
        if scene.get("image_id") not in ids:
            scene["image_id"] = library[index % len(library)]["id"]
    return data


class Scene(BaseModel):
    image_id: str
    caption: str = ""
    narration: str


class RenderReq(BaseModel):
    title: str = "phim"
    scenes: list[Scene] = Field(min_length=1, max_length=50)
    aspect: str = "16:9"
    voice: str = "vi-VN-HoaiMyNeural"


def font(size):
    for candidate in FONTS:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def background(src, size, out):
    width, height = size
    with Image.open(src) as source:
        image = source.convert("RGB")
        ratio = max(width / image.width, height / image.height)
        image = image.resize((int(image.width * ratio) + 1, int(image.height * ratio) + 1))
        left, top = (image.width - width) // 2, (image.height - height) // 2
        image.crop((left, top, left + width, top + height)).save(out)


def caption_png(text, size, out):
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if text.strip():
        draw, face = ImageDraw.Draw(layer), font(max(18, width // 24))
        lines, current = [], ""
        for word in text.split():
            test = (current + " " + word).strip()
            if draw.textlength(test, font=face) > width * 0.86 and current:
                lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)
        line_height = face.size + 8
        y = height - int(height * 0.08) - line_height * len(lines)
        for line in lines:
            x = (width - draw.textlength(line, font=face)) / 2
            draw.text((x, y), line, font=face, fill="white", stroke_width=4, stroke_fill="black")
            y += line_height
    layer.save(out)


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", str(path)]))


@app.post("/api/render")
def render(req: RenderReq):
    if req.aspect not in SIZES:
        raise HTTPException(400, "Khổ hình chỉ hỗ trợ 16:9 hoặc 9:16")
    size = SIZES[req.aspect]
    library = {item["id"]: item for item in load(LIB_JSON, [])}
    job = TMP / uuid.uuid4().hex[:12]
    job.mkdir()
    clips = []
    for index, scene in enumerate(req.scenes):
        item = library.get(scene.image_id)
        if not item:
            raise HTTPException(400, f"Không thấy ảnh {scene.image_id}")
        bg, cap = job / f"bg{index}.png", job / f"cap{index}.png"
        mp3, clip = job / f"a{index}.mp3", job / f"c{index}.mp4"
        background(LIB / item["file"], size, bg)
        caption_png(scene.caption, size, cap)
        try:
            asyncio.run(edge_tts.Communicate(scene.narration, req.voice).save(str(mp3)))
        except Exception as exc:
            raise HTTPException(502, f"Không tạo được giọng đọc: {exc}") from exc
        seconds = duration(mp3) + 0.5
        frames = max(1, int(seconds * 25))
        width, height = size
        filter_complex = (f"[0:v]scale={width * 2}:{height * 2},zoompan=z='min(zoom+0.0007,1.2)':"
                          f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=25[bg];"
                          "[bg][1:v]overlay=0:0,format=yuv420p[v]")
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(bg), "-i", str(cap), "-i", str(mp3),
             "-filter_complex", filter_complex, "-map", "[v]", "-map", "2:a", "-af", "apad",
             "-t", f"{seconds:.2f}", "-r", "25", "-c:v", "libx264", "-c:a", "aac",
             "-ar", "44100", "-ac", "2", str(clip)])
        clips.append(clip)
    concat_list = job / "list.txt"
    concat_list.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips), encoding="utf-8")
    title = re.sub(r"[^\w-]+", "_", req.title, flags=re.UNICODE).strip("_")[:80] or "phim"
    final = OUT / f"{title}_{uuid.uuid4().hex[:6]}.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(final)])
    return {"url": f"/files/output/{final.name}"}


app.mount("/files/library", StaticFiles(directory=LIB), name="library-files")
app.mount("/files/output", StaticFiles(directory=OUT), name="output-files")


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
