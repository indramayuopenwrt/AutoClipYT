import os
import asyncio
import uuid
import shutil
import subprocess
from collections import deque

from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 8080))

BASE_DIR = "/tmp/autoclip"
MAX_DURATION = 300

os.makedirs(BASE_DIR, exist_ok=True)

# ================= GLOBAL =================
queue = deque()
processing = False

# ================= UTILS =================
def run(cmd):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def parse_time(t):
    parts = list(map(int, t.split(":")))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]

# ================= WORKER =================
async def worker(app: Application):
    global processing
    if processing:
        return

    processing = True

    while queue:
        job = queue.popleft()
        chat_id = job["chat_id"]
        bot = app.bot

        vid = f"{BASE_DIR}/{job['id']}.mp4"
        cut = f"{BASE_DIR}/{job['id']}_cut.mp4"
        out = f"{BASE_DIR}/{job['id']}_final.mp4"

        try:
            await bot.send_message(chat_id, "🎬 Processing...")

            run(["yt-dlp", "-f", job["fmt"], "-o", vid, job["url"]])

            run([
                "ffmpeg", "-y",
                "-ss", str(job["start"]),
                "-to", str(job["end"]),
                "-i", vid,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                       "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,boxblur=20",
                "-preset", "veryfast",
                out
            ])

            await bot.send_video(chat_id, video=open(out, "rb"))

        except Exception as e:
            await bot.send_message(chat_id, f"❌ Error: {e}")

        finally:
            shutil.rmtree(BASE_DIR, ignore_errors=True)
            os.makedirs(BASE_DIR, exist_ok=True)

    processing = False

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎞 AutoClipYT\n\n"
        "/clip720 <url> <start> <end>\n"
        "/clip1080 <url> <start> <end>\n"
        "Max 300 detik"
    )

async def clip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        return await update.message.reply_text("❌ Format salah")

    url, t1, t2 = context.args
    start = parse_time(t1)
    end = parse_time(t2)

    if end - start > MAX_DURATION:
        return await update.message.reply_text("⛔ Max 300 detik")

    fmt = (
        "bestvideo[height<=720]+bestaudio/best"
        if update.message.text.startswith("/clip720")
        else "bestvideo[height<=1080]+bestaudio/best"
    )

    queue.append({
        "id": str(uuid.uuid4()),
        "chat_id": update.message.chat_id,
        "url": url,
        "start": start,
        "end": end,
        "fmt": fmt,
    })

    await update.message.reply_text(f"📥 Masuk antrean ({len(queue)})")
    asyncio.create_task(worker(context.application))

# ================= FASTAPI =================
app = FastAPI()
tg_app = Application.builder().token(BOT_TOKEN).build()

tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("clip720", clip))
tg_app.add_handler(CommandHandler("clip1080", clip))

@app.post("/")
async def webhook(req: Request):
    data = await req.json()
    await tg_app.update_queue.put(Update.de_json(data, tg_app.bot))
    return {"ok": True}

@app.on_event("startup")
async def startup():
    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL)

# ================= RUN =================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
