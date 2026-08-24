import discord
from redbot.core import commands, Config, modlog
from discord.ext import tasks
import datetime
import time
import uuid
import typing

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
        elif "tempban" in req_type:
            if not await self.cog._has_level_member(guild, interaction.user, 3):
                return await interaction.response.send_message("❌ Hierarchy Denied: You must be Class III+ to approve a temporary ban request.", ephemeral=True)
        elif "permban" in req_type:
            if not await self.cog._has_level_member(guild, interaction.user, 3):
                return await interaction.response.send_message("❌ Hierarchy Denied: You must be Class III+ to approve a permanent ban request.", ephemeral=True)
        elif "review" in req_type:
            if not await self.cog._has_level_member(guild, interaction.user, 5):
                return await interaction.response.send_message("❌ Hierarchy Denied: Only Directors can approve this action.", ephemeral=True)

        await interaction.response.defer()

        target_id = req["target"]
        target = guild.get_member(target_id) or await self.cog.bot.fetch_user(target_id)
        reason = f"Request {req_id} approved by {interaction.user} | Original: {req['reason']}"
        proof = req["proof"]

        if "kick" in req_type:
            if isinstance(target, discord.Member):
                dm_embed = discord.Embed(title=f"Kicked from {guild.name}", description=f"**Reason:** {reason}", color=discord.Color.red())
                await self.cog._dm_user(target, dm_embed, tag_user=True)
                try:
                    await target.kick(reason=reason)
                except discord.HTTPException:
                    pass
            await self.cog.log_immediate_action(guild, "Kick", target, interaction.user, reason, proof)
        elif "tempban" in req_type:
            days = req.get("duration_days", 14)
            await self.cog._process_ban(guild, target, interaction.user, reason, proof, appealable=True, temp_days=days)
        elif "ban" in req_type:
            await self.cog._process_ban(guild, target, interaction.user, reason, proof, appealable=True)

        disabled_view = discord.ui.View(timeout=None)
        disabled_view.add_item(discord.ui.Button(label="Approved", style=discord.ButtonStyle.green, disabled=True))

        log_embed = discord.Embed(title=f"✅ Mod Action: {req_type.title()} (Approved)", color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
        log_embed.add_field(name="Target", value=f"{target.mention if hasattr(target, 'mention') else 'Unknown'} ({target_id})", inline=False)
        log_embed.add_field(name="Requested By", value=f"<@{req['author']}>", inline=True)
        log_embed.add_field(name="Approved By", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="Reason", value=reason, inline=False)
        if "duration_days" in req:
            log_embed.add_field(name="Duration", value=f"{req['duration_days']} Days", inline=True)
            
        if proof and proof != "None Provided":
            log_embed.set_image(url=proof)
            log_embed.add_field(name="Proof Link", value=proof, inline=False)

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

    async def _dm_user(self, target: typing.Union[discord.Member, discord.User], embed: discord.Embed, tag_user: bool = False):
        try:
            content = target.mention if tag_user else None
            await target.send(content=content, embed=embed)
        except discord.Forbidden:
            pass

    async def log_immediate_action(self, guild: discord.Guild, action: str, target: typing.Union[discord.Member, discord.User], moderator: typing.Union[discord.Member, discord.User], reason: str, proof: str, duration_minutes: int = None, duration_days: int = None):
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
                if proof and proof != "None Provided":
                    embed.set_image(url=proof)
                    embed.add_field(name="Proof Link", value=proof, inline=False)
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
        elif "tempban" in action_lower:
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
                    reason=f"{reason} | Evidence: {proof}",
                    until=until_time
                )
            except Exception:
                pass

    async def create_request(self, ctx: commands.Context, req_type: str, target: typing.Union[discord.Member, discord.User], reason: str, proof: str, ping_level: int, extra_data: dict = None):
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
        if extra_data:
            for k, v in extra_data.items():
                embed.add_field(name=k.replace("_", " ").title(), value=str(v), inline=True)
        
        if proof and proof != "None Provided":
            embed.set_image(url=proof)
            embed.add_field(name="Proof Link", value=proof, inline=False)

        msg = await channel.send(content=f"Attention required: {ping_mention}", embed=embed, view=DynamicRequestView(self))
        
        base_payload = {
            "type": req_type,
            "target": target.id,
            "author": ctx.author.id,
            "reason": reason,
            "proof": proof,
            "message_id": msg.id
        }
        if extra_data:
            base_payload.update(extra_data)

        async with self.config.guild(ctx.guild).active_requests() as reqs:
            reqs[req_id] = base_payload

    async def _process_warning_escalation(self, ctx: commands.Context, target: typing.Union[discord.Member, discord.User]):
        warns = await self.config.user(target).warnings()
        warn_count = len(warns)
        punishments = await self.config.guild(ctx.guild).punishments()
        
        if str(warn_count) not in punishments: return

        punishment = punishments[str(warn_count)]
        action = punishment["action"]
        duration = punishment["duration"]
        reason = f"Automated Escalation: Reached {warn_count} warnings."
        proof = warns[-1]["proof"]

        if action == "timeout" and isinstance(target, discord.Member):
            time_delta = datetime.timedelta(minutes=duration)
            await target.timeout(time_delta, reason=reason)
            dm_embed = discord.Embed(title=f"Automated Timeout: {ctx.guild.name}", description=f"You have been timed out for {duration} minutes.\n**Reason:** {reason}", color=discord.Color.orange())
            await self._dm_user(target, dm_embed, tag_user=True)
            await self.log_immediate_action(ctx.guild, f"Auto-Timeout", target, ctx.guild.me, reason, proof, duration_minutes=duration)

        elif action == "kick" and isinstance(target, discord.Member):
            dm_embed = discord.Embed(title=f"Automated Kick: {ctx.guild.name}", description=f"You have been kicked.\n**Reason:** {reason}", color=discord.Color.red())
            await self._dm_user(target, dm_embed, tag_user=True)
            await target.kick(reason=reason)
            await self.log_immediate_action(ctx.guild, "Auto-Kick", target, ctx.guild.me, reason, proof)

        elif action == "ban":
            await self._process_ban(ctx.guild, target, ctx.guild.me, reason, proof, appealable=True, automated=True)

    @commands.hybrid_group(name="advmodset", description="Configure Advanced Moderation parameters.")
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def advmodset(self, ctx):
        pass

    @advmodset.command(name="roles", description="Configure all modular security authorization roles.")
    async def set_roles(self, ctx, base: discord.Role, class1: discord.Role, class2: discord.Role, class3: discord.Role, manager: discord.Role, director: discord.Role):
        await self.config.guild(ctx.guild).base_mod_role.set(base.id)
        await self.config.guild(ctx.guild).class_1_role.set(class1.id)
        await self.config.guild(ctx.guild).class_2_role.set(class2.id)
        await self.config.guild(ctx.guild).class_3_role.set(class3.id)
        await self.config.guild(ctx.guild).manager_role.set(manager.id)
        await self.config.guild(ctx.guild).director_role.set(director.id)
        await ctx.send("Roles successfully configured.")

    @advmodset.command(name="channel", description="Set the single dedicated moderation channel for requests and logs.")
    async def set_channel(self, ctx, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).mod_channel.set(channel.id)
        await ctx.send(f"Unified tracking channel locked to: {channel.mention}")

    @advmodset.command(name="appeallink", description="Set the URL link for automated ban appeal notifications.")
    async def set_appeal(self, ctx, link: str):
        await self.config.guild(ctx.guild).appeal_link.set(link)
        await ctx.send(f"Appeal destination URL set to: {link}")

    @advmodset.command(name="punishment", description="Configure automated thresholds (Actions: timeout, kick, ban).")
    async def set_punishment(self, ctx, warn_count: int, action: str, duration_minutes: int = None):
        action = action.lower()
        if action not in ["timeout", "kick", "ban"]:
            return await ctx.send("❌ Invalid action. Please choose from: `timeout`, `kick`, or `ban`.", ephemeral=True)
            
        if action == "timeout" and not duration_minutes:
            return await ctx.send("❌ You must specify a duration in minutes for a timeout punishment.", ephemeral=True)
            
        async with self.config.guild(ctx.guild).punishments() as punishments:
            punishments[str(warn_count)] = {"action": action, "duration": duration_minutes}
            
        duration_str = f" for {duration_minutes} minutes" if duration_minutes else ""
        await ctx.send(f"✅ Automated Escalation Configured: Reaching `{warn_count}` warnings will trigger a `{action}`{duration_str}.")

    @commands.hybrid_command(name="warn", description="[Class I+] Issue a warning to a user or ID.")
    @commands.guild_only()
    async def warn(self, ctx, target: typing.Union[discord.Member, discord.User], reason: str, proof_link: str = None, attachment: discord.Attachment = None):
        if not await self._has_level(ctx, 1): return await ctx.send("Permission denied.", ephemeral=True)
        allowed, error_msg = await self._is_allowed_to_moderate(ctx, target)
        if not allowed: return await ctx.send(error_msg, ephemeral=True)
        
        proof_data = self._get_proof(proof_link, attachment)
        if proof_data == "None Provided": return await ctx.send("❌ You must provide visual proof attributes (a link or file upload).", ephemeral=True)
        
        async with self.config.user(target).warnings() as warns:
            warns.append({"reason": reason, "proof": proof_data, "mod": ctx.author.id, "time": time.time()})
            total_warns = len(warns)

        await ctx.send(f"⚠️ {target.mention} has been logged for warning #{total_warns}.")

        embed = discord.Embed(title=f"Warning received in {ctx.guild.name}", description=f"**Reason:** {reason}\nTotal Server Infractions: {total_warns}", color=discord.Color.gold())
        await self._dm_user(target, embed, tag_user=True)
        
        await self.log_immediate_action(ctx.guild, f"Warn (#{total_warns})", target, ctx.author, reason, proof_data)
        await self._process_warning_escalation(ctx, target)

    @commands.hybrid_command(name="warnings", description="[Class I+] View warning history by user mention or ID.")
    @commands.guild_only()
    async def warnings(self, ctx, target: typing.Union[discord.Member, discord.User]):
        if not await self._has_level(ctx, 1): return await ctx.send("Permission denied.", ephemeral=True)
        
        warns = await self.config.user(target).warnings()
        if not warns:
            return await ctx.send(f"✅ **{target.display_name}** has a perfectly clean record (0 warnings).")
            
        embed = discord.Embed(title=f"Infraction History: {target.display_name}", color=discord.Color.gold())
        if hasattr(target, "display_avatar"):
            embed.set_thumbnail(url=target.display_avatar.url)
        
        for idx, w in enumerate(warns, 1):
            timestamp = f"<t:{int(w['time'])}:F>"
            value = f"**Reason:** {w['reason']}\n**Moderator:** <@{w['mod']}>\n**Date:** {timestamp}"
            if w['proof'] != "None Provided":
                value += f"\n**Proof Evidence:** [Click to View]({w['proof']})"
            embed.add_field(name=f"Warning #{idx}", value=value, inline=False)
            
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="unwarn", description="[Class II+] Remove a warning or reset a user's warnings completely.")
    @commands.guild_only()
    async def unwarn(self, ctx, target: typing.Union[discord.Member, discord.User], warning_number: int = None):
        if not await self._has_level(ctx, 2): return await ctx.send("Permission denied. Class II+ hierarchy required.", ephemeral=True)
        allowed, error_msg = await self._is_allowed_to_moderate(ctx, target)
        if not allowed: return await ctx.send(error_msg, ephemeral=True)
        
        async with self.config.user(target).warnings() as warns:
            if not warns:
                return await ctx.send(f"**{target.display_name}** does not have any active warnings to remove.", ephemeral=True)
                
            if warning_number is None:
                warns.clear()
                await ctx.send(f"✅ Successfully wiped all warning infractions for {target.mention}.")
                await self.log_immediate_action(ctx.guild, "Wipe Warnings", target, ctx.author, "All warning history wiped manually by supervisor.", "None Provided")
            else:
                if warning_number < 1 or warning_number > len(warns):
                    return await ctx.send(f"❌ Invalid index selection. Choose a position between 1 and {len(warns)}.", ephemeral=True)
                    
                removed = warns.pop(warning_number - 1)
                await ctx.send(f"✅ Successfully removed Warning `#{warning_number}` from {target.mention}.")
                await self.log_immediate_action(ctx.guild, f"Remove Warn #{warning_number}", target, ctx.author, f"Warning removed. Original Reason: {removed['reason']}", "None Provided")

    @commands.hybrid_command(name="timeout", description="[Class I+] Timeout (mute) a user temporarily to stop them from interacting with the community.")
    @commands.guild_only()
    async def timeout(self, ctx, target: typing.Union[discord.Member, discord.User], minutes: int, reason: str, proof_link: str = None, attachment: discord.Attachment = None):
        if not await self._has_level(ctx, 1): return await ctx.send("Permission denied.", ephemeral=True)
        if not isinstance(target, discord.Member):
            return await ctx.send("❌ Target user must currently be a member in the server to be timed out.", ephemeral=True)

        allowed, error_msg = await self._is_allowed_to_moderate(ctx, target)
        if not allowed: return await ctx.send(error_msg, ephemeral=True)
        
        proof_data = self._get_proof(proof_link, attachment)
        if proof_data == "None Provided": return await ctx.send("❌ Proof missing.", ephemeral=True)
        
        await ctx.send(f"🔇 Timed out {target.mention} for {minutes}m.")
        
        await target.timeout(datetime.timedelta(minutes=minutes), reason=reason)
        embed = discord.Embed(title=f"Timed Out in {ctx.guild.name}", description=f"Duration: {minutes} minutes\n**Reason:** {reason}", color=discord.Color.orange())
        await self._dm_user(target, embed, tag_user=True)
        await self.log_immediate_action(ctx.guild, "Timeout", target, ctx.author, reason, proof_data, duration_minutes=minutes)

    @commands.hybrid_command(name="kick", description="[Class I+] Remove a member by mention or ID.")
    @commands.guild_only()
    async def kick(self, ctx, target: typing.Union[discord.Member, discord.User], reason: str, proof_link: str = None, attachment: discord.Attachment = None):
        if not await self._has_level(ctx, 1): return await ctx.send("Permission denied.", ephemeral=True)
        if not isinstance(target, discord.Member):
            return await ctx.send("❌ Target user must currently be present in the server to be kicked.", ephemeral=True)

        allowed, error_msg = await self._is_allowed_to_moderate(ctx, target)
        if not allowed: return await ctx.send(error_msg, ephemeral=True)
        
        proof_data = self._get_proof(proof_link, attachment)
        if proof_data == "None Provided": return await ctx.send("❌ Proof metadata missing.", ephemeral=True)

        if await self._has_level(ctx, 2):
            await ctx.send(f"👢 Removed {target.mention} from the server.")
            embed = discord.Embed(title=f"Kicked from {ctx.guild.name}", description=f"**Reason:** {reason}", color=discord.Color.red())
            await self._dm_user(target, embed, tag_user=True)
            await target.kick(reason=reason)
            await self.log_immediate_action(ctx.guild, "Kick", target, ctx.author, reason, proof_data)
        else:
            await ctx.send(f"⏳ Verification request for kick sent to Class II+ moderators.")
            await self.create_request(ctx, "kick", target, reason, proof_data, ping_level=2)

    @commands.hybrid_command(name="tempban", description="[Class I+] Tempban a user by mention or ID.")
    @commands.guild_only()
    async def tempban(self, ctx, target: typing.Union[discord.Member, discord.User], duration_days: int, reason: str, proof_link: str = None, attachment: discord.Attachment = None):
        if not await self._has_level(ctx, 1): return await ctx.send("Permission denied.", ephemeral=True)
        allowed, error_msg = await self._is_allowed_to_moderate(ctx, target)
        if not allowed: return await ctx.send(error_msg, ephemeral=True)
        
        if duration_days <= 0: return await ctx.send("❌ Ban duration must be at least 1 day.", ephemeral=True)
        
        proof_data = self._get_proof(proof_link, attachment)
        if proof_data == "None Provided": return await ctx.send("❌ Proof metadata missing.", ephemeral=True)

        if await self._has_level(ctx, 3):
            await ctx.send(f"⏳ Temporarily banned {target} for {duration_days} days.")
            await self._process_ban(ctx.guild, target, ctx.author, reason, proof_data, appealable=True, temp_days=duration_days)
        else:
            await ctx.send(f"⏳ Verification request for temporary ban sent to Class III+ moderators.")
            await self.create_request(ctx, "tempban", target, reason, proof_data, ping_level=3, extra_data={"duration_days": duration_days})

    @commands.hybrid_command(name="ban", description="[Class II+] Ban a user by mention or ID.")
    @commands.guild_only()
    async def ban(self, ctx, target: typing.Union[discord.Member, discord.User], reason: str, proof_link: str = None, attachment: discord.Attachment = None):
        if not await self._has_level(ctx, 2): return await ctx.send("Permission denied.", ephemeral=True)
        allowed, error_msg = await self._is_allowed_to_moderate(ctx, target)
        if not allowed: return await ctx.send(error_msg, ephemeral=True)
        
        proof_data = self._get_proof(proof_link, attachment)
        if proof_data == "None Provided": return await ctx.send("❌ Proof metadata missing.", ephemeral=True)

        if await self._has_level(ctx, 3):
            await ctx.send(f"🔨 Permanently banned {target}.")
            await self._process_ban(ctx.guild, target, ctx.author, reason, proof_data, appealable=True)
        else:
            await ctx.send(f"⏳ Verification request for ban sent to Class III+ moderators.")
            await self.create_request(ctx, "permban (appealable)", target, reason, proof_data, ping_level=3)

    @commands.hybrid_command(name="strictban", description="[Manager+] Strict ban user by mention or ID.")
    @commands.guild_only()
    async def strictban(self, ctx, target: typing.Union[discord.Member, discord.User], reason: str, proof_link: str = None, attachment: discord.Attachment = None):
        if not await self._has_level(ctx, 4): return await ctx.send("Permission denied.", ephemeral=True)
        allowed, error_msg = await self._is_allowed_to_moderate(ctx, target)
        if not allowed: return await ctx.send(error_msg, ephemeral=True)
        
        proof_data = self._get_proof(proof_link, attachment)
        if proof_data == "None Provided": return await ctx.send("❌ Proof required.", ephemeral=True)

        await ctx.send(f"⛔ Executed strict ban on {target}. Forwarded context to Directors.")
        await self._process_ban(ctx.guild, target, ctx.author, reason, proof_data, appealable=False)
        await self.create_request(ctx, "director review (strict ban)", target, reason, proof_data, ping_level=5)

    async def _process_ban(self, guild: discord.Guild, target: typing.Union[discord.Member, discord.User], moderator: typing.Union[discord.Member, discord.User], reason: str, proof: str, appealable: bool, temp_days: int = None, automated: bool = False):
        desc = f"**Reason:** {reason}"
        if temp_days: desc = f"**Duration:** {temp_days} Days\n" + desc
        embed = discord.Embed(title=f"Banned from {guild.name}", description=desc, color=discord.Color.dark_red())
        
        if appealable:
            hold_time = temp_days if temp_days else 14
            embed.add_field(name="Appeals", value=f"This restriction is appealable. You will receive an access form via DM in {hold_time} days.")
            async with self.config.guild(guild).pending_appeals() as appeals_list:
                appeals_list.append({"user_id": target.id, "timestamp": time.time(), "hold_days": hold_time})
        else:
            embed.add_field(name="Appeals", value="This execution type is strict and unappealable.")

        await self._dm_user(target, embed, tag_user=True)
        await guild.ban(target, reason=reason)
        
        log_type = "Auto-Ban" if automated else (f"Tempban" if temp_days else ("Ban" if appealable else "Strict Ban"))
        await self.log_immediate_action(guild, log_type, target, moderator, reason, proof, duration_days=temp_days)

    @tasks.loop(hours=24)
    async def appeal_notifier(self):
        current_time = time.time()

        for guild_id in await self.config.all_guilds():
            guild = self.bot.get_guild(guild_id)
            if not guild: continue
            appeal_link = await self.config.guild(guild).appeal_link()
            if not appeal_link: continue

            async with self.config.guild(guild).pending_appeals() as appeals_list:
                to_remove = []
                for appeal in appeals_list:
                    days = appeal.get("hold_days", 14)
                    seconds_required = days * 24 * 60 * 60
                    
                    if current_time - appeal["timestamp"] >= seconds_required:
                        user = self.bot.get_user(appeal["user_id"]) or await self.bot.fetch_user(appeal["user_id"])
                        if user:
                            if "hold_days" in appeal and appeal["hold_days"] != 14:
                                try:
                                    await guild.unban(user, reason="Temporary ban duration expired.")
                                except discord.HTTPException:
                                    pass
                                    
                            embed = discord.Embed(
                                title=f"Appeal / Re-entry Window Opened: {guild.name}", 
                                description=f"Your {days}-day network hold time has ended.\n\n[Open Form Portal]({appeal_link})",
                                color=discord.Color.green()
                            )
                            await self._dm_user(user, embed, tag_user=True)
                        to_remove.append(appeal)
                for item in to_remove:
                    appeals_list.remove(item)

    @appeal_notifier.before_loop
    async def before_appeal_notifier(self):
        await self.bot.wait_until_red_ready()
