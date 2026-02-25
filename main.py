import discord
from discord.ext import commands, tasks
from flask import Flask
import threading
import os
import asyncio
import aiohttp
import re
import unicodedata
from datetime import datetime, timedelta
from discord.utils import utcnow

# --- Flask Keep-Alive ---
app = Flask(__name__)
ALLOWED_CHANNEL_ID = 1403040565137899733  # ضع هنا القناة الخاصة
bot_name = "Loading..."

@app.route("/")
def home():
    return f"Bot {bot_name} is operational ✅"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- Discord Bot Setup ---
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Missing DISCORD_BOT_TOKEN in environment variables")

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.session = None
        self.last_link_time = {}

    async def setup_hook(self):
        # جلسة aiohttp واحدة
        self.session = aiohttp.ClientSession()
        # بدء Flask في Thread
        threading.Thread(target=run_flask, daemon=True).start()
        print("🚀 Flask server started in background")
        # بدء المهام الدورية
        self.update_status.start()

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    # --- تحديث الحالة ---
    @tasks.loop(minutes=5)
    async def update_status(self):
        try:
            activity = discord.Activity(type=discord.ActivityType.watching, name=f"{len(self.guilds)} servers")
            await self.change_presence(activity=activity)
        except Exception as e:
            print(f"⚠️ Status update failed: {e}")

    @update_status.before_loop
    async def before_status_update(self):
        await self.wait_until_ready()

    # --- كشف الروابط ---
    def normalize_text(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = text.lower().replace("ـ", "")
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"(.)\1{2,}", r"\1", text)
        return text

    def contains_link(self, message: discord.Message) -> bool:
        content = self.normalize_text(message.content)
        spotify_domains = ["spotify.com", "open.spotify.com", "spotify.link"]
        if any(domain in content for domain in spotify_domains):
            return False
        if re.search(r"https?://", content): return True
        if "www." in content: return True
        domain_pattern = r"[a-z0-9\-]+\.(com|net|org|gg|io|me|co|xyz|info|app|site|store|online)"
        if re.search(domain_pattern, content): return True
        if "discord.gg" in content or "discord.com/invite" in content: return True
        for embed in message.embeds:
            if embed.url and not any(domain in self.normalize_text(embed.url) for domain in spotify_domains):
                return True
        for attachment in message.attachments:
            filename = self.normalize_text(attachment.filename)
            if re.search(domain_pattern, filename) and not any(domain in filename for domain in spotify_domains):
                return True
        return False

    # --- حذف الرسائل والتحذيرات ---
    async def on_message(self, message):
        if message.author.bot: return
        user_id = message.author.id
        now = datetime.utcnow()

        # فقط لمن ليس لديهم صلاحيات إدارة الرسائل
        if not any(role.permissions.manage_messages for role in message.author.roles):
            if self.contains_link(message):
                # حذف مؤقت للقناة الخاصة
                if message.channel.id == ALLOWED_CHANNEL_ID:
                    try:
                        await asyncio.sleep(5)
                        await message.delete()
                    except: pass
                    return

                try: await message.delete()
                except: pass

                last_time = self.last_link_time.get(user_id)
                if not last_time or (now - last_time) > timedelta(hours=1):
                    self.last_link_time[user_id] = now
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
                        print("⚠️ Timeout error:", e)
                    self.last_link_time[user_id] = None

        await self.process_commands(message)

# --- Run Bot ---
bot = MyBot()

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
