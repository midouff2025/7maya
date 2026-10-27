import discord
from discord.ext import commands, tasks
from flask import Flask
import os
import json
import asyncio
import threading
import re
import unicodedata
import aiohttp
from datetime import datetime, timedelta, UTC
from discord.utils import utcnow

# =========================
# الإعدادات
# =========================

TOKEN = os.environ.get("DISCORD")
ALLOWED_CHANNEL_ID = 1403040565137899733

# ضع رابط الريندر هنا
SELF_PING_URL = "https://midou-cheat.onrender.com"  # <-- عدل هذا

# ملف حفظ التحذيرات / الإعدادات / أوقات العقوبات
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "warnings.json")

if not TOKEN:
    raise ValueError("Missing DISCORD in environment variables")

# =========================
# حفظ البيانات (warnings.json)
# =========================

class Store:

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {
            "last_link": {},       # user_id -> وقت آخر رابط
            "last_everyone": {},   # user_id -> وقت آخر منشن عام
            "warns": {},           # user_id -> {count, history}
            "guilds": {},          # guild_id -> {log_channel, allowed_channels}
        }
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            for k in self.data:
                if isinstance(d.get(k), dict):
                    self.data[k] = d[k]
            print("Store loaded:", self.path)
        except FileNotFoundError:
            print("Store: new file will be created ->", self.path)
        except Exception as e:
            print("Store load failed:", e)

    def save(self):
        try:
            with self.lock:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
        except Exception as e:
            print("Store save failed:", e)

    # ---------- إعدادات السيرفر ----------
    def guild(self, guild_id):
        g = self.data["guilds"].setdefault(str(guild_id), {})
        g.setdefault("log_channel", None)
        g.setdefault("allowed_channels", [])
        return g

    def allowed_channels(self, guild_id):
        if guild_id is None:
            return []
        return self.guild(guild_id)["allowed_channels"]

    def is_allowed_channel(self, guild_id, channel_id):
        if channel_id == ALLOWED_CHANNEL_ID:
            return True
        return channel_id in self.allowed_channels(guild_id)

    # ---------- أوقات العقوبات ----------
    def load_times(self, key):
        out = {}
        for uid, iso in self.data.get(key, {}).items():
            try:
                out[int(uid)] = datetime.fromisoformat(iso)
            except Exception:
                pass
        return out

    def save_time(self, key, user_id, when):
        self.data[key][str(user_id)] = when.isoformat()
        self.save()

    # ---------- التحذيرات ----------
    def add_warn(self, guild_id, user_id, reason, moderator_id):
        w = self.data["warns"].setdefault(str(user_id), {"count": 0, "history": []})
        w.setdefault("history", [])
        w["count"] += 1
        w["history"].append({
            "guild": str(guild_id),
            "reason": reason,
            "moderator": str(moderator_id),
            "at": datetime.now(UTC).isoformat(),
        })
        self.save()
        return w["count"]

    def warn_count(self, user_id):
        return self.data["warns"].get(str(user_id), {}).get("count", 0)


# =========================
# Flask Server
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# =========================
# Discord Bot
# =========================

class MyBot(commands.Bot):

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(command_prefix="!", intents=intents)

        self.store = Store(DATA_FILE)
        self.last_link_time = self.store.load_times("last_link")
        self.last_everyone_time = self.store.load_times("last_everyone")

    async def setup_hook(self):
        self.update_status.start()
        self.self_ping.start()

        # تسجيل أوامر السلاش
        try:
            self.tree.on_error = self.on_tree_error
            await self.tree.sync()
            print("Slash commands synced")
        except Exception as e:
            print("Slash sync failed:", e)

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})")
        print(f"Guilds: {len(self.guilds)}")

    # =========================
    # تحديث الحالة
    # =========================

    @tasks.loop(minutes=10)
    async def update_status(self):
        try:
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers"
            )
            await self.change_presence(activity=activity)
        except Exception as e:
            print("Status update failed:", e)

    @update_status.before_loop
    async def before_status_update(self):
        await self.wait_until_ready()

    # =========================
    # Self Ping كل 5 دقائق
    # =========================

    @tasks.loop(minutes=5)
    async def self_ping(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(SELF_PING_URL) as resp:
                    print("Self Ping Status:", resp.status)
        except Exception as e:
            print("Self Ping Failed:", e)

    @self_ping.before_loop
    async def before_self_ping(self):
        await self.wait_until_ready()

    # =========================
    # تنظيف النصوص
    # =========================

    def normalize_text(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = text.lower().replace("ـ", "")
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"(.)\1{2,}", r"\1", text)
        return text

    # =========================
    # كشف الروابط
    # =========================

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

    # =========================
    # أدوات مساعدة
    # =========================

    def is_mod(self, member) -> bool:
        """بديل آمن لـ message.author.roles (يشتغل حتى لو الكاتب User مو Member)."""
        return isinstance(member, discord.Member) and member.guild_permissions.manage_messages

    def mentions_everyone(self, message: discord.Message) -> bool:
        content = (message.content or "").lower()
        return message.mention_everyone or "@everyone" in content or "@here" in content

    async def send_log(self, guild, title, description, color, fields=None):
        """إرسال لوق لقناة اللوقز المحددة في السيرفر."""
        if guild is None:
            return

        ch_id = self.store.guild(guild.id)["log_channel"]
        if not ch_id:
            return

        channel = guild.get_channel(ch_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(ch_id)
            except Exception:
                return

        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(UTC)
        )
        for name, value in (fields or []):
            embed.add_field(name=name, value=value, inline=True)

        embed.set_footer(text=f"MIDOU GUARD • {guild.name}")

        try:
            await channel.send(embed=embed)
        except Exception as e:
            print("Log send failed:", e)

    # =========================
    # التعامل مع الرسائل
    # =========================

    async def on_message(self, message):
        if message.author.bot:
            return

        user_id = message.author.id
        now = datetime.now(UTC)

        is_mod = self.is_mod(message.author)

        if not is_mod:
            if self.contains_link(message):

                if self.store.is_allowed_channel(message.guild.id if message.guild else None, message.channel.id):
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
                    self.store.save_time("last_link", user_id, now)

                    embed = discord.Embed(
                        title="⚠️ تحذير من الروابط",
                        description=f"{message.author.mention} نشر الروابط ممنوع. المرة القادمة سيتم اسكاتك.",
                        color=0xFFFF00
                    )
                    await message.channel.send(embed=embed)

                    await self.send_log(
                        message.guild,
                        "⚠️ تحذير — نشر رابط",
                         f"{message.author.mention} نشر رابط في {message.channel.mention}",
                        0xFFFF00,
                        [
                            ("العضو", f"{message.author} (`{message.author.id}`)"),
                            ("القناة", message.channel.mention),
                            ("العقوبة", "تحذير أول"),
                        ]
                    )

                else:
                    try:
                        if not isinstance(message.author, discord.Member):
                            raise RuntimeError("author is not a guild member")

                        until_time = utcnow() + timedelta(hours=1)
                        await message.author.timeout(until_time, reason="نشر روابط")

                        embed = discord.Embed(
                            title="⛔ تم اسكاتك",
                            description=f"{message.author.mention} تم اسكاتك بسبب تكرار نشر الروابط",
                            color=0xFF0000
                        )
                        await message.channel.send(embed=embed)

                        await self.send_log(
                            message.guild,
                            "⛔ تايم أوت — تكرار الروابط",
                            f"{message.author.mention} تم اسكاته في {message.channel.mention}",
                            0xFF0000,
                            [
                                ("العضو", f"{message.author} (`{message.author.id}`)"),
                                ("القناة", message.channel.mention),
                                ("العقوبة", "اسكات 1 ساعة"),
                            ]
                        )

                    except Exception as e:
                        print("Timeout error:", e)

                self.last_link_time[user_id] = now
                self.store.save_time("last_link", user_id, now)

        # ---- مراقبة المنشن العام (@everyone / @here) ----
        if not is_mod and self.mentions_everyone(message):
            await self.handle_everyone(message)

        await self.process_commands(message)

    # =========================
    # مراقبة @everyone
    # =========================

    async def handle_everyone(self, message):
        now = datetime.now(UTC)

        try:
            await message.delete()
        except:
            pass

        last_time = self.last_everyone_time.get(message.author.id)
        first_time = (not last_time) or ((now - last_time) > timedelta(hours=1))

        self.last_everyone_time[message.author.id] = now
        self.store.save_time("last_everyone", message.author.id, now)

        if first_time:
            embed = discord.Embed(
                title="📢 المنشن العام ممنوع",
                description=f"{message.author.mention} استخدام `@everyone` / `@here` ممنوع. المرة القادمة سيتم اسكاتك.",
                color=0xFFFF00
            )
            await message.channel.send(embed=embed)

            await self.send_log(
                message.guild,
                "⚠️ تحذير — منشن عام",
                f"{message.author.mention} استخدم منشن عام في {message.channel.mention}",
                0xFFFF00,
                [
                    ("العضو", f"{message.author} (`{message.author.id}`)"),
                    ("القناة", message.channel.mention),
                    ("العقوبة", "تحذير أول"),
                ]
            )
            return

        try:
            if not isinstance(message.author, discord.Member):
                raise RuntimeError("author is not a guild member")

            until_time = utcnow() + timedelta(hours=1)
            await message.author.timeout(until_time, reason="تكرار استخدام @everyone / @here")

            embed = discord.Embed(
                title="⛔ تم اسكاتك",
                description=f"{message.author.mention} تم اسكاتك ساعة بسبب تكرار المنشن العام",
                color=0xFF0000
            )
            await message.channel.send(embed=embed)

            await self.send_log(
                message.guild,
                "⛔ تايم أوت — تكرار منشن عام",
                f"{message.author.mention} تم اسكاته في {message.channel.mention}",
                0xFF0000,
                [
                    ("العضو", f"{message.author} (`{message.author.id}`)"),
                    ("القناة", message.channel.mention),
                    ("العقوبة", "اسكات 1 ساعة"),
                ]
            )

        except Exception as e:
            print("Timeout error:", e)

    # =========================
    # الأوامر
    # =========================

    @commands.command(name="help", help="عرض كل الأوامر المتاحة")
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="📖 قائمة الأوامر",
            description="كل الأوامر المتاحة في البوت",
            color=0x2ECC71
        )

        for cmd in sorted(self.commands, key=lambda c: c.name):
            if cmd.hidden:
                continue
            sig = f"{ctx.prefix}{cmd.name} {cmd.signature}".strip()
            embed.add_field(name=f"`{sig}`", value=cmd.help or "—", inline=False)

        embed.set_footer(text="MIDOU GUARD")
        await ctx.send(embed=embed)

    @commands.command(name="warn", help="تحذير عضو: !warn @user السبب")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = "بدون سبب"):
        count = self.store.add_warn(
            ctx.guild.id if ctx.guild else 0,
            member.id,
            reason,
            ctx.author.id
        )

        embed = discord.Embed(
            title="⚠️ تحذير",
            description=f"{member.mention} تم تحذيره بواسطة {ctx.author.mention}",
            color=0xFFFF00
        )
        embed.add_field(name="السبب", value=reason, inline=False)
        embed.add_field(name="عدد التحذيرات", value=str(count), inline=True)

        await ctx.send(embed=embed)

        await self.send_log(
            ctx.guild,
            "⚠️ تحذير عضو",
            f"{member.mention} تم تحذيره بواسطة {ctx.author.mention}",
            0xFFFF00,
            [
                ("العضو", f"{member} (`{member.id}`)"),
                ("بواسطة", f"{ctx.author} (`{ctx.author.id}`)"),
                ("السبب", reason),
                ("العدد", str(count)),
            ]
        )

        try:
            await member.send(
                f"⚠️ تم تحذيرك في **{ctx.guild.name}**\n"
                f"السبب: {reason}\n"
                f"عدد تحذيراتك: {count}"
            )
        except:
            pass

    @commands.command(name="warns", help="عرض تحذيرات عضو: !warns @user")
    async def warns(self, ctx, member: discord.Member):
        count = self.store.warn_count(member.id)
        embed = discord.Embed(
            title="📋 سجل التحذيرات",
            description=f"{member.mention} لديه **{count}** تحذير",
            color=0x3498DB
        )
        await ctx.send(embed=embed)

    @commands.command(name="clear", help="حذف رسائل: !clear 50")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 10):
        amount = max(1, min(amount, 100))

        try:
            deleted = await ctx.channel.purge(limit=amount + 1)
        except Exception as e:
            print("Purge error:", e)
            await ctx.send(embed=discord.Embed(
                title="⛔ فشل الحذف",
                description="تأكد أن البوت يملك صلاحية **Manage Messages**.",
                color=0xFF0000
            ))
            return

        real = max(0, len(deleted) - 1)

        embed = discord.Embed(
            title="🧹 تم التنظيف",
            description=f"تم حذف **{real}** رسالة بواسطة {ctx.author.mention}",
            color=0x2ECC71
        )
        msg = await ctx.send(embed=embed)

        await self.send_log(
            ctx.guild,
            "🧹 تنظيف رسائل",
            f"{ctx.author.mention} حذف **{real}** رسالة في {ctx.channel.mention}",
            0x2ECC71,
            [
                ("بواسطة", f"{ctx.author} (`{ctx.author.id}`)"),
                ("القناة", ctx.channel.mention),
                ("العدد", str(real)),
            ]
        )

        await asyncio.sleep(4)
        try:
            await msg.delete()
        except:
            pass

    @commands.hybrid_command(
        name="allowchannel",
        description="السماح بالروابط في قناة (تُحذف بعد 5 ثواني بدون عقوبة)"
    )
    @commands.has_permissions(manage_guild=True)
    async def allowchannel(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        cfg = self.store.guild(ctx.guild.id)

        if channel.id not in cfg["allowed_channels"]:
            cfg["allowed_channels"].append(channel.id)
            self.store.save()

        embed = discord.Embed(
            title="✅ قناة مسموحة",
            description=f"{channel.mention} صارت مسموحة للروابط\n"
                        f"الروابط فيها تُحذف بعد 5 ثواني بدون أي عقوبة.",
            color=0x2ECC71
        )
        await ctx.send(embed=embed)

        await self.send_log(
            ctx.guild,
            "✅ قناة مسموحة للروابط",
            f"{ctx.author.mention} أضاف {channel.mention}",
            0x2ECC71,
            [
                ("بواسطة", f"{ctx.author} (`{ctx.author.id}`)"),
                ("القناة", channel.mention),
            ]
        )

    @commands.hybrid_command(
        name="removechannel",
        description="إزالة قناة من قائمة المسموحة للروابط"
    )
    @commands.has_permissions(manage_guild=True)
    async def removechannel(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        cfg = self.store.guild(ctx.guild.id)

        if channel.id in cfg["allowed_channels"]:
            cfg["allowed_channels"].remove(channel.id)
            self.store.save()

        embed = discord.Embed(
            title="✅ تم الإزالة",
            description=f"{channel.mention} رجعت قناة عادية — الروابط فيها ممنوعة.",
            color=0x2ECC71
        )
        await ctx.send(embed=embed)

        await self.send_log(
            ctx.guild,
            "✅ إزالة قناة مسموحة",
            f"{ctx.author.mention} أزال {channel.mention}",
            0x2ECC71,
            [
                ("بواسطة", f"{ctx.author} (`{ctx.author.id}`)"),
                ("القناة", channel.mention),
            ]
        )

    @commands.command(name="setchannellogs", help="تحديد قناة اللوقز: !setchannellogs #logs")
    @commands.has_permissions(administrator=True)
    async def setchannellogs(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        cfg = self.store.guild(ctx.guild.id)
        cfg["log_channel"] = channel.id
        self.store.save()

        embed = discord.Embed(
            title="✅ قناة اللوقز",
            description=f"تم تحديد {channel.mention} كقناة لوقز لهذا السيرفر.",
            color=0x2ECC71
        )
        await ctx.send(embed=embed)

        # رسالة تجريبية في قناة اللوقز
        await self.send_log(
            ctx.guild,
            "🔧 تم تفعيل اللوقز",
            f"هذه القناة صارت تستقبل كل أحداث الحماية.\nبواسطة {ctx.author.mention}",
            0x3498DB,
            [
                ("السيرفر", ctx.guild.name),
                ("بواسطة", f"{ctx.author} (`{ctx.author.id}`)"),
            ]
        )

    # =========================
    # معالجة الأخطاء
    # =========================

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=discord.Embed(
                title="⛔ صلاحيات غير كافية",
                description="ما عندك الصلاحية لاستخدام هذا الأمر.",
                color=0xFF0000
            ))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(
                title="⚠️ ناقص",
                description=f"استخدم: `{ctx.prefix}{ctx.command.name} {ctx.command.signature}`",
                color=0xFFFF00
            ))
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=discord.Embed(
                title="⚠️ عضو غير موجود",
                description="منشن العضو بشكل صحيح.",
                color=0xFFFF00
            ))
        elif isinstance(error, commands.CommandNotFound):
            return
        else:
            print("Command error:", error)

    # أخطاء أوامر السلاش (/) — لازم تكون منفصلة عن أخطاء البريفكس
    async def on_tree_error(self, interaction: discord.Interaction, error):
        if isinstance(error, commands.MissingPermissions):
            msg = "⛔ ما عندك الصلاحية لاستخدام هذا الأمر."
            color = 0xFF0000
        elif isinstance(error, commands.MemberNotFound):
            msg = "⚠️ العضو غير موجود — منشنه بشكل صحيح."
            color = 0xFFFF00
        elif isinstance(error, commands.MissingRequiredArgument):
            msg = f"⚠️ ناقص: `{error.param.name}`"
            color = 0xFFFF00
        elif isinstance(error, commands.BadArgument):
            msg = "⚠️ قيمة غير صحيحة — تأكد من المنشن أو القناة."
            color = 0xFFFF00
        elif isinstance(error, commands.CommandOnCooldown):
            msg = f"⏳ انتظر {error.retry_after:.1f} ثانية."
            color = 0xFFFF00
        else:
            print("Slash error:", error)
            msg = "⛔ صار خطأ غير متوقع."
            color = 0xFF0000

        embed = discord.Embed(title="خطأ", description=msg, color=color)

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            print("Tree error reply failed:", e)


# =========================
# التشغيل
# =========================

bot = MyBot()

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    asyncio.run(main())
