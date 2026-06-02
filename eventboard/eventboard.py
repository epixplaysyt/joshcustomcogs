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
            "api_url": "https://instance.planetaryapp.cloud/api/v1/sessions",
            "api_token": "",
            "channel_id": None,
            "message_id": None,
            "embed_color": 0x2596be,
        }
        self.config.register_guild(**default_guild)
        self.update_board_loop.start()

    def cog_unload(self):
        self.update_board_loop.cancel()

    @tasks.loop(minutes=10)
    async def update_board_loop(self):
        await self.bot.wait_until_ready()
        await self._run_board_update()

    async def _run_board_update(self, target_guild: discord.Guild = None):
        """Internal helper to process the API request and update the embed message."""
        all_guilds = await self.config.all_guilds()
        
        async with aiohttp.ClientSession() as session:
            for guild_id, data in all_guilds.items():
                # If target_guild is passed, skip other servers running the loop
                if target_guild and guild_id != target_guild.id:
                    continue
                    
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    continue
                
                channel_id = data["channel_id"]
                api_url = data["api_url"]
                api_token = data["api_token"]
                
                if not channel_id or not api_url:
                    continue
                    
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue
                
                headers = {}
                if api_token:
                    headers["Authorization"] = f"Bearer {api_token}"
                    headers["X-API-Key"] = api_token  # Handles common variants of Orbit deployment structures

                try:
                    async with session.get(api_url, headers=headers, timeout=10) as response:
                        if response.status != 200:
                            log.error(f"Failed to fetch Orbit sessions for guild {guild_id}. Status: {response.status}")
                            continue
                        sessions_data = await response.json()
                except Exception as e:
                    log.error(f"Error connecting to Orbit API for guild {guild_id}: {e}")
                    continue

                # Filter down to entries explicitly categorized as "events"
                upcoming_events = []
                items_source = sessions_data.get("data", sessions_data) if isinstance(sessions_data, dict) else sessions_data
                
                if isinstance(items_source, list):
                    for item in items_source:
                        category = item.get("category", "")
                        if category and str(category).lower() == "events":
                            upcoming_events.append(item)

                # Format upcoming events section safely
                events_text = ""
                if upcoming_events:
                    for event in upcoming_events[:8]:  # Capped at 8 listings to protect embed limits safely
                        name = event.get("name") or event.get("title") or "Unnamed Event"
                        time_val = event.get("scheduledTime") or event.get("time") or event.get("date")
                        
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
                            
                        host = event.get("host") or event.get("hostName") or "Staff"
                        events_text += f"• **{name}**\n📅 {time_str}\n👤 Host: {host}\n\n"
                else:
                    events_text = "*No upcoming community events scheduled at the moment. Check back soon!*"

                # Build the mirrored embed style based on UI design specification
                embed = discord.Embed(
                    title="📅 Events",
                    color=discord.Color(data["embed_color"])
                )
                
                embed.description = (
                    "Welcome to the channel for all official MM Tech Studios events! This is where we "
                    "announce everything happening across the community to keep things active and fun.\n\n"
                    "**What will you find here?**\n\n"
                    "• Game Nights & Showcases. Join the community to play games together or check out "
                    "what our developers and members are building.\n"
                    "• Community Q&As. Get live updates on our projects and ask the team your questions.\n"
                    "• Schedules & Details. Find exact dates, times, and instructions on how to "
                    "participate in upcoming activities."
                )
                
                embed.add_field(name="🗓️ Upcoming Schedule", value=events_text, inline=False)
                
                avatar_url = guild.icon.url if guild.icon else None
                embed.set_footer(
                    text="Copyright © MM Tech Studios:\nhttps://discord.com/invite/DVaRQRQRcB",
                    icon_url=avatar_url
                )
                
                # Verify message presence state to perform edit operations rather than messy repeating posts
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
                    except Exception as e:
                        log.error(f"Failed to edit event board message: {e}")
                else:
                    try:
                        new_msg = await channel.send(embed=embed)
                        await self.config.guild(guild).message_id.set(new_msg.id)
                    except Exception as e:
                        log.error(f"Failed to send new event board message: {e}")
                      
    @commands.group(name="eventset")
    @commands.admin_or_permissions(manage_guild=True)
    async def eventset(self, ctx):
        """Configuration management tools for the Orbit automated Event Board."""
        pass

    @eventset.command(name="channel")
    async def eventset_channel(self, ctx, channel: discord.TextChannel):
        """Configure the destination target text channel for message rendering updates."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await self.config.guild(ctx.guild).message_id.set(None)  # Resets message ID to force generate a fresh embed post
        await ctx.send(f"✅ Event board channel set to {channel.mention}. The new embed will build momentarily.")

    @eventset.command(name="url")
    async def eventset_url(self, ctx, url: str):
        """Define the Orbit sessions endpoint URL."""
        await self.config.guild(ctx.guild).api_url.set(url)
        await ctx.send(f"✅ Orbit endpoint targeting synchronized to: `{url}`")

    @eventset.command(name="token")
    async def eventset_token(self, ctx, token: str):
        """Provide authorization credentials to bypass private instance restrictions."""
        await self.config.guild(ctx.guild).api_token.set(token)
        try:
            await ctx.message.delete()
            await ctx.send("✅ Orbit API configuration payload processed. (Command deleted to secure tokens).")
        except discord.Forbidden:
            await ctx.send("✅ Orbit API configuration payload processed. (Please erase your plaintext configuration command history manually for safety).")

    @eventset.command(name="refresh")
    async def eventset_refresh(self, ctx):
        """Force run an explicit pull against the web targets to sync content state instantly."""
        await ctx.typing()
        await self._run_board_update(target_guild=ctx.guild)
        await ctx.send("🔄 Event board sync complete.")
