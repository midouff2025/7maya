import discord
from discord.ext import commands, tasks
from flask import Flask
import threading
import os
import asyncio
import aiohttp
import re
from datetime import datetime, timedelta

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

session = None  # جلسة aiohttp واحدة لجميع الطلبات

# --- Warning Trackers ---
mention_warnings = {}  # user_id: count
link_warnings = {}     # user_id: count

# --- Keep-Alive Task ---
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

# --- Periodic Bot Status ---
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

    # --- تجاهل المالك عند مراقبة الروابط والمنشن ---
    if message.author == message.guild.owner:
        await bot.process_commands(message)
        return

    # --- مراقبة منشن المالك ---
    if message.guild.owner in message.mentions:
        user_id = message.author.id
        count = mention_warnings.get(user_id, 0) + 1
        mention_warnings[user_id] = count

        if count == 1:
            embed = discord.Embed(
                title="تحذير من المنشن ⚠️",
                description=f"{message.author.mention} لقد قمت بعمل منشن للمالك. المرة القادمة سيتم اسكاتك.",
                color=0xFFA500
            )
            await message.channel.send(embed=embed)
        else:
            try:
                if not message.author.guild_permissions.administrator:
                    until_time = datetime.utcnow() + timedelta(hours=1)
                    await message.author.timeout(until=until_time, reason="تكرار المنشن للمالك")
                    embed = discord.Embed(
                        title="تم سكاتك ⛔ ",
                        description=f"{message.author.mention} لقد تم اسكاتك لمدة ساعة بسبب تكرارك للمنشن.",
                        color=0xFF0000
                    )
                    await message.channel.send(embed=embed)
                else:
                    embed = discord.Embed(
                        title="⚠️ فشل اسكات العضو",
                        description=f"{message.author.mention} لا يمكنني اسكات هذا العضو لأنه مسؤول أو لديه صلاحيات عالية.",
                        color=0xFF4500
                    )
                    await message.channel.send(embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    title="⚠️ خطأ في الاسكات",
                    description=f"حدث خطأ عند محاولة اسكات {message.author.mention}: {e}",
                    color=0xFF4500
                )
                await message.channel.send(embed=embed)
            mention_warnings[user_id] = 0  # إعادة تعيين العداد بعد العقوبة

    # --- منع نشر الروابط ---
    if not any(role.permissions.manage_messages for role in message.author.roles):
        urls = re.findall(r'https?://\S+', message.content)
        if urls:
            user_id = message.author.id
            count = link_warnings.get(user_id, 0) + 1
            link_warnings[user_id] = count

            try:
                await message.delete()
            except Exception as e:
                print(f"⚠️ Error deleting message: {e}")

            if count == 1:
                embed = discord.Embed(
                    title="تحذير من نشر الروابط ⚠️",
                    description=f"{message.author.mention} نشر الروابط هنا ممنوع. المرة القادمة سيتم اسكاتك.",
                    color=0xFFA500
                )
                await message.channel.send(embed=embed)
            else:
                try:
                    if not message.author.guild_permissions.administrator:
                        until_time = datetime.utcnow() + timedelta(hours=1)
                        await message.author.timeout(until=until_time, reason="تكرار نشر الروابط")
                        embed = discord.Embed(
                            title="تم اسكاتك ⛔",
                            description=f"{message.author.mention} لقد تم اسكاتك لمدة ساعة بسبب تكرارك نشر الروابط.",
                            color=0xFF0000
                        )
                        await message.channel.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="⚠️ فشل اسكات العضو",
                            description=f"{message.author.mention} لا يمكنني اسكات هذا العضو لأنه مسؤول أو لديه صلاحيات عالية.",
                            color=0xFF4500
                        )
                        await message.channel.send(embed=embed)
                except Exception as e:
                    embed = discord.Embed(
                        title="⚠️ خطأ في الاسكات",
                        description=f"حدث خطأ عند محاولة اسكات {message.author.mention}: {e}",
                        color=0xFF4500
                    )
                    await message.channel.send(embed=embed)
                link_warnings[user_id] = 0  # إعادة تعيين العداد بعد العقوبة

    await bot.process_commands(message)

# --- Run Bot ---
async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
