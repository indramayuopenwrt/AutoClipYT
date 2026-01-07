import os, re, time, json, asyncio, subprocess
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ================= ENV =================
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
PORT = int(os.environ.get("PORT", 8080))

# ================= PROFILE =================
PROFILES = {
    "720":  {"v": 2500, "a": 128, "max": 60, "scale": "1280:720"},
    "1080": {"v": 5000, "a": 128, "max": 30, "scale": "1920:1080"},
}

# ================= GLOBAL =================
queue = asyncio.Queue()
jobs = {}
avg_time = 20
STATS_FILE = "stats.json"

# ================= STATS =================
def load_stats():
    if not os.path.exists(STATS_FILE):
        return {
            "total_jobs": 0,
            "total_duration": 0,
            "resolution": {"720": 0, "1080": 0},
            "users": {},
            "avg_process": 0
        }
    with open(STATS_FILE) as f:
        return json.load(f)

def save_stats():
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

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