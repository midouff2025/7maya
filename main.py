import discord
from discord.ext import commands, tasks
import os
import asyncio
import aiohttp
import re
import unicodedata
from datetime import timedelta, datetime
from discord.utils import utcnow

# --- Discord Bot Setup ---
TOKEN = "MTQwNzA0MTYwNDg3ODg2NDU0OA.GiIEuj.XB1zeEpEoUnvq9430Yabd8ukY0SCusMDBY63u4"  # ضع التوكن هنا

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

session = None

# --- Warning Trackers ---
link_warnings = {}
last_link_time = {}

# --- Normalize text ---
def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    text = text.replace("ـ", "")
    text = re.sub(r"\s+", "", text)  # إزالة المسافات للتحايل
    text = re.sub(r"(.)\1{2,}", r"\1", text)
    return text

# 🔥 كشف روابط قوي جدًا مع السماح الكامل لسبوتيفاي
def contains_link(message: discord.Message) -> bool:
    content = normalize_text(message.content)

    # 🔓 السماح الكامل لسبوتيفاي
    spotify_domains = [
        "spotify.com",
        "open.spotify.com",
        "spotify.link"
    ]

    if any(domain in content for domain in spotify_domains):
        return False  # مسموح بالكامل

    # 1️⃣ http / https
    if re.search(r"https?://", content):
        return True

    # 2️⃣ www
    if "www." in content:
        return True

    # 3️⃣ أي دومين مباشر بدون http
    domain_pattern = r"[a-z0-9\-]+\.(com|net|org|gg|io|me|co|xyz|info|app|site|store|online)"
    if re.search(domain_pattern, content):
        return True

    # 4️⃣ دعوات ديسكورد
    if "discord.gg" in content or "discord.com/invite" in content:
        return True

    # 5️⃣ روابط داخل Embed (مع استثناء سبوتيفاي)
    for embed in message.embeds:
        if embed.url:
            embed_url = normalize_text(embed.url)
            if not any(domain in embed_url for domain in spotify_domains):
                return True

    # 6️⃣ روابط داخل المرفقات (اسم الملف)
    for attachment in message.attachments:
        filename = normalize_text(attachment.filename)
        if re.search(domain_pattern, filename):
            if not any(domain in filename for domain in spotify_domains):
                return True

    return False

# --- Update Status ---
@tasks.loop(minutes=5)
async def update_status():
    try:
        activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(bot.guilds)} servers")
        await bot.change_presence(activity=activity)
    except Exception as e:
        print(f"⚠️ Status update failed: {e}")

# --- Bot Events ---
@bot.event
async def on_ready():
    global session
    print(f"✅ Bot connected as {bot.user} ({len(bot.guilds)} servers)")

    if not session:
        session = aiohttp.ClientSession()

    update_status.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    now = datetime.utcnow()

    # --- الروابط فقط ---
    if not any(role.permissions.manage_messages for role in message.author.roles):
        if contains_link(message):

            # الغرفة الخاصة: حذف بعد 5 ثواني فقط
            if message.channel.id == 1403040565137899733:
                try:
                    await asyncio.sleep(5)
                    await message.delete()
                except:
                    pass
                return

            # باقي الغرف
            try:
                await message.delete()
            except:
                pass

            last_time = last_link_time.get(user_id)
            if not last_time or (now - last_time) > timedelta(hours=1):
                last_link_time[user_id] = now
                embed = discord.Embed(
                    title="⚠️ تحذير من الروابط",
                    description=f"{message.author.mention} نشر الروابط ممنوع. المرة القادمة سيتم اسكاتك.",
                    color=0xFFFF00
                )
                await message.channel.send(embed=embed)
            else:
                try:
                    until_time = utcnow() + timedelta(hours=1)
                    await message.author.timeout(until_time, reason="نشر روابط")
                    embed = discord.Embed(
                        title="⛔ تم اسكاتك",
                        description=f"{message.author.mention} تم اسكاتك بسبب تكرار نشر الروابط.",
                        color=0xFF0000
                    )
                    await message.channel.send(embed=embed)
                except Exception as e:
                    await message.channel.send(f"⚠️ خطأ في الاسكات: {e}")
                last_link_time[user_id] = None

    await bot.process_commands(message)

# --- Run Bot ---
async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())