import discord
from redbot.core import commands, Config, modlog
from discord.ext import tasks
from discord import app_commands
import datetime
import time
import uuid
import typing
import re

DISCORD_MSG_LINK_REGEX = re.compile(
    r"https?://(?:canary\.|ptb\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)"
)

def format_proof_display(embed: discord.Embed, proof: str):
    if not proof or proof == "None Provided":
        return
    
    match = DISCORD_MSG_LINK_REGEX.search(proof)
    if match:
        guild_id, channel_id, message_id = match.groups()
        embed.add_field(
            name="Proof / Evidence",
            value=f"[Message Link](https://discord.com/channels/{guild_id}/{channel_id}/{message_id}) (<#{channel_id}>)",
            inline=False
        )
    else:
        embed.set_image(url=proof)
        embed.add_field(name="Proof Link", value=f"<{proof}>", inline=False)

class BanConflictView(discord.ui.View):
    def __init__(self, cog, target: typing.Union[discord.Member, discord.User], moderator: typing.Union[discord.Member, discord.User], new_action_type: str, reason: str, proof: str, temp_duration: int = None, appealable: bool = True):
        super().__init__(timeout=60)
        self.cog = cog
        self.target = target
        self.moderator = moderator
        self.new_action_type = new_action_type
        self.reason = reason
        self.proof = proof
        self.temp_duration = temp_duration
        self.appealable = appealable

    @discord.ui.button(label="Confirm & Override Ban", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.moderator.id:
            return await interaction.response.send_message("❌ You are not authorized to confirm this action.", ephemeral=True)
            
        await interaction.response.defer()
        
        async with self.cog.config.guild(interaction.guild).pending_appeals() as appeals:
            self.cog.config.guild(interaction.guild).pending_appeals.set([a for a in appeals if a["user_id"] != self.target.id])

        if self.new_action_type == "tempban":
            await self.cog._execute_ban_action(interaction.guild, self.target, self.moderator, self.reason, self.proof, appealable=self.appealable, temp_duration=self.temp_duration, is_override=True)
            await interaction.followup.send(f"✅ Adjusted ban for **{self.target}** to a Temporary Ban ({self.temp_duration} seconds).")
        else:
            await self.cog._execute_ban_action(interaction.guild, self.target, self.moderator, self.reason, self.proof, appealable=self.appealable, temp_duration=None, is_override=True)
            await interaction.followup.send(f"✅ Adjusted ban for **{self.target}** to a Permanent Ban.")
            
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.moderator.id:
            return await interaction.response.send_message("❌ You are not authorized to perform this action.", ephemeral=True)
            
        await interaction.response.send_message("Action canceled. No changes made to the user's ban status.", ephemeral=True)
        self.stop()


class DynamicRequestView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="advmod:approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild: return
        
        active_reqs = await self.cog.config.guild(guild).active_requests()
        req_id = None
        for r_id, data in active_reqs.items():
            if data["message_id"] == interaction.message.id:
                req_id = r_id
                break
                
        if not req_id:
            return await interaction.response.send_message("This request is expired, invalid, or has already been processed.", ephemeral=True)
            
        req = active_reqs[req_id]
        req_type = req["type"]
        
        if "kick" in req_type:
            if not await self.cog._has_level_member(guild, interaction.user, 2):
                return await interaction.response.send_message("❌ Hierarchy Denied: You must be Class II+ to approve a kick request.", ephemeral=True)
        elif "ban" in req_type:
            if not await self.cog._has_level_member(guild, interaction.user, 3):
                return await interaction.response.send_message("❌ Hierarchy Denied: You must be Class III+ to approve a ban request.", ephemeral=True)
        elif "review" in req_type:
            if not await self.cog._has_level_member(guild, interaction.user, 5):
                return await interaction.response.send_message("❌ Hierarchy Denied: Only Directors can approve this action.", ephemeral=True)

        await interaction.response.defer()

        target_id = req["target"]
        target = guild.get_member(target_id) or await self.cog.bot.fetch_user(target_id)
        reason = f"Request {req_id} approved by {interaction.user} | Original: {req['reason']}"
        proof = req["proof"]
        appealable = req.get("appealable", True)

        if "kick" in req_type:
            if isinstance(target, discord.Member):
                dm_embed = discord.Embed(title=f"Kicked from {guild.name}", description=f"**Reason:** {reason}", color=discord.Color.red())
                await self.cog._dm_user(target, dm_embed, tag_user=True)
                try:
                    await target.kick(reason=reason)
                except discord.HTTPException:
                    pass
            await self.cog.log_immediate_action(guild, "Kick", target, interaction.user, reason, proof, appealable=appealable)
        elif "ban" in req_type:
            duration = req.get("duration", None)
            await self.cog._process_ban(guild, target, interaction.user, reason, proof, appealable=appealable, temp_duration=duration)

        disabled_view = discord.ui.View(timeout=None)
        disabled_view.add_item(discord.ui.Button(label="Approved", style=discord.ButtonStyle.green, disabled=True))

        log_embed = discord.Embed(title=f"✅ Mod Action: {req_type.title()} (Approved)", color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
        log_embed.add_field(name="Target", value=f"{target.mention if hasattr(target, 'mention') else 'Unknown'} ({target_id})", inline=False)
        log_embed.add_field(name="Requested By", value=f"<@{req['author']}>", inline=True)
        log_embed.add_field(name="Approved By", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        log_embed.add_field(name="Appealable", value="Yes" if appealable else "No", inline=True)
        if "duration_str" in req:
            log_embed.add_field(name="Duration", value=req["duration_str"], inline=True)
            
        if proof and proof != "None Provided":
            format_proof_display(log_embed, proof)

        await interaction.message.edit(content=None, embed=log_embed, view=disabled_view)

        async with self.cog.config.guild(guild).active_requests() as data:
            if req_id in data: del data[req_id]

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="advmod:deny")
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild: return
        
        if not await self.cog._has_level_member(guild, interaction.user, 2):
            return await interaction.response.send_message("❌ Hierarchy Denied: You must be Class II+ to deny requests.", ephemeral=True)
            
        active_reqs = await self.cog.config.guild(guild).active_requests()
        req_id = None
        for r_id, data in active_reqs.items():
            if data["message_id"] == interaction.message.id:
                req_id = r_id
                break
                
        if not req_id:
            return await interaction.response.send_message("This request has already been processed.", ephemeral=True)

        req = active_reqs[req_id]
        
        disabled_view = discord.ui.View(timeout=None)
        disabled_view.add_item(discord.ui.Button(label="Denied", style=discord.ButtonStyle.danger, disabled=True))

        deny_embed = discord.Embed(title=f"❌ Mod Request: {req['type'].title()} (Denied)", color=discord.Color.greyple(), timestamp=datetime.datetime.now(datetime.timezone.utc))
        deny_embed.add_field(name="Target ID", value=str(req['target']), inline=False)
        deny_embed.add_field(name="Requested By", value=f"<@{req['author']}>", inline=True)
        deny_embed.add_field(name="Denied By", value=interaction.user.mention, inline=True)
        
        await interaction.response.edit_message(content=None, embed=deny_embed, view=disabled_view)

        async with self.cog.config.guild(guild).active_requests() as data:
            if req_id in data: del data[req_id]


class AdvancedMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9485739485, force_registration=True)
        
        default_guild = {
            "mod_channel": None,
            "appeal_link": None,
            "base_mod_role": None,
            "class_1_role": None,
            "class_2_role": None,
            "class_3_role": None,
            "manager_role": None,
            "director_role": None,
            "pending_appeals": [],      
            "active_requests": {},     
            "punishments": {           
                "3": {"action": "timeout", "duration": 60},   
                "5": {"action": "kick", "duration": None}     
            }
        }
        default_member = {"warnings": []}
        
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)
        self.appeal_notifier.start()

    async def cog_load(self):
        self.bot.add_view(DynamicRequestView(self))

    def cog_unload(self):
        self.appeal_notifier.cancel()

    async def _has_level_member(self, guild: discord.Guild, member: discord.Member, level: int) -> bool:
        if member.guild_permissions.administrator:
            return True
            
        roles = await self.config.guild(guild).all()
        user_role_ids = [r.id for r in member.roles]
        
        levels = {
            1: [roles["class_1_role"], roles["class_2_role"], roles["class_3_role"], roles["manager_role"], roles["director_role"]],
            2: [roles["class_2_role"], roles["class_3_role"], roles["manager_role"], roles["director_role"]],
            3: [roles["class_3_role"], roles["manager_role"], roles["director_role"]],
            4: [roles["manager_role"], roles["director_role"]],
            5: [roles["director_role"]]
        }
        allowed_roles = [r for r in levels[level] if r is not None]
        return any(role_id in allowed_roles for role_id in user_role_ids)

    async def _has_level(self, ctx: commands.Context, level: int) -> bool:
        return await self._has_level_member(ctx.guild, ctx.author, level)

    async def _is_allowed_to_moderate(self, ctx: commands.Context, target: typing.Union[discord.Member, discord.User]) -> typing.Tuple[bool, str]:
        if ctx.author.id == target.id:
            return False, "❌ Safeguard Violation: You cannot execute moderation sequences against yourself."
        if target.id == ctx.guild.me.id:
            return False, "❌ Safeguard Violation: Systems are hard-locked against processing internal loops on the bot client."
        if target.id == ctx.guild.owner_id:
            return False, "❌ Safeguard Violation: Server ownership profiles are strictly immune to administrative overrides."
            
        if isinstance(target, discord.Member):
            if ctx.author != ctx.guild.owner and target.top_role >= ctx.author.top_role:
                return False, "❌ Hierarchy Refusal: Target holds an equal or superior role position within Discord's native hierarchy."
                
            mod_level = 0
            target_level = 0
            for lvl in range(1, 6):
                if await self._has_level_member(ctx.guild, ctx.author, lvl):
                    mod_level = lvl
                if await self._has_level_member(ctx.guild, target, lvl):
                    target_level = lvl
                    
            if ctx.author != ctx.guild.owner and target_level >= mod_level and target_level > 0:
                return False, f"❌ Hierarchy Refusal: Target holds an authorized internal clearance rank equal to or higher than yours (Your Level: Class {mod_level} | Target Level: Class {target_level})."

        return True, ""

    def _get_proof(self, proof_link: str = None, attachment: discord.Attachment = None) -> str:
        if attachment:
            return attachment.url
        return proof_link if proof_link else "None Provided"

    def _parse_duration(self, duration_str: str) -> typing.Optional[int]:
        if not duration_str:
            return None
        duration_str = duration_str.lower().strip()
        if duration_str in ["permanent", "perm", "infinite", "none", "0"]:
            return None
        
        match = re.match(r"^(\d+)([dhms])$", duration_str)
        if match:
            value, unit = int(match.group(1)), match.group(2)
            if unit == "s": return value
            if unit == "m": return value * 60
            if unit == "h": return value * 3600
            if unit == "d": return value * 86400
            
        try:
            val = int(duration_str)
            return val * 86400 
        except ValueError:
            return None

    async def _dm_user(self, target: typing.Union[discord.Member, discord.User], embed: discord.Embed, tag_user: bool = False):
        try:
            content = target.mention if tag_user else None
            await target.send(content=content, embed=embed)
        except discord.Forbidden:
            pass

    async def log_immediate_action(self, guild: discord.Guild, action: str, target: typing.Union[discord.Member, discord.User], moderator: typing.Union[discord.Member, discord.User], reason: str, proof: str, duration_minutes: int = None, duration_days: int = None, duration_str: str = None, appealable: bool = True):
        channel_id = await self.config.guild(guild).mod_channel()
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                embed = discord.Embed(title=f"⚡ Mod Action: {action}", color=discord.Color.red(), timestamp=datetime.datetime.now(datetime.timezone.utc))
                embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
                embed.add_field(name="Moderator", value=f"{moderator.mention} ({moderator.id})", inline=False)
                embed.add_field(name="Reason", value=reason, inline=False)
                if duration_minutes: embed.add_field(name="Duration", value=f"{duration_minutes} Minutes", inline=True)
                if duration_days: embed.add_field(name="Duration", value=f"{duration_days} Days", inline=True)
                if duration_str: embed.add_field(name="Duration", value=duration_str, inline=True)
                embed.add_field(name="Appealable", value="Yes" if appealable else "No", inline=True)
                if proof and proof != "None Provided":
                    format_proof_display(embed, proof)
                await channel.send(embed=embed)

        action_lower = action.lower()
        modlog_type = None
        until_time = None

        if "warn" in action_lower:
            modlog_type = "warning"
        elif "timeout" in action_lower:
            modlog_type = "timeout"
            if duration_minutes:
                until_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=duration_minutes)
        elif "kick" in action_lower:
            modlog_type = "kick"
        elif "tempban" in action_lower or "duration" in action_lower:
            modlog_type = "tempban"
            if duration_days:
                until_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=duration_days)
        elif "ban" in action_lower:
            modlog_type = "ban"

        if modlog_type:
            try:
                await modlog.create_case(
                    bot=self.bot,
                    guild=guild,
                    created_at=datetime.datetime.now(datetime.timezone.utc),
                    action_type=modlog_type,
                    user=target,
                    moderator=moderator,
                    reason=f"{reason} | Evidence: {proof} | Appealable: {appealable}",
                    until=until_time
                )
            except Exception:
                pass

    async def create_request(self, ctx: commands.Context, req_type: str, target: typing.Union[discord.Member, discord.User], reason: str, proof: str, ping_level: int, extra_data: dict = None, appealable: bool = True):
        channel_id = await self.config.guild(ctx.guild).mod_channel()
        if not channel_id: return
        channel = ctx.guild.get_channel(channel_id)
        if not channel: return

        req_id = str(uuid.uuid4())[:8]
        roles = await self.config.guild(ctx.guild).all()
        
        ping_role_id = None
        if ping_level == 2: ping_role_id = roles["class_2_role"]
        elif ping_level == 3: ping_role_id = roles["class_3_role"]
        elif ping_level == 5: ping_role_id = roles["director_role"]
        
        ping_mention = f"<@&{ping_role_id}>" if ping_role_id else "Administrators"

        embed = discord.Embed(title=f"⏳ Pending Request: {req_type.title()}", description=f"ID: `{req_id}`\nReview the details below and select an action.", color=discord.Color.orange())
        embed.add_field(name="Target", value=f"{target.mention} ({target.id})", inline=False)
        embed.add_field(name="Requested By", value=ctx.author.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Appealable", value="Yes" if appealable else "No", inline=True)
        if extra_data:
            for k, v in extra_data.items():
                embed.add_field(name=k.replace("_", " ").title(), value=str(v), inline=True)
        
        if proof and
