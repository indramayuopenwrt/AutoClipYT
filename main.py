import os
import asyncio
import uuid
import shutil
import subprocess
from datetime import datetime
from collections import deque

from fastapi import FastAPI, Request
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import whisper

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # https://xxx.up.railway.app
PORT = int(os.getenv("PORT", 8080))

MAX_DURATION = 300  # detik
BASE_DIR = "/tmp/autoclip"
WATERMARK = "watermark.png"

os.makedirs(BASE_DIR, exist_ok=True)

# ================== GLOBAL ==================
queue = deque()
processing = False
usage_stats = {
    "jobs": 0,
    "users": set()
}

# ================== UTILS ==================
def run(cmd):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def ts(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")

def parse_time(t):
    p = list(map(int, t.split(":")))
    if len(p) == 2:
        return p[0]*60 + p[1]
    return p[0]*3600 + p[1]*60 + p[2]

# ================== WORKER ==================
async def worker(app: Application):
    global processing
    if processing:
        return
    processing = True

    while queue:
        job = queue.popleft()
        chat_id = job["chat_id"]
        bot = app.bot

        try:
            await bot.send_message(chat_id, "🎬 Processing clip...")

            vid = f"{BASE_DIR}/{job['id']}.mp4"
            cut = f"{BASE_DIR}/{job['id']}_cut.mp4"
            audio = f"{BASE_DIR}/{job['id']}.wav"
            subs = f"{BASE_DIR}/{job['id']}.srt"
            out = f"{BASE_DIR}/{job['id']}_final.mp4"

            # download
            run(["yt-dlp", "-f", job["fmt"], "-o", vid, job["url"]])

            # cut
            run([
                "ffmpeg", "-y",
                "-ss", str(job["start"]),
                "-to", str(job["end"]),
                "-i", vid,
                "-c", "copy",
                cut
            ])

            # audio
            run([
                "ffmpeg", "-y", "-i", cut,
                "-vn", "-ac", "1", "-ar", "16000", audio
            ])

            # whisper
            model = whisper.load_model("base")
            result = model.transcribe(audio)

            with open(subs, "w") as f:
                for i, s in enumerate(result["segments"], 1):
                    f.write(f"{i}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text'].strip()}\n\n")

            # render FINAL
            vf = (
                "[0:v]scale=1080:1920,boxblur=20:5[bg];"
                "[0:v]scale=iw*min(1080/iw\\,1920/ih):ih*min(1080/iw\\,1920/ih)[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                f"subtitles={subs}:force_style='Fontsize=48,Outline=2,Alignment=10',"
                f"movie={WATERMARK},scale=200:-1[wm];"
                "[in][wm]overlay=W-w-40:H-h-40[out]"
            )

            run([
                "ffmpeg", "-y",
                "-i", cut,
                "-vf", vf,
                "-preset", "veryfast",
                "-movflags", "+faststart",
                out
            ])

            await bot.send_video(chat_id, video=open(out, "rb"))

        except Exception as e:
            await bot.send_message(chat_id, f"❌ Error: {e}")

        finally:
            shutil.rmtree(BASE_DIR, ignore_errors=True)
            os.makedirs(BASE_DIR, exist_ok=True)

    processing = False

# ================== COMMANDS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎞 AutoClipYT\n\n"
        "/clip720 <url> <start> <end>\n"
        "/clip1080 <url> <start> <end>\n\n"
        "Max 300 detik | Auto Shorts"
    )

async def clip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global queue
    args = context.args
    if len(args) < 3:
        return await update.message.reply_text("❌ Format salah")

    url, t1, t2 = args
    start, end = parse_time(t1), parse_time(t2)

    if end - start > MAX_DURATION:
        return await update.message.reply_text("⛔ Max 300 detik")

    fmt = "bestvideo[height<=720]+bestaudio/best" \
        if update.message.text.startswith("/clip720") \
        else "bestvideo[height<=1080]+bestaudio/best"

    job = {
        "id": str(uuid.uuid4()),
        "chat_id": update.message.chat_id,
        "url": url,
        "start": start,
        "end": end,
        "fmt": fmt,
    }

    queue.append(job)
    usage_stats["jobs"] += 1
    usage_stats["users"].add(update.message.chat_id)

    await update.message.reply_text(
        f"📥 Masuk antrean\n"
        f"📊 Queue: {len(queue)}"
    )

    asyncio.create_task(worker(context.application))

# ================== APP ==================
app = FastAPI()
telegram_app = Application.builder().token(BOT_TOKEN).build()

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("clip720", clip))
telegram_app.add_handler(CommandHandler("clip1080", clip))

@app.post("/")
async def webhook(req: Request):
    data = await req.json()
    await telegram_app.update_queue.put(Update.de_json(data, telegram_app.bot))
    return {"ok": True}

@app.on_event("startup")
async def on_start():
    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(WEBHOOK_URL)

# ================== RUN ==================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT) stats_cmd(update, context):
    await update.message.reply_text(
        f"📊 Statistik Bot\n\n"
        f"🎬 Total clip: {stats['total_jobs']}\n"
        f"⏱ Total durasi: {stats['total_duration']} detik\n"
        f"📺 720p: {stats['resolution']['720']}\n"
        f"📺 1080p: {stats['resolution']['1080']}\n"
        f"⚡ Avg process: {stats['avg_process']} detik"
    )

# ================= START =================
app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("clip720", clip720))
app.add_handler(CommandHandler("clip1080", clip1080))
app.add_handler(CommandHandler("cancel", cancel))
app.add_handler(CommandHandler("stats", stats_cmd))

app.post_init = lambda app: asyncio.create_task(worker(app))

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    webhook_url=WEBHOOK_URL
)
