import discord
from discord.ext import commands, tasks
from flask import Flask
import threading
import os
import asyncio
import aiohttp
import re
import unicodedata
from datetime import timedelta, datetime
from discord.utils import utcnow
from difflib import SequenceMatcher

# --- Flask Keep-Alive ---
app = Flask(__name__)
bot_name = "Loading..."

@app.route("/")
def home():
    return f"Bot {bot_name} is operational"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- Discord Bot Setup ---
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Missing DISCORD_BOT_TOKEN in environment variables")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

session = None

# --- Warning Trackers ---
mention_warnings = {}
link_warnings = {}
badword_warnings = {}
last_mention_time = {}  # لتخزين أوقات آخر منشن لكل مستخدم

# --- قائمة الكلمات المسيئة ---
BAD_WORDS = [
    "fuck","shit","bitch","asshole","bastard","dick","douche","cunt","fag","slut","قلوة","ختك","سوتيان","خرى","خرية","106",
    "whore","prick","motherfucker","nigger","cock","pussy","twat","jerk","idiot","سوة","سوى","سخون","سليب","منوي","حواي",
    "9LAWI","9lawi","zok","zb","MOK","moron","dumbass","nik","nik mok","9A7BA","الطبون","طبون","زبور","الزبور",
    "zaml","كلب","نيك","نيك مك","كس","mok","نيك يماك","قحبة","ولد القحبة",
    "ابن الكلب","حمار","غبي","قذر","حقير","كافر","زب","زبي","قلاوي","زك",
    "الزك","نكمك","عطاي","حيوان","منيوك","خنزير","خائن","متسكع","أرعن",
    "حقيرة","لعينة","مشين","زانية","أوغاد","أهبل","لعين","منيك","ترمة",
    "مترم","بقرة","شرموطة","الشرموطة","العاهرة","قليل الأدب","ابن الشرموطة",
    "كس أمك","كس أختك","ابن القحبة","ابن الزانية","ابن العاهرة","ابن الحرام","ابن الزنا"
]

# --- Normalize text (استبدال الرموز + حذف التكرارات) ---
REPLACEMENTS = {
    "@":"a","4":"a","à":"a","á":"a","â":"a","ä":"a","å":"a","ª":"a",
    "8":"b","ß":"b",
    "(":"c","¢":"c","©":"c","ç":"c",
    "3":"e","€":"e","&":"e","ë":"e","è":"e","é":"e","ê":"e",
    "6":"g","9":"g",
    "#":"h",
    "!":"i","1":"i","¡":"i","|":"i","í":"i","î":"i","ï":"i","ì":"i",
    "£":"l","¬":"l",
    "0":"o","ò":"o","ó":"o","ô":"o","ö":"o","ø":"o","¤":"o",
    "$":"s","5":"s","§":"s","š":"s",
    "7":"t","+":"t","†":"t",
    "2":"z","¥":"y",
    "¶":"p",
    "*":"","^":"","~":"","`":"","?":"","!":"","-":"","=":"",",":"",".":""
}

def normalize_text(text: str) -> str:
    text = text.lower()
    for k, v in REPLACEMENTS.items():
        text = text.replace(k, v)
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\u0621-\u064A]+", "", text)
    text = re.sub(r"(.)\1{2,}", r"\1", text)
    return text

def is_similar(a: str, b: str, threshold: float = 0.8) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= threshold

def contains_bad_word(message: str) -> bool:
    text = normalize_text(message)
    for bad in BAD_WORDS:
        bad_norm = normalize_text(bad)
        if bad_norm in text:
            return True
        words = re.findall(r"[a-z0-9\u0621-\u064A]+", text)
        for w in words:
            if is_similar(w, bad_norm):
                return True
    return False

# --- Keep-Alive ---
@tasks.loop(minutes=1)
async def keep_alive():
    global session
    if session:
        try:
            url = "https://sevenmaya-1.onrender.com"
            async with session.get(url) as response:
                print(f"💡 Keep-Alive ping status: {response.status}")
        except Exception as e:
            print(f"⚠️ Keep-Alive error: {e}")

@keep_alive.before_loop
async def before_keep_alive():
    await bot.wait_until_ready()

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
    global bot_name, session
    bot_name = str(bot.user)
    print(f"✅ Bot connected as {bot.user} ({len(bot.guilds)} servers)")

    if not session:
        session = aiohttp.ClientSession()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🚀 Flask server started in background")

    keep_alive.start()
    update_status.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.author == message.guild.owner:
        await bot.process_commands(message)
        return

    user_id = message.author.id
    now = datetime.utcnow()

    # --- منشن المالك مع إعادة العد بعد 10 دقائق ---
    if message.guild.owner in message.mentions:
        last_time = last_mention_time.get(user_id)
        if not last_time or (now - last_time) > timedelta(minutes=10):
            last_mention_time[user_id] = now
            embed = discord.Embed(
                title="⚠️ تحذير من المنشن",
                description=f"{message.author.mention} لقد قمت بعمل منشن للمالك. المرة القادمة سيتم اسكاتك.",
                color=0xFFFF00
            )
            await message.channel.send(embed=embed)
        else:
            try:
                if not message.author.guild_permissions.administrator:
                    until_time = utcnow() + timedelta(hours=1)
                    await message.author.timeout(until_time, reason="تكرار منشن المالك")
                    embed = discord.Embed(
                        title="⛔ تم اسكاتك",
                        description=f"{message.author.mention} لقد تم اسكاتك بسبب تكرارك للمنشن.",
                        color=0xFF0000
                    )
                    await message.channel.send(embed=embed)
                else:
                    await message.channel.send("⚠️ لا يمكن اسكات عضو بصلاحيات عالية.")
            except Exception as e:
                await message.channel.send(f"⚠️ خطأ في الاسكات: {e}")
            last_mention_time[user_id] = None

    # --- الروابط ---
    if not any(role.permissions.manage_messages for role in message.author.roles):
        if re.search(r'https?://\S+', message.content):
            count = link_warnings.get(user_id, 0) + 1
            link_warnings[user_id] = count

            try:
                await message.delete()
            except:
                pass

            if count == 1:
                embed = discord.Embed(
                    title="⚠️ تحذير من الروابط",
                    description=f"{message.author.mention} نشر الروابط ممنوع. المرة القادمة سيتم اسكاتك.",
                    color=0xFFFF00
                )
                await message.channel.send(embed=embed)
            else:
                try:
                    until_time = utcnow() + timedelta(days=1)
                    await message.author.timeout(until_time, reason="نشر روابط")
                    embed = discord.Embed(
                        title="⛔ تم اسكاتك",
                        description=f"{message.author.mention} تم اسكاتك بسبب تكرار نشر الروابط.",
                        color=0xFF0000
                    )
                    await message.channel.send(embed=embed)
                except Exception as e:
                    await message.channel.send(f"⚠️ خطأ في الاسكات: {e}")
                link_warnings[user_id] = 0

    # --- الكلمات المسيئة ---
    if contains_bad_word(message.content):
        try:
            await message.delete()
        except:
            pass

        count = badword_warnings.get(user_id, 0) + 1
        badword_warnings[user_id] = count

        if count == 1:
            embed = discord.Embed(
                title="⚠️ تحذير من الكلمات الحساسة",
                description=f"{message.author.mention} لا تستخدم كلمات مسيئة. المرة القادمة سيتم اسكاتك.",
                color=0xFFFF00
            )
            await message.channel.send(embed=embed)
        else:
            try:
                until_time = utcnow() + timedelta(days=1)
                await message.author.timeout(until_time, reason="استخدام كلمات مسيئة")
                embed = discord.Embed(
                    title="⛔ تم اسكاتك",
                    description=f"{message.author.mention} تم اسكاتك بسبب تكرار استخدام كلمات مسيئة.",
                    color=0xFF0000
                )
                await message.channel.send(embed=embed)
            except Exception as e:
                await message.channel.send(f"⚠️ خطأ في الاسكات: {e}")
            badword_warnings[user_id] = 0

    await bot.process_commands(message)

# --- Run Bot ---
async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
