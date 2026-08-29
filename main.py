import os
import uuid
import subprocess
import shutil
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="Smart Video Downloader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = "temp_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class VideoInfoRequest(BaseModel):
    url: str

class ProcessRequest(BaseModel):
    url: str
    mode: str = "reverse"  # "reverse" or "normal"
    format_type: str = "video"  # "video" or "audio"
    quality: str = "720"  # "360", "480", "720", "1080"

def cleanup_file(file_path: str):
    """Deletes temporary file from server after download to free storage"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")

@app.get("/")
def home():
    return {"status": "online", "service": "Smart Video & Reverse Audio-Video Downloader API"}

@app.post("/api/info")
def get_video_info(req: VideoInfoRequest):
    """Fetches video metadata including title, thumbnail, duration, and channel name"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
            return {
                "title": info.get("title", "YouTube Video"),
                "thumbnail": info.get("thumbnail", ""),
                "duration": info.get("duration", 0),
                "channel": info.get("uploader", "YouTube Creator")
            }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch video information: {str(e)}")

@app.post("/api/process")
def process_video(req: ProcessRequest, background_tasks: BackgroundTasks):
    """Downloads YouTube video and reverses video & audio tracks if requested"""
    task_id = str(uuid.uuid4())[:8]
    raw_filename = os.path.join(DOWNLOAD_DIR, f"raw_{task_id}.mp4")
    out_filename = os.path.join(DOWNLOAD_DIR, f"reversed_{task_id}.mp4")

    ydl_opts = {
        'format': f'bestvideo[height<={req.quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={req.quality}][ext=mp4]/best',
        'outtmpl': raw_filename,
        'merge_output_format': 'mp4',
        'quiet': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([req.url])

        if not os.path.exists(raw_filename):
            raise HTTPException(status_code=500, detail="Failed to download video from YouTube.")

        if req.mode == "reverse":
            # FFmpeg pipeline to reverse both video frames (-vf reverse) and audio samples (-af areverse)
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", raw_filename,
                "-vf", "reverse",
                "-af", "areverse",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "22",
                "-c:a", "aac",
                out_filename
            ]
            result = subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cleanup_file(raw_filename)
            final_file = out_filename
        else:
            final_file = raw_filename

        file_id = os.path.basename(final_file)
        return {
            "status": "success",
            "file_id": file_id,
            "download_url": f"/api/download/{file_id}"
        }
    except subprocess.CalledProcessError as e:
        cleanup_file(raw_filename)
        cleanup_file(out_filename)
        raise HTTPException(status_code=500, detail=f"FFmpeg reversal processing failed: {e.stderr.decode('utf-8', errors='ignore')}")
    except Exception as e:
        cleanup_file(raw_filename)
        cleanup_file(out_filename)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.get("/api/download/{file_id}")
def download_file(file_id: str, background_tasks: BackgroundTasks):
    file_path = os.path.join(DOWNLOAD_DIR, file_id)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested file not found or expired.")

    background_tasks.add_task(cleanup_file, file_path)
    return FileResponse(
        path=file_path,
        filename=f"SmartVideo_{file_id}",
        media_type="video/mp4"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
