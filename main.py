import discord
from discord.ext import commands, tasks
import os
import asyncio
import re
import unicodedata
from datetime import datetime, timedelta, UTC
from discord.utils import utcnow

# --- إعداد البوت ---
ALLOWED_CHANNEL_ID = 1403040565137899733
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Missing DISCORD_BOT_TOKEN in environment variables")

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.last_link_time = {}

    # 🔹 تحديث الحالة الدورية
    @tasks.loop(minutes=10)
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

    # 🔹 تنظيف النصوص
    def normalize_text(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = text.lower().replace("ـ", "")
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"(.)\1{2,}", r"\1", text)
        return text

    # 🔹 كشف الروابط
    def contains_link(self, message: discord.Message) -> bool:
        spotify_whitelist = ["spotify.com", "open.spotify.com", "spotify.link"]
        shorteners = [
            "bit.ly", "tinyurl.com", "t.co", "goo.gl",
            "is.gd", "cutt.ly", "rebrand.ly", "shorturl.at"
        ]

        full_content = message.content
        for embed in message.embeds:
            if embed.url:
                full_content += " " + embed.url
            if embed.description:
                full_content += " " + embed.description
            if embed.title:
                full_content += " " + embed.title

        content = self.normalize_text(full_content)

        # Markdown links
        markdown_links = re.findall(r"\[.*?\]\((.*?)\)", full_content)
        for link in markdown_links:
            if not any(domain in self.normalize_text(link) for domain in spotify_whitelist):
                return True

        patterns = [
            r"h\s*t\s*t\s*p\s*s?\s*:\s*/\s*/",
            r"w\s*w\s*w\s*\.",
            r"https?://",
            r"[a-z0-9\-]+\.(com|net|org|gg|io|me|co|xyz|info|app|site|store|online|tech|dev|link)",
            r"d\s*i\s*s\s*c\s*o\s*r\s*d\s*\.\s*g\s*g"
        ]

        for pat in patterns:
            if re.search(pat, content):
                return True

        for short in shorteners:
            if short in content:
                return True

        for attachment in message.attachments:
            if re.search(patterns[3], self.normalize_text(attachment.filename)):
                return True

        return False

    # --- التعامل مع الرسائل ---
    async def on_message(self, message):
        if message.author.bot:
            return

        user_id = message.author.id
        now = datetime.now(UTC)

        if not any(role.permissions.manage_messages for role in message.author.roles):
            if self.contains_link(message):
                if message.channel.id == ALLOWED_CHANNEL_ID:
                    try:
                        await asyncio.sleep(5)
                        await message.delete()
                    except:
                        pass
                    return
                try:
                    await message.delete()
                except:
                    pass

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
                            description=f"{message.author.mention} تم اسكاتك بسبب تكرار نشر الروابط",
                            color=0xFF0000
                        )
                        await message.channel.send(embed=embed)
                    except Exception as e:
                        print("⚠️ Timeout error:", e)
                self.last_link_time[user_id] = None

        await self.process_commands(message)


# --- تشغيل البوت ---
bot = MyBot()

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())

