import discord
from discord.ext import commands, tasks
from flask import Flask
import threading
import os
import asyncio
import aiohttp
import re
from datetime import timedelta
from discord.utils import utcnow  # ✅ الحل هنا

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

# --- قائمة الكلمات المسيئة ---
BAD_WORDS = [
    "fuck","shit","bitch","asshole","bastard","dick","douche","cunt","fag","slut",
    "whore","prick","motherfucker","nigger","cock","pussy","twat","jerk","idiot",
    "moron","dumbass","nik","nik mok","9A7BA","zaml","كلب","نيك","نيك مك","كس",
    "نيك يماك","قحبة","ولد القحبة","ابن الكلب","حمار","غبي","قذر","حقير","كافر",
    "خائن","متسكع","أرعن","حقيرة","لعينة","مشين","زانية","أوغاد","حيوان","أهبل",
    "قليل الأدب","ابن الشرموطة","كس أمك","كس أختك","ابن القحبة","ابن الزانية",
    "ابن العاهرة","ابن الحرام","ابن الزنا"
]

# --- فحص الكلمات المسيئة ---
def contains_bad_word(message_content: str) -> bool:
    content = message_content.lower()
    for word in BAD_WORDS:
        if word.lower() in content:
            return True
    return False

# --- Keep-Alive ---
@tasks.loop(minutes=1)
async def keep_alive():
    global session
    if session:
        try:
            url = "https://sevenmaya.onrender.com"
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

    # --- منشن المالك ---
    if message.guild.owner in message.mentions:
        count = mention_warnings.get(user_id, 0) + 1
        mention_warnings[user_id] = count

        if count == 1:
            embed = discord.Embed(
                title="⚠️ تحذير من المنشن",
                description=f"{message.author.mention} لقد قمت بعمل منشن للمالك. المرة القادمة سيتم اسكاتك.",
                color=0xFFA500
            )
            await message.channel.send(embed=embed)
        else:
            try:
                if not message.author.guild_permissions.administrator:
                    until_time = utcnow() + timedelta(hours=1)  # ✅ التعديل هنا
                    await message.author.timeout(until_time, reason="تكرار منشن المالك")
                    embed = discord.Embed(
                        title="⛔ تم اسكاتك",
                        description=f"{message.author.mention} لقد تم اسكاتك لمدة ساعة بسبب تكرارك للمنشن.",
                        color=0xFF0000
                    )
                    await message.channel.send(embed=embed)
                else:
                    await message.channel.send("⚠️ لا يمكن اسكات عضو بصلاحيات عالية.")
            except Exception as e:
                await message.channel.send(f"⚠️ خطأ في الاسكات: {e}")
            mention_warnings[user_id] = 0

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
                await message.channel.send(f"⚠️ {message.author.mention} نشر الروابط ممنوع. المرة القادمة سيتم اسكاتك.")
            else:
                try:
                    until_time = utcnow() + timedelta(hours=1)
                    await message.author.timeout(until_time, reason="نشر روابط")
                    await message.channel.send(f"⛔ {message.author.mention} تم اسكاتك ساعة بسبب تكرار نشر الروابط.")
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
            await message.channel.send(f"⚠️ {message.author.mention} لا تستخدم كلمات مسيئة. المرة القادمة سيتم اسكاتك.")
        else:
            try:
                until_time = utcnow() + timedelta(hours=1)
                await message.author.timeout(until_time, reason="استخدام كلمات مسيئة")
                await message.channel.send(f"⛔ {message.author.mention} تم اسكاتك ساعة بسبب تكرار استخدام كلمات مسيئة.")
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
