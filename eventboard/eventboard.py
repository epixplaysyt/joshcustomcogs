import discord
from redbot.core import commands, Config
import aiohttp
from discord.ext import tasks
import logging
from datetime import datetime

log = logging.getLogger("red.eventboard")

class EventBoard(commands.Cog):
    """Fetches upcoming events from Orbit (Planetary App) and maintains an event board embed."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8374629104, force_registration=True)
        
        default_guild = {
            "api_url": "https://instance.planetaryapp.cloud/api/public/v1/workspace/YOUR_ID/sessions/upcoming?limit=50&page=1",
            "api_token": "",
            "channel_id": None,
            "message_id": None,
            "embed_color": 0x2596be,  # Custom hex #2596be
        }
        self.config.register_guild(**default_guild)
        self.update_board_loop.start()

    def cog_unload(self):
        self.update_board_loop.cancel()

    @tasks.loop(minutes=10)
    async def update_board_loop(self):
        await self.bot.wait_until_ready()
        for guild_id in await self.config.all_guilds():
            guild = self.bot.get_guild(guild_id)
            if guild:
                await self._run_board_update(guild)

    async def _run_board_update(self, guild: discord.Guild) -> tuple[bool, str]:
        """Internal helper to process the API request. Returns (success_bool, status_message)"""
        data = await self.config.guild(guild).all()
        channel_id = data["channel_id"]
        api_url = data["api_url"]
        api_token = data["api_token"]
        
        if not channel_id:
            return False, "Configuration Error: Destination channel has not been set yet via `!eventset channel`."
        if not api_url or "YOUR_ID" in api_url:
            return False, "Configuration Error: Please configure your active workspace URL endpoint via `!eventset url`."
            
        channel = guild.get_channel(channel_id)
        if not channel:
            return False, f"Discord Error: Cannot find configured channel ID ({channel_id}) in this server."
        
        # Verify Bot Permissions
        perms = channel.permissions_for(guild.me)
        if not perms.send_messages or not perms.embed_links:
            return False, f"Permission Error: Bot is missing 'Send Messages' or 'Embed Links' in {channel.mention}."

        headers = {}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(api_url, headers=headers, timeout=10) as response:
                    if response.status in (401, 403):
                        return False, f"API Error: Unauthorized (Status {response.status}). Check if your token is valid."
                    if response.status != 200:
                        return False, f"API Error: Received unexpected status code {response.status} from Orbit server."
                    sessions_data = await response.json()
            except aiohttp.ClientConnectorError:
                return False, f"Connection Error: Could not resolve or connect to the API URL: `{api_url}`"
            except Exception as e:
                return False, f"Exception Error encountered while fetching data: {str(e)}"

        upcoming_events = []
        sessions_list = sessions_data.get("sessions", [])
        
        if isinstance(sessions_list, list):
            for item in sessions_list:
                # Skip historical sessions that successfully ended to avoid cluttering the billboard
                if item.get("ended") is True and not item.get("cancelled"):
                    continue
                
                # Fetch nested category safely
                session_type = item.get("type") or {}
                category = session_type.get("category", "")
                
                if category and str(category).lower() == "events":
                    upcoming_events.append(item)

        events_text = ""
        if upcoming_events:
            for event in upcoming_events[:8]:
                name = event.get("name") or "Unnamed Event"
                time_val = event.get("date")
                
                is_cancelled = event.get("cancelled") is True
                started_at = event.get("startedAt")
                is_ongoing = started_at is not None and event.get("ended") is not True and not is_cancelled

                # Build out Title Headers based on Status Requirements
                if is_cancelled:
                    title_display = f"~~**{name}**~~ ❌ *(Cancelled)*"
                elif is_ongoing:
                    title_display = f"**{name}** 🟢 *(Ongoing)*"
                else:
                    title_display = f"**{name}** ⏳ *(Upcoming)*"

                # Parse ISO-8601 strings into Discord Dynamic Timestamps
                if time_val:
                    try:
                        if "T" in str(time_val):
                            dt = datetime.fromisoformat(str(time_val).replace("Z", "+00:00"))
                            time_str = f"<t:{int(dt.timestamp())}:F> (<t:{int(dt.timestamp())}:R>)"
                        else:
                            time_str = str(time_val)
                    except Exception:
                        time_str = str(time_val)
                else:
                    time_str = "TBD"
                
                # Fetch nested host data safely
                host_info = event.get("host") or {}
                host = host_info.get("username") or "Staff"
                
                # Fetch and truncate nested description snippet safely
                session_type = event.get("type") or {}
                raw_desc = session_type.get("description") or event.get("description") or ""
                raw_desc = raw_desc.strip().replace("\n", " ") # Collapse structural linebreaks for embedding cleanly
                
                if len(raw_desc) > 110:
                    desc_snippet = f"\n*\"{raw_desc[:107]}...\"*"
                elif raw_desc:
                    desc_snippet = f"\n*\"{raw_desc}\"*"
                else:
                    desc_snippet = ""
                
                events_text += f"• {title_display}\n📅 {time_str}\n👤 Host: {host}{desc_snippet}\n\n"
        else:
            events_text = "*No upcoming community events scheduled at the moment. Check back soon!*"

        # Base Embed Setup
        embed = discord.Embed(
            title="📅 Events",
            color=discord.Color(data["embed_color"])
        )
        
        embed.description = (
            "Welcome to the channel for all official MM Tech Studios events! This is where we "
            "announce everything happening across the community to keep things active and fun."
        )
        
        info_field_value = (
            "• Game Nights & Showcases. Join the community to play games together or check out "
            "what our developers and members are building.\n"
            "• Community Q&As. Get live updates on our projects and ask the team your questions.\n"
            "• Schedules & Details. Find exact dates, times, and instructions on how to "
            "participate in upcoming activities."
        )
        embed.add_field(name="What will you find here?", value=info_field_value, inline=False)
        embed.add_field(name="🗓️ Upcoming Schedule", value=events_text, inline=False)
        
        avatar_url = guild.icon.url if guild.icon else None
        embed.set_footer(
            text="Copyright © MM Tech Studios:\nhttps://discord.com/invite/DVaRQRQRcB",
            icon_url=avatar_url
        )
        
        message_id = data["message_id"]
        msg = None
        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden):
                msg = None
        
        if msg:
            try:
                await msg.edit(embed=embed)
                return True, f"Board updated smoothly (Found {len(upcoming_events)} live index tracking targets)."
            except Exception as e:
                return False, f"Discord Write Error: Failed to edit existing message: {str(e)}"
        else:
            try:
                new_msg = await channel.send(embed=embed)
                await self.config.guild(guild).message_id.set(new_msg.id)
                return True, f"Board spawned fresh (Found {len(upcoming_events)} live index tracking targets)."
            except Exception as e:
                return False, f"Discord Write Error: Failed to send new message embed: {str(e)}"

    # ========================
    # PREFIX ADMIN COMMANDS
    # ========================

    @commands.group(name="eventset")
    @commands.admin_or_permissions(manage_guild=True)
    async def eventset(self, ctx):
        """Configuration management tools for the Orbit automated Event Board."""
        pass

    @eventset.command(name="channel")
    async def eventset_channel(self, ctx, channel: discord.TextChannel):
        """Configure the destination target text channel for message rendering updates."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await self.config.guild(ctx.guild).message_id.set(None)
        await ctx.send(f"✅ Event board channel set to {channel.mention}. Use `!eventset refresh` to test it.")

    @eventset.command(name="url")
    async def eventset_url(self, ctx, url: str):
        """Define the Orbit sessions endpoint URL (include your workspace workspace ID block)."""
        await self.config.guild(ctx.guild).api_url.set(url)
        await ctx.send(f"✅ Orbit endpoint targeting synchronized to:\n`{url}`")

    @eventset.command(name="token")
    async def eventset_token(self, ctx, token: str):
        """Provide authorization credentials to bypass private instance restrictions."""
        await self.config.guild(ctx.guild).api_token.set(token)
        try:
            await ctx.message.delete()
            await ctx.send("✅ Orbit API configuration payload processed. (Command deleted to secure tokens).")
        except discord.Forbidden:
            await ctx.send("✅ Orbit API configuration payload processed.")

    @commands.command(name="color")
    async def eventset_color(self, ctx, color: discord.Color):
        """Change the left border highlight color of the embed board."""
        await self.config.guild(ctx.guild).embed_color.set(color.value)
        await ctx.send(f"✅ Embed sidebar accent color updated to: `{color.value}`.")

    @eventset.command(name="refresh")
    async def eventset_refresh(self, ctx):
        """Force run an explicit pull against the web targets to sync content state instantly."""
        await ctx.typing()
        success, status_msg = await self._run_board_update(ctx.guild)
        if success:
            await ctx.send(f"🔄 **Sync Complete:** {status_msg}")
        else:
            await ctx.send(f"❌ **Sync Failed!**\n> {status_msg}")

async def setup(bot):
    await bot.add_cog(EventBoard(bot))
