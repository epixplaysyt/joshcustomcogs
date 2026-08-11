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
    """Logs dangerous actions from a Roblox group's audit log using Open Cloud API."""

    def __init__(self, bot):
        self.bot = bot
        # Ensure ID is random/unique for your bot's database to prevent collisions
        self.config = Config.get_conf(self, identifier=83475923485739, force_registration=True)
        default_guild = {
            "api_key": None,
            "group_id": None,
            "log_channel_id": None,
            "max_safe_rank": 250,
            "last_log_time": None # ISO 8601 string cache
        }
        self.config.register_guild(**default_guild)
        
        self.session = aiohttp.ClientSession()
        self.group_roles = {} # Cache: guild_id -> {roleset_id: rank}
        self.log_loop.start()

    def cog_unload(self):
        self.log_loop.cancel()
        self.bot.loop.create_task(self.session.close())

    @tasks.loop(minutes=1.0)
    async def log_loop(self):
        """Background task running every minute to fetch new logs."""
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
                # 1. Fetch & Cache Roles (used to map RoleSetId back to a 1-255 Rank Number)
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
                            continue # Could not fetch roles, skip to next loop

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
                    # Stop processing if we reached a log entry we've already saved/seen
                    if last_log_time and created_at and created_at <= last_log_time:
                        break
                    new_logs.append(log)

                if not new_logs:
                    continue
                    
                # 4. Save the time of the most recent log (Index 0 in Roblox's response)
                newest_time = new_logs[0].get("created")
                await config.last_log_time.set(newest_time)
                
                # 5. Process logs from oldest to newest (Reverse order)
                for log in reversed(new_logs):
                    await self.process_log(channel, log, group_id, max_safe_rank)

            except Exception:
                # Silently skip this guild on a network error/timeout to prevent breaking the loop
                pass

    async def process_log(self, channel, log, group_id, max_safe_rank):
        """Determine if an action is dangerous and formats the embed."""
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
                danger_reason = f"Ranked **{target_name}** to **{role_name}** (Rank {rank}), which meets/exceeds the safe threshold ({max_safe_rank})."
                
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
                title="⚠️ Dangerous Group Action Detected",
                color=discord.Color.red(),
                timestamp=created_at or datetime.utcnow()
            )
            embed.set_author(name=f"{actor_name} ({actor_id})", url=f"https://www.roblox.com/users/{actor_id}/profile")
            embed.add_field(name="Action Type", value=f"`{action_type}`", inline=True)
            embed.add_field(name="Group ID", value=str(group_id), inline=True)
            embed.add_field(name="Details", value=danger_reason, inline=False)
            embed.set_footer(text="Roblox Group Audit Log")
            
            await channel.send(embed=embed)

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
        
        # Clear the internal timer so it restarts on the next cycle, and refresh cache
        await self.config.guild(ctx.guild).last_log_time.set(None)
        self.group_roles.pop(group_id, None)
        
        await ctx.send(f"✅ Group ID set to `{group_id}` and logging to {channel.mention}.")

    @rblxaudit.command(name="setkey")
    async def rblxaudit_setkey(self, ctx, api_key: str):
        """Set the Open Cloud API key. (Highly recommended to use in a private/staff channel)"""
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
        await ctx.send(f"✅ Max safe rank threshold set to `{rank}`. Ranks promoted to this or above will flag an alert.")

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

