# Xưởng phim mẫu (local)

Ứng dụng Windows chạy trên máy cá nhân để quản lý ảnh/video mẫu, phân loại tài nguyên, viết kịch bản bằng Claude và dựng video MP4.

## Tính năng

- Nạp ảnh và video; video được lấy khung hình mẫu, đo thời lượng và phiên âm local bằng faster-whisper.
- Claude Vision đề xuất mô tả, phong cách, tags và loại tài nguyên: `character`, `background`, `prop`.
- Tùy chọn tách nền ảnh bằng rembg; ảnh PNG trong suốt hiện trên nền caro.
- Gợi ý kịch bản theo thư viện và nhịp video mẫu.
- Edge TTS đọc lời thoại; FFmpeg dựng MP4 ngang/dọc có phụ đề.
- Dữ liệu dự án lưu local trong thư mục `data/`.

## Cài đặt Windows

1. Cài Python 3.11 x64 và bật **Add Python to PATH**.
2. Cài FFmpeg, thêm `ffmpeg` và `ffprobe` vào PATH.
3. Tải ZIP từ GitHub (**Code → Download ZIP**) và giải nén.
4. Chạy `setup_windows.bat` (lần đầu có thể mất một lúc do tải các thư viện AI).
5. Mở `.env`, điền API key Anthropic của bạn vào `ANTHROPIC_API_KEY`.
6. Chạy `start_windows.bat`; trình duyệt mở tại http://127.0.0.1:8000.

Whisper tải model về máy trong lần đầu phân tích video. Muốn giảm dung lượng/thời gian tải, sửa `WHISPER_MODEL=base` trong `.env`; model lớn thường cần RAM nhiều hơn. Tách nền/Whisper chạy local, còn phân tích ảnh và viết kịch bản dùng Anthropic API nên cần API key và kết nối Internet.

## Lưu ý

- Dự án là ứng dụng local, chưa đóng gói thành EXE độc lập; cần cài Python, FFmpeg và dependencies như trên.
- `rembg`/Whisper tải model AI lần đầu. Tốc độ phụ thuộc CPU/RAM; GPU không bắt buộc.
- Chỉ dùng media mà bạn có quyền sử dụng. Video mẫu được phân tích để tham khảo nhịp, không nên sao chép nội dung.
- Không đưa API key vào mã nguồn hoặc chia sẻ file `.env`.

## Khởi chạy thủ công

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Điền API key trong .env; cài FFmpeg rồi chạy:
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```
