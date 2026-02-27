import discord
from discord.ext import commands, tasks
from flask import Flask
import threading
import os
import asyncio
import aiohttp
import re
import unicodedata
from datetime import datetime, timedelta, timezone

# ---------------- Flask Keep-Alive ---------------- #

app = Flask(__name__)
ALLOWED_CHANNEL_ID = 1403040565137899733
bot_name = "Loading..."

@app.route("/")
def home():
    return f"Bot {bot_name} is operational ✅"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ---------------- Discord Bot Setup ---------------- #

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
        self.session = aiohttp.ClientSession()
        threading.Thread(target=run_flask, daemon=True).start()
        print("🚀 Flask server started in background")
        self.update_status.start()
        self.keep_alive.start()

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    # ---------------- Status Update ---------------- #

    @tasks.loop(minutes=5)
    async def update_status(self):
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            print(f"⚠️ Status update failed: {e}")

    @update_status.before_loop
    async def before_status_update(self):
        await self.wait_until_ready()

    # ---------------- Keep-Alive Ping ---------------- #

    @tasks.loop(minutes=1)
    async def keep_alive(self):
        if self.session:
            try:
                url = "https://sevenmaya-6.onrender.com"
                async with self.session.get(url):
                    pass
            except Exception as e:
                print(f"⚠️ KeepAlive ping failed: {e}")

    @keep_alive.before_loop
    async def before_keep_alive(self):
        await self.wait_until_ready()

    # ---------------- Text Normalization ---------------- #

    def normalize_text(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = text.lower().replace("ـ", "")
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"(.)\1{2,}", r"\1", text)
        return text

    # ---------------- Link Detection ---------------- #

    def contains_link(self, message: discord.Message) -> bool:
        spotify_whitelist = ["spotify.com", "open.spotify.com", "spotify.link"]
        shorteners = ["bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "rebrand.ly"]

        full_content = message.content
        for embed in message.embeds:
            if embed.url: full_content += " " + embed.url
            if getattr(embed, "description", None): full_content += " " + embed.description
            if getattr(embed, "title", None): full_content += " " + embed.title

        content = self.normalize_text(full_content)

        # Check markdown links
        for link in re.findall(r"\[.*?\]\((.*?)\)", full_content):
            if not any(domain in link for domain in spotify_whitelist):
                return True

        # Check normal URLs
        if re.search(r"https?://", content):
            if not any(domain in content for domain in spotify_whitelist):
                return True

        # Check domain patterns
        domain_pattern = r"[a-z0-9\-]+\.(com|net|org|gg|io|me|xyz|link)"
        if re.search(domain_pattern, content):
            if not any(domain in content for domain in spotify_whitelist):
                return True

        # Discord invites
        if "discord.gg" in content or "discord.com/invite" in content:
            return True

        # Shorteners
        if any(short in content for short in shorteners):
            return True

        # Attachments
        for att in message.attachments:
            if re.search(domain_pattern, self.normalize_text(att.filename)):
                return True

        return False

    # ---------------- Message Handler ---------------- #

    async def on_message(self, message):
        if message.author.bot:
            return

        if message.channel.id == ALLOWED_CHANNEL_ID:
            await self.process_commands(message)
            return

        if message.author.guild_permissions.manage_messages:
            await self.process_commands(message)
            return

        if not self.contains_link(message):
            await self.process_commands(message)
            return

        # Delete link message
        try:
            await message.delete()
        except:
            pass

        user_id = message.author.id
        now = datetime.now(timezone.utc)
        last_time = self.last_link_time.get(user_id)

        # First warning
        if not last_time or (now - last_time) > timedelta(hours=1):
            self.last_link_time[user_id] = now
            embed = discord.Embed(
                title="⚠️ تحذير | Warning",
                description=(
                    f"{message.author.mention} نشر الروابط ممنوع.\n"
                    f"Posting links is not allowed.\n"
                    f"المرة القادمة سيتم اسكاتك لمدة ساعة.\n"
                    f"You will be muted for 1 hour if repeated."
                ),
                color=0xFFFF00
            )
            await message.channel.send(embed=embed)
            return

        # Timeout after repeated link
        try:
            until = datetime.now(timezone.utc) + timedelta(hours=1)
            await message.author.timeout(until, reason="Posting links repeatedly")

            embed = discord.Embed(
                title="⛔ تم اسكاتك | You Have Been Muted",
                description=(
                    f"{message.author.mention}\n"
                    f"تم اسكاتك لمدة ساعة بسبب تكرار نشر الروابط.\n"
                    f"You have been muted for 1 hour for repeated link posting."
                ),
                color=0xFF0000
            )
            await message.channel.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Timeout failed: {e}")

        self.last_link_time[user_id] = None
        await self.process_commands(message)

# ---------------- Run Bot ---------------- #

bot = MyBot()

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
