import os
import asyncio
import uuid
import time
import shutil
from collections import deque, defaultdict
from typing import Dict

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# =========================
# ENV
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8080))

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("BOT_TOKEN & WEBHOOK_URL wajib di-set di Railway Variables")

# =========================
# GLOBAL STATE
# =========================
queue = deque()
active_job = None
cancel_flags: Dict[str, bool] = {}
stats = defaultdict(int)

TMP_DIR = "/tmp/clips"
os.makedirs(TMP_DIR, exist_ok=True)

# =========================
# UTIL
# =========================
def parse_time(t: str) -> int:
    if ":" in t:
        parts = list(map(int, t.split(":")))
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return int(t)

def estimate_size(duration: int, res: int) -> float:
    bitrate = 6 if res == 1080 else 3
    return round((duration * bitrate) / 8, 2)  # MB

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 AutoClipYT\n"
        "/clip1080 <url> <start> <end>\n"
        "/clip720 <url> <start> <end>\n"
        "/cancel\n"
        "/stats"
    )

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 Statistik\n"
        f"Jobs selesai: {stats['done']}\n"
        f"Jobs batal: {stats['cancel']}\n"
        f"Total request: {stats['total']}"
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if active_job:
        cancel_flags[active_job["id"]] = True
        await update.message.reply_text("🛑 Job dibatalkan")
    else:
        await update.message.reply_text("Tidak ada job aktif")

async def clip(update: Update, context: ContextTypes.DEFAULT_TYPE, res: int):
    try:
        url, start, end = context.args
        s = parse_time(start)
        e = parse_time(end)
        dur = e - s
        if dur <= 0:
            raise ValueError
    except Exception:
        await update.message.reply_text("Format salah")
        return

    job_id = str(uuid.uuid4())
    queue.append({
        "id": job_id,
        "chat": update.effective_chat.id,
        "url": url,
        "start": s,
        "end": e,
        "res": res,
    })

    stats["total"] += 1
    size = estimate_size(dur, res)

    await update.message.reply_text(
        f"⏳ Masuk antrean\n"
        f"Estimasi ukuran: {size} MB\n"
        f"Posisi antrean: {len(queue)}"
    )

async def clip1080(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clip(update, context, 1080)

async def clip720(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await clip(update, context, 720)

# =========================
# WORKER
# =========================
async def worker(app):
    global active_job

    while True:
        if not queue or active_job:
            await asyncio.sleep(1)
            continue

        job = queue.popleft()
        active_job = job
        jid = job["id"]
        cancel_flags[jid] = False

        chat = job["chat"]
        out = f"{TMP_DIR}/{jid}.mp4"

        try:
            await app.bot.send_message(chat, "⚡ Processing...")

            cmd = (
                f'yt-dlp -f "bv*[height<={job["res"]}]+ba/b" '
                f'-o - "{job["url"]}" | '
                f'ffmpeg -y -i pipe:0 -ss {job["start"]} -to {job["end"]} '
                f'-c copy "{out}"'
            )

            proc = await asyncio.create_subprocess_shell(cmd)
            while proc.returncode is None:
                if cancel_flags[jid]:
                    proc.kill()
                    raise asyncio.CancelledError
                await asyncio.sleep(1)

            await app.bot.send_video(chat, video=open(out, "rb"))
            stats["done"] += 1

        except asyncio.CancelledError:
            await app.bot.send_message(chat, "❌ Job dibatalkan")
            stats["cancel"] += 1

        except Exception as e:
            await app.bot.send_message(chat, f"Error: {e}")

        finally:
            if os.path.exists(out):
                os.remove(out)
            active_job = None

# =========================
# STARTUP
# =========================
async def on_startup(app):
    app.create_task(worker(app))

# =========================
# MAIN
# =========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("clip1080", clip1080))
    app.add_handler(CommandHandler("clip720", clip720))

    app.post_init = on_startup

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )

if __name__ == "__main__":
    main()        json.dump(stats, f)

stats = load_stats()

# ================= UTILS =================
def parse_time(t):
    if ":" in t:
        p = list(map(int, t.split(":")))
        return p[-1] + (p[-2] * 60) + (p[-3] * 3600 if len(p) == 3 else 0)
    if t.isdigit():
        return int(t)
    m = re.match(r"(?:(\d+)m)?(?:(\d+)s)?", t)
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)

def estimate_size(profile, dur):
    p = PROFILES[profile]
    return round((p["v"] + p["a"]) * dur / 8 / 1024, 2)

def bar(p):
    return "█" * (p // 10) + "░" * (10 - p // 10)

# ================= QUEUE =================
async def enqueue(update, context, profile):
    if len(context.args) != 3:
        await update.message.reply_text(
            f"Format:\n/{context.command} <url> <start> <durasi>"
        )
        return

    url, start, dur = context.args
    dur_s = parse_time(dur)

    if dur_s > PROFILES[profile]["max"]:
        await update.message.reply_text(
            f"❌ Max {profile}p = {PROFILES[profile]['max']} detik"
        )
        return

    size = estimate_size(profile, dur_s)
    if size > 48:
        await update.message.reply_text(
            f"❌ Estimasi {size} MB (>50MB)\nGunakan resolusi lebih rendah"
        )
        return

    pos = queue.qsize() + 1
    eta = pos * avg_time

    await queue.put((update, context, profile))
    await update.message.reply_text(
        f"📥 Masuk antrean\n"
        f"🎬 {profile}p | 📦 {size}MB\n"
        f"⏱ ETA ~{eta}s"
    )

# ================= WORKER =================
async def worker(app):
    global avg_time
    while True:
        update, context, profile = await queue.get()
        uid = update.effective_user.id
        start_t = time.time()

        msg = await update.message.reply_text("⏳ Processing...")
        output = f"clip_{uid}.mp4"

        try:
            url, start, dur = context.args
            start_s = parse_time(start)
            dur_s = parse_time(dur)
            p = PROFILES[profile]

            ytdlp = subprocess.Popen(
                ["yt-dlp", "-f", f"bv*[height={profile}]/bv*", "-o", "-", url],
                stdout=subprocess.PIPE
            )

            ffmpeg = subprocess.Popen(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start_s),
                    "-i", "pipe:0",
                    "-t", str(dur_s),
                    "-vf", f"scale={p['scale']}",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-b:v", f"{p['v']}k",
                    "-c:a", "aac",
                    "-b:a", f"{p['a']}k",
                    "-progress", "pipe:1",
                    "-nostats",
                    output
                ],
                stdin=ytdlp.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True
            )

            jobs[uid] = ffmpeg
            last = 0
            dur_ms = dur_s * 1_000_000

            for line in ffmpeg.stdout:
                if "out_time_ms" in line:
                    ms = int(line.split("=")[1])
                    pct = min(100, int(ms / dur_ms * 100))
                    if pct - last >= 5:
                        await msg.edit_text(
                            f"🎬 Processing\n{bar(pct)} {pct}%"
                        )
                        last = pct

            ffmpeg.wait()
            await msg.edit_text("📤 Uploading...")
            await update.message.reply_video(video=open(output, "rb"))

            # ==== STATS UPDATE ====
            stats["total_jobs"] += 1
            stats["total_duration"] += dur_s
            stats["resolution"][profile] += 1
            stats["users"][str(uid)] = stats["users"].get(str(uid), 0) + 1
            elapsed = int(time.time() - start_t)
            stats["avg_process"] = int(
                (stats["avg_process"] + elapsed) / 2
            )
            save_stats()

            avg_time = int((avg_time + elapsed) / 2)

        except Exception as e:
            await msg.edit_text(f"❌ Error: {e}")

        finally:
            jobs.pop(uid, None)
            if os.path.exists(output):
                os.remove(output)
            queue.task_done()

# ================= COMMANDS =================
async def clip720(update, context):
    await enqueue(update, context, "720")

async def clip1080(update, context):
    await enqueue(update, context, "1080")

async def cancel(update, context):
    uid = update.effective_user.id
    if uid in jobs:
        jobs[uid].kill()
        await update.message.reply_text("❌ Job dibatalkan")
    else:
        await update.message.reply_text("⚠️ Tidak ada job aktif")

async def stats_cmd(update, context):
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
