import discord
import io
import datetime
import re
from collections import defaultdict, deque
from PIL import Image
import imagehash
import aiohttp
from redbot.core import commands, Config
from redbot.core.bot import Red

class ServerGuard(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543213, force_registration=True)
        default_guild = {
            "log_channel": None,
            "mod_role": None,
            "blacklisted_hashes": [],
            "threshold": 5
        }
        self.config.register_guild(**default_guild)
        self.user_channel_history = defaultdict(set)
        self.user_timestamps = defaultdict(deque)
        self.invite_pattern = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li|com/invite)|discord(?:app)?\.com/invite)/\w+")

    async def red_delete_data_for_the_user(self, **kwargs):
        return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if message.author.guild_permissions.manage_messages:
            return

        has_image = bool(message.attachments)
        has_invite = bool(self.invite_pattern.search(message.content))

        if not has_image and not has_invite:
            return

        guild = message.guild
        blacklisted_hexes = await self.config.guild(guild).blacklisted_hashes()
        threshold = await self.config.guild(guild).threshold()
        matched = False
        best_diff = 999

        if has_image:
            for attachment in message.attachments:
                if not attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
                    continue
                try:
                    image_bytes = await attachment.read()
                    image = Image.open(io.BytesIO(image_bytes))
                    incoming_hash = imagehash.phash(image)

                    for bad_hex in blacklisted_hexes:
                        bad_hash = imagehash.hex_to_hash(bad_hex)
                        diff = incoming_hash - bad_hash
                        if diff <= threshold:
                            matched = True
                            best_diff = min(best_diff, diff)
                except Exception:
                    continue

        if has_invite and not blacklisted_hexes:
            matched = True

        if matched or (has_image and has_invite):
            await self.handle_scam_attempt(message, best_diff if best_diff != 999 else 0, has_invite)

    async def handle_scam_attempt(self, message: discord.Message, diff_score: int, has_invite: bool):
        guild = message.guild
        member = message.author
        channel = message.channel

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        accessible_channels = [
            c for c in guild.text_channels 
            if c.permissions_for(member).send_messages and c.permissions_for(member).read_messages
        ]
        total_accessible = len(accessible_channels)

        user_id = member.id
        self.user_channel_history[user_id].add(channel.id)
        channels_ratio = len(self.user_channel_history[user_id]) / max(total_accessible, 1)
        channel_score = min(channels_ratio * 30.0, 30.0)

        now = datetime.datetime.now(datetime.timezone.utc)
        timestamps = self.user_timestamps[user_id]
        timestamps.append(now)
        while timestamps and (now - timestamps[0]).total_seconds() > 30:
            timestamps.popleft()

        frequency_count = len(timestamps)
        frequency_score = min((frequency_count / 5.0) * 30.0, 30.0)

        similarity_ratio = max(0.0, 1.0 - (diff_score / 15.0))
        similarity_score = similarity_ratio * 20.0 if diff_score > 0 else 20.0

        invite_score = 20.0 if has_invite else 0.0

        total_risk = round(min(channel_score + frequency_score + similarity_score + invite_score, 100.0), 2)

        log_channel_id = await self.config.guild(guild).log_channel()
        mod_role_id = await self.config.guild(guild).mod_role()
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return

        embed = discord.Embed(
            title="🚨 Scam / Phishing Attempt Blocked",
            description=(
                f"**User:** {member.mention} (`{member.id}`)\n"
                f"**Channel:** {channel.mention}\n"
                f"**Risk Factor:** `{total_risk}%`\n"
                f"**Discord Invite Detected:** `{'Yes' if has_invite else 'No'}`\n"
                f"**Match Distance:** `{diff_score}`"
            ),
            color=discord.Color.red(),
            timestamp=message.created_at
        )
        if message.attachments:
            embed.set_thumbnail(url=message.attachments[0].url)
        embed.add_field(name="Action Taken", value="Message deleted. No timeout applied.")

        role_ping = f"<@&{mod_role_id}>" if mod_role_id else "⚠️ Staff Alert:"
        await log_channel.send(content=f"{role_ping} Potential compromised account detected[cite: 1, 2].", embed=embed)

    @commands.group(name="serverguard", aliases=["sguard"])
    @commands.admin_or_permissions(manage_guild=True)
    async def serverguard(self, ctx: commands.Context):
        pass

    @serverguard.command(name="setlog")
    async def setlog(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"✅ Log channel set to {channel.mention}.")

    @serverguard.command(name="setmodrole")
    async def setmodrole(self, ctx: commands.Context, role: discord.Role):
        await self.config.guild(ctx.guild).mod_role.set(role.id)
        await ctx.send(f"✅ Moderator role set to {role.mention}.")

    @serverguard.command(name="addhash")
    async def addhash(self, ctx: commands.Context, image_url: str = None):
        target_url = image_url
        if not target_url and ctx.message.attachments:
            target_url = ctx.message.attachments[0].url

        if not target_url:
            await ctx.send("❌ Please provide an image URL or attach an image to add.")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(target_url) as resp:
                    if resp.status != 200:
                        await ctx.send("❌ Failed to download the image.")
                        return
                    data = await resp.read()
            
            image = Image.open(io.BytesIO(data))
            new_hash = str(imagehash.phash(image))

            async with self.config.guild(ctx.guild).blacklisted_hashes() as hashes:
                if new_hash in hashes:
                    await ctx.send("⚠️ This exact image hash is already in the blacklist.")
                    return
                hashes.append(new_hash)

            await ctx.send(f"✅ Successfully added image hash to blacklist: `{new_hash}`")
        except Exception as e:
            await ctx.send(f"❌ Error processing image: {e}")

    @serverguard.command(name="listhashes")
    async def listhashes(self, ctx: commands.Context):
        hashes = await self.config.guild(ctx.guild).blacklisted_hashes()
        if not hashes:
            await ctx.send("ℹ️ No blacklisted image hashes configured for this server.")
            return
        
        hash_list = "\n".join([f"`{h}`" for h in hashes])
        embed = discord.Embed(title="🛡️ Blacklisted Image Hashes", description=hash_list, color=discord.Color.blue())
        await ctx.send(embed=embed)

async def setup(bot: Red):
    await bot.add_cog(ServerGuard(bot))
