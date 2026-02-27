import discord
from discord.ext import commands, tasks
from flask import Flask
import threading
import os
import asyncio
import aiohttp
import re
from datetime import datetime, timedelta, UTC
from discord.utils import utcnow

# ==============================
# Flask Keep-Alive
# ==============================

app = Flask(__name__)
ALLOWED_CHANNEL_ID = 1403040565137899733  # غيره لو احتجت
bot_name = "Loading..."

@app.route("/")
def home():
    return f"Bot {bot_name} is operational ✅"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ==============================
# Discord Bot Setup
# ==============================

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Missing DISCORD_BOT_TOKEN")

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(command_prefix="!", intents=intents)

        self.session = None
        self.last_link_time = {}

    async def setup_hook(self):
        global bot_name
        bot_name = self.user.name if self.user else "Bot"

        self.session = aiohttp.ClientSession()
        threading.Thread(target=run_flask, daemon=True).start()

        self.update_status.start()
        self.keep_alive.start()

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    # ==============================
    # Status Update
    # ==============================

    @tasks.loop(minutes=5)
    async def update_status(self):
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(self.guilds)} servers"
        )
        await self.change_presence(activity=activity)

    @update_status.before_loop
    async def before_status_update(self):
        await self.wait_until_ready()

    # ==============================
    # Keep Alive
    # ==============================

    @tasks.loop(minutes=5)
    async def keep_alive(self):
        if self.session:
            try:
                url = "https://sevenmaya-6.onrender.com"  # ضع رابطك
                async with self.session.get(url):
                    pass
            except:
                pass

    @keep_alive.before_loop
    async def before_keep_alive(self):
        await self.wait_until_ready()

    # ==============================
    # Link Detection
    # ==============================

    def contains_link(self, message: discord.Message) -> bool:
        spotify_whitelist = ["spotify.com", "open.spotify.com", "spotify.link"]

        full_content = message.content

        for embed in message.embeds:
            if embed.url:
                full_content += " " + embed.url
            if embed.description:
                full_content += " " + embed.description
            if embed.title:
                full_content += " " + embed.title

        full_lower = full_content.lower()

        # HTTP Links
        urls = re.findall(r"https?://[^\s]+", full_content)
        for url in urls:
            if not any(domain in url.lower() for domain in spotify_whitelist):
                return True

        # Markdown Links
        markdown_links = re.findall(r"\[.*?\]\((.*?)\)", full_content)
        for link in markdown_links:
            if not any(domain in link.lower() for domain in spotify_whitelist):
                return True

        # Domain without http
        domain_pattern = r"\b[a-zA-Z0-9-]+\.(com|net|org|gg|io|me|co|xyz|info|app|site|store|online|tech|dev|link)\b"
        matches = re.findall(domain_pattern, full_lower)
        if matches:
            if not any(domain in full_lower for domain in spotify_whitelist):
                return True

        # Discord Invites
        if "discord.gg" in full_lower or "discord.com/invite" in full_lower:
            return True

        # Shorteners
        shorteners = [
            "bit.ly", "tinyurl.com", "t.co",
            "goo.gl", "is.gd", "cutt.ly",
            "rebrand.ly", "shorturl.at"
        ]
        if any(short in full_lower for short in shorteners):
            return True

        return False

    # ==============================
    # Message Handler
    # ==============================

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Allow moderators
        if message.author.guild_permissions.manage_messages:
            await self.process_commands(message)
            return

        # No link detected
        if not self.contains_link(message):
            await self.process_commands(message)
            return

        # Allowed channel
        if message.channel.id == ALLOWED_CHANNEL_ID:
            await self.process_commands(message)
            return

        # Delete message
        try:
            await message.delete()
        except:
            pass

        user_id = message.author.id
        now = datetime.now(UTC)
        last_time = self.last_link_time.get(user_id)

        # ==========================
        # First Warning
        # ==========================
        if not last_time:
            self.last_link_time[user_id] = now

            embed = discord.Embed(
                title="⚠️ تحذير | Warning",
                description=f"""**{message.author.mention} نشر الروابط ممنوع.**
Links are not allowed.

المرة القادمة سيتم اسكاتك لمدة ساعة.
Next time you will be muted for 1 hour.""",
                color=0xF1C40F
            )

            await message.channel.send(embed=embed)
            return

        # ==========================
        # Timeout
        # ==========================
        if (now - last_time) <= timedelta(hours=1):
            try:
                until_time = utcnow() + timedelta(hours=1)
                await message.author.timeout(until_time, reason="Repeated link posting")

                embed = discord.Embed(
                    title="⛔ تم اسكاتك | You Have Been Muted",
                    description=f"""**{message.author.mention} تم اسكاتك لمدة ساعة.**
You have been muted for 1 hour.

بسبب تكرار نشر الروابط.
For repeatedly posting links.""",
                    color=0xE74C3C
                )

                await message.channel.send(embed=embed)

            except Exception as e:
                print("Timeout error:", e)

            del self.last_link_time[user_id]

        else:
            self.last_link_time[user_id] = now

        await self.process_commands(message)

# ==============================
# Run Bot
# ==============================

bot = MyBot()

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
