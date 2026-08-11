import aiohttp
import discord
from redbot.core import commands, Config
from discord.ext import tasks
from datetime import datetime

def parse_isodate(date_string):
    """Safely parse Roblox ISO-8601 string to datetime."""
    if not date_string:
        return None
    # Roblox uses Z for UTC timezone. Replace with +00:00 for python's fromisoformat
    date_string = date_string.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(date_string)
    except ValueError:
        return None

class AuditLogger(commands.Cog):
    """Logs dangerous actions from a Roblox group's audit log and Discord audit log."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=83475923485739, force_registration=True)
        default_guild = {
            "api_key": None,
            "group_id": None,
            "log_channel_id": None,
            "max_safe_rank": 250,
            "last_log_time": None
        }
        self.config.register_guild(**default_guild)
        
        self.session = aiohttp.ClientSession()
        self.group_roles = {} 
        self.log_loop.start()

    def cog_unload(self):
        self.log_loop.cancel()
        self.bot.loop.create_task(self.session.close())

    # ==========================================
    # DISCORD AUDIT LOG MONITOR
    # ==========================================
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        """Listens to native Discord audit log entries in real-time."""
        guild = entry.guild
        config = self.config.guild(guild)
        channel_id = await config.log_channel_id()
        
        if not channel_id:
            return
            
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        # Ignore the bot's own actions to prevent spam loops
        if entry.user and entry.user.id == self.bot.user.id:
            return

        is_dangerous = False
        danger_reason = ""
        action = entry.action

        # Check for dangerous Discord actions
        if action == discord.AuditLogAction.bot_add:
            is_dangerous = True
            danger_reason = f"Added a bot to the server: **{getattr(entry.target, 'name', 'Unknown')}**"

        elif action == discord.AuditLogAction.webhook_create:
            is_dangerous = True
            danger_reason = f"Created a webhook: **{getattr(entry.target, 'name', 'Unknown')}**"

        elif action == discord.AuditLogAction.channel_delete:
            is_dangerous = True
            danger_reason = f"Deleted channel: **{getattr(entry.target, 'name', 'Unknown')}**"
            
        elif action == discord.AuditLogAction.member_ban_add:
            is_dangerous = True
            danger_reason = f"Banned server member: **{getattr(entry.target, 'name', 'Unknown')}**"

        elif action == discord.AuditLogAction.member_role_update:
            # Check if someone was just given dangerous server permissions
            added_roles = getattr(entry.changes.after, 'roles', [])
            dangerous_roles = []
            
            for role_obj in added_roles:
                role = guild.get_role(role_obj.id)
                if role and (role.permissions.administrator or role.permissions.ban_members or role.permissions.manage_guild):
                    dangerous_roles.append(role.name)
            
            if dangerous_roles:
                is_dangerous = True
                roles_str = ", ".join(dangerous_roles)
                target_name = getattr(entry.target, 'name', 'Unknown User')
                danger_reason = f"Granted highly dangerous role(s) to **{target_name}**: `{roles_str}`"

        elif action == discord.AuditLogAction.role_update:
            # Check if an existing role was edited to suddenly have Admin
            old_perms = getattr(entry.changes.before, 'permissions', None)
            new_perms = getattr(entry.changes.after, 'permissions', None)
            
            if old_perms and new_perms:
                if not old_perms.administrator and new_perms.administrator:
                    is_dangerous = True
                    role_name = getattr(entry.target, 'name', 'Unknown Role')
                    danger_reason = f"Granted `Administrator` permission directly to role: **{role_name}**"

        # If flagged, send it to the log channel
        if is_dangerous:
            embed = discord.Embed(
                title="⚠️ Dangerous Discord Action Detected",
                color=discord.Color.red(),
                timestamp=entry.created_at
            )
            actor = entry.user
            actor_name = actor.name if actor else "Unknown User"
            actor_id = actor.id if actor else "Unknown ID"
            
            embed.set_author(name=f"{actor_name} ({actor_id})", icon_url=actor.display_avatar.url if actor else None)
            embed.add_field(name="Action Type", value=f"`{action.name}`", inline=True)
            if entry.reason:
                embed.add_field(name="Reason", value=entry.reason, inline=False)
            embed.add_field(name="Details", value=danger_reason, inline=False)
            embed.set_footer(text="Discord Server Audit Log")
            
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass


    # ==========================================
    # ROBLOX AUDIT LOG MONITOR
    # ==========================================
    @tasks.loop(seconds=30.0)
    async def log_loop(self):
        """Background task running every 30 seconds to fetch new Roblox logs."""
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            config = self.config.guild(guild)
            api_key = await config.api_key()
            group_id = await config.group_id()
            channel_id = await config.log_channel_id()
            max_safe_rank = await config.max_safe_rank()
            last_log_time_str = await config.last_log_time()
            
            if not (api_key and group_id and channel_id):
                continue
                
            channel = guild.get_channel(channel_id)
            if not channel:
                continue

            try:
                # 1. Fetch & Cache Roles
                if group_id not in self.group_roles:
                    roles_url = f"https://groups.roblox.com/v1/groups/{group_id}/roles"
                    async with self.session.get(roles_url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            roles = {}
                            for role in data.get("roles", []):
                                roles[role["id"]] = role.get("rank", 0)
                            self.group_roles[group_id] = roles
                        else:
                            continue

                # 2. Fetch recent Audit Logs
                url = f"https://apis.roblox.com/legacy-groups/v1/groups/{group_id}/audit-log?limit=25"
                headers = {"x-api-key": api_key}
                
                async with self.session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    logs = data.get("data", [])
                    
                if not logs:
                    continue

                # 3. Filter for new logs only
                last_log_time = parse_isodate(last_log_time_str) if last_log_time_str else None
                new_logs = []
                for log in logs:
                    created_at = parse_isodate(log.get("created"))
                    if last_log_time and created_at and created_at <= last_log_time:
                        break
                    new_logs.append(log)

                if not new_logs:
                    continue
                    
                # 4. Save the time of the most recent log
                newest_time = new_logs[0].get("created")
                await config.last_log_time.set(newest_time)
                
                # 5. Process logs backwards (chronologically)
                for log in reversed(new_logs):
                    await self.process_roblox_log(channel, log, group_id, max_safe_rank)

            except Exception:
                pass

    async def process_roblox_log(self, channel, log, group_id, max_safe_rank):
        """Determine if a Roblox action is dangerous and formats the embed."""
        action_type = log.get("actionType")
        actor_data = log.get("actor", {})
        actor_user = actor_data.get("user", {})
        actor_name = actor_user.get("username", "Unknown")
        actor_id = actor_user.get("userId", 0)
        
        desc = log.get("description", {})
        created_at = parse_isodate(log.get("created"))
        
        is_dangerous = False
        danger_reason = ""
        
        if action_type == "ChangeRank":
            role_set_id = desc.get("RoleSetId") or desc.get("RoleNameId")
            rank = self.group_roles.get(group_id, {}).get(role_set_id, 0)
            target_name = desc.get("TargetName", "Unknown User")
            role_name = desc.get("RoleName", "Unknown Role")
            
            if rank >= max_safe_rank:
                is_dangerous = True
                danger_reason = f"Ranked **{target_name}** to **{role_name}** (Rank {rank}), which exceeds the safe threshold ({max_safe_rank})."
                
        elif action_type == "SpendGroupFunds":
            is_dangerous = True
            amount = desc.get("Amount", "Unknown")
            danger_reason = f"Spent **{amount}** Group Funds."
            
        elif action_type == "DeleteGroupAsset":
            is_dangerous = True
            asset_name = desc.get("AssetName", "Unknown Asset")
            danger_reason = f"Deleted group asset: **{asset_name}**."

        if is_dangerous:
            embed = discord.Embed(
                title="⚠️ Dangerous Roblox Action Detected",
                color=discord.Color.orange(),
                timestamp=created_at or datetime.utcnow()
            )
            embed.set_author(name=f"{actor_name} ({actor_id})", url=f"https://www.roblox.com/users/{actor_id}/profile")
            embed.add_field(name="Action Type", value=f"`{action_type}`", inline=True)
            embed.add_field(name="Group ID", value=str(group_id), inline=True)
            embed.add_field(name="Details", value=danger_reason, inline=False)
            embed.set_footer(text="Roblox Group Audit Log")
            
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass

    # ==========================================
    # COMMANDS
    # ==========================================
    @commands.group(name="rblxaudit", aliases=["robloxaudit"])
    @commands.admin_or_permissions(manage_guild=True)
    async def rblxaudit(self, ctx):
        """Configure Roblox Group Audit Logging settings."""
        pass

    @rblxaudit.command(name="setup")
    async def rblxaudit_setup(self, ctx, group_id: int, channel: discord.TextChannel):
        """Set the Group ID and logging channel."""
        await self.config.guild(ctx.guild).group_id.set(group_id)
        await self.config.guild(ctx.guild).log_channel_id.set(channel.id)
        
        await self.config.guild(ctx.guild).last_log_time.set(None)
        self.group_roles.pop(group_id, None)
        
        await ctx.send(f"✅ Group ID set to `{group_id}` and logging to {channel.mention}.")

    @rblxaudit.command(name="setkey")
    async def rblxaudit_setkey(self, ctx, api_key: str):
        """Set the Open Cloud API key."""
        await self.config.guild(ctx.guild).api_key.set(api_key)
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
        await ctx.send("✅ API key set successfully! *(Original message deleted for security where possible).*")

    @rblxaudit.command(name="saferank")
    async def rblxaudit_saferank(self, ctx, rank: int):
        """Set the maximum safe rank threshold (1-255). Default is 250."""
        if not 1 <= rank <= 255:
            return await ctx.send("⚠️ Rank must be between 1 and 255.")
        await self.config.guild(ctx.guild).max_safe_rank.set(rank)
        await ctx.send(f"✅ Max safe rank threshold set to `{rank}`.")

    @rblxaudit.command(name="test")
    async def rblxaudit_test(self, ctx):
        """Test the connection to the Open Cloud API."""
        config = self.config.guild(ctx.guild)
        api_key = await config.api_key()
        group_id = await config.group_id()
        
        if not api_key or not group_id:
            return await ctx.send("⚠️ Please set both the group ID and API key first (`[p]rblxaudit setup` and `[p]rblxaudit setkey`).")
            
        url = f"https://apis.roblox.com/legacy-groups/v1/groups/{group_id}/audit-log?limit=10"
        headers = {"x-api-key": api_key}
        
        async with self.session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                logs = data.get("data", [])
                await ctx.send(f"✅ Connection successful! Retrieved {len(logs)} recent logs.")
            elif resp.status == 401:
                await ctx.send("❌ Connection failed: **Unauthorized**. Please check your API key.")
            elif resp.status == 403:
                await ctx.send("❌ Connection failed: **Forbidden**. Ensure your API key has the correct permissions (Group Audit Log access) for this group.")
            else:
                await ctx.send(f"❌ Connection failed with HTTP Code `{resp.status}`.")
