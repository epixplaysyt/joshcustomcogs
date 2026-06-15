import discord
from redbot.core import commands, Config
from discord import app_commands
from discord.ext import tasks
import io
import datetime

class TicketConfirmationView(discord.ui.View):
    def __init__(self, cog, user: discord.User, guild: discord.Guild, initial_message: discord.Message, departments: dict):
        super().__init__(timeout=180)
        self.cog = cog
        self.user = user
        self.guild = guild
        self.initial_message = initial_message
        self.message = None

        for dept_name in departments.keys():
            button = discord.ui.Button(
                label=f"Open {dept_name.title()}",
                style=discord.ButtonStyle.success,
                custom_id=f"confirm_{guild.id}_{user.id}_{dept_name}"
            )
            button.callback = self.make_callback(dept_name)
            self.add_item(button)
            
        cancel_button = discord.ui.Button(
            label="Cancel", 
            style=discord.ButtonStyle.danger, 
            custom_id=f"cancel_{guild.id}_{user.id}"
        )
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    def make_callback(self, dept_name):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            self.stop()
            
            try:
                channel = await self.cog._create_ticket(self.guild, self.user, dept_name)
            except Exception as e:
                print(f"[Modmail Error] Failed to create channel via button: {e}")
                await interaction.message.edit(content="❌ Failed to create ticket. Please ensure the bot has 'Manage Channels' permissions.", view=None)
                return

            if channel:
                member = self.guild.get_member(self.user.id)
                role_name = member.top_role.name if member else "User"
                ticket_id = await self.cog.config.channel(channel).ticket_id() or "UNKNOWN"
                now = datetime.datetime.now(datetime.timezone.utc)
                date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')
                
                files = [await a.to_file() for a in self.initial_message.attachments]
                embed = discord.Embed(
                    description=self.initial_message.content, 
                    color=discord.Color.blue(), 
                    timestamp=now
                )
                embed.set_author(name=self.user.name, icon_url=self.user.display_avatar.url)
                embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                
                await channel.send(embed=embed, files=files)
                await interaction.message.edit(content=f"✅ **Ticket {ticket_id} opened successfully!**", view=None)
        return callback

    async def cancel_callback(self, interaction: discord.Interaction):
        self.stop()
        await interaction.response.edit_message(content="❌ Ticket creation cancelled.", view=None)

    async def on_timeout(self):
        try:
            if self.message:
                await self.message.edit(content="⏳ Ticket creation timed out.", view=None)
        except Exception:
            pass

class Modmail(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8472938471, force_registration=True)
        
        self.config.register_global(default_guild_id=None)
        
        self.config.register_guild(
            log_channel_id=None,
            immune_roles=[],
            blocked_users=[],
            ticket_counter=1000,
            departments={"general": None},
            support_hours={"start": None, "end": None},
            response_stats={}
        )
        self.config.register_user(active_channel_id=None)
        self.config.register_channel(
            owner_id=None, 
            claimed_by=None, 
            ticket_id=None,
            department=None,
            waiting_since=None
        )
        
        self.presence_loop.start()

    def cog_unload(self):
        self.presence_loop.cancel()
        try:
            self.bot.tree.remove_command(self.ticket_group.name)
        except Exception:
            pass

    def is_in_hours(self, start_str, end_str):
        if not start_str or not end_str:
            return True
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
        except ValueError:
            return True
            
        current_time = now.time()
        if start_time <= end_time:
            return start_time <= current_time <= end_time
        else:
            return current_time >= start_time or current_time <= end_time

    def get_next_open_timestamp(self, start_str):
        if not start_str:
            return None
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
        except ValueError:
            return None
            
        next_open = now.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
        if now.time() > start_time:
            next_open += datetime.timedelta(days=1)
        return int(next_open.timestamp())

    async def update_average(self, guild, department, wait_time_seconds, was_in_hours):
        if not department:
            return
        async with self.config.guild(guild).response_stats() as stats:
            if department not in stats:
                stats[department] = {'in_avg': 0, 'in_count': 0, 'out_avg': 0, 'out_count': 0}
            
            prefix = 'in' if was_in_hours else 'out'
            current_avg = stats[department][f'{prefix}_avg']
            current_count = stats[department][f'{prefix}_count']
            
            new_count = current_count + 1
            new_avg = ((current_avg * current_count) + wait_time_seconds) / new_count
            
            stats[department][f'{prefix}_avg'] = new_avg
            stats[department][f'{prefix}_count'] = new_count

    @tasks.loop(minutes=5)
    async def presence_loop(self):
        default_guild_id = await self.config.default_guild_id()
        if not default_guild_id: 
            return
        guild = self.bot.get_guild(default_guild_id)
        if not guild: 
            return
            
        hours = await self.config.guild(guild).support_hours()
        in_hours = self.is_in_hours(hours.get('start'), hours.get('end'))
        
        target_status = discord.Status.online if in_hours else discord.Status.idle
        if self.bot.guilds and self.bot.guilds[0].me.status != target_status:
            await self.bot.change_presence(status=target_status)

    @presence_loop.before_loop
    async def before_presence_loop(self):
        await self.bot.wait_until_ready()

    async def _create_ticket(self, guild: discord.Guild, user: discord.User, department: str = "general"):
        departments = await self.config.guild(guild).departments()
        if not isinstance(departments, dict) or department not in departments:
            department = "general"
            
        category_id = departments.get(department) if isinstance(departments, dict) else None
        category = guild.get_channel(category_id) if category_id else None

        counter = await self.config.guild(guild).ticket_counter() + 1
        await self.config.guild(guild).ticket_counter.set(counter)
        prefix = department[0].upper() if department else "G"
        ticket_id = f"{prefix}{counter}"

        channel_name = f"{ticket_id.lower()}-{user.name}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(name=channel_name, category=category)

        now = datetime.datetime.now(datetime.timezone.utc)
        await self.config.user(user).active_channel_id.set(channel.id)
        await self.config.channel(channel).owner_id.set(user.id)
        await self.config.channel(channel).ticket_id.set(ticket_id)
        await self.config.channel(channel).department.set(department)
        await self.config.channel(channel).waiting_since.set(now.timestamp())

        hours = await self.config.guild(guild).support_hours()
        in_hours = self.is_in_hours(hours.get('start'), hours.get('end'))
        stats = await self.config.guild(guild).response_stats()
        
        dept_stats = stats.get(department, {})
        time_prefix = 'in' if in_hours else 'out'
        avg_wait = dept_stats.get(f'{time_prefix}_avg', 0)
        
        avg_str = "Calculating..." if avg_wait == 0 else f"{int(avg_wait // 60)}m {int(avg_wait % 60)}s"
        created_at = f"<t:{int(user.created_at.timestamp())}:R>"

        embed = discord.Embed(
            title=f"🎫 Ticket Created - {ticket_id}",
            color=discord.Color.green(),
            timestamp=now
        )
        desc = (f"Support channel created for {user.mention} (`{user.id}`).\n\n"
                f"**Ticket ID:** `{ticket_id}`\n"
                f"**Account Created:** {created_at}\n\n"
                f"**Current Avg Response:** {avg_str}\n\n"
                f"Type here to reply, or use `!anon ` to send anonymous messages.")
        
        if not in_hours and hours.get('start'):
            next_open = self.get_next_open_timestamp(hours.get('start'))
            desc += f"\n\n🌙 **We are currently out of hours.**\nSupport resumes <t:{next_open}:R>."

        embed.description = desc
        embed.set_thumbnail(url=user.display_avatar.url)
        await channel.send(embed=embed)
        
        try:
            user_msg = f"✅ **Ticket Opened ({ticket_id})**\nYou are connected to the **{department.title()}** department. "
            if not in_hours and hours.get('start'):
                user_msg += f"\n⚠️ *Note: We are out of operating hours. We will be back <t:{next_open}:R>.*"
            await user.send(user_msg)
        except discord.Forbidden:
            await channel.send("⚠️ **Warning:** The user has DMs disabled.")

        return channel

    # ... (Keep the _generate_html_transcript function exactly as it was) ...

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        now = datetime.datetime.now(datetime.timezone.utc)

        if message.guild is None:
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                return

            active_channel_id = await self.config.user(message.author).active_channel_id()
            channel = self.bot.get_channel(active_channel_id) if active_channel_id else None

            if channel:
                guild = channel.guild
                blocked_users = await self.config.guild(guild).blocked_users()
                if message.author.id in blocked_users:
                    return

                # Mark that user is waiting for a reply
                await self.config.channel(channel).waiting_since.set(now.timestamp())

                ticket_id = await self.config.channel(channel).ticket_id() or "UNKNOWN"
                member = guild.get_member(message.author.id)
                role_name = member.top_role.name if member else "User"
                date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')

                files = [await a.to_file() for a in message.attachments]
                embed = discord.Embed(description=message.content, color=discord.Color.blue(), timestamp=now)
                embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                
                await channel.send(embed=embed, files=files)
                await message.add_reaction("✅")
            else:
                if active_channel_id:
                    await self.config.user(message.author).active_channel_id.set(None)

                default_guild_id = await self.config.default_guild_id()
                guild = self.bot.get_guild(default_guild_id) if default_guild_id else None
                
                if not guild:  
                    for g in self.bot.guilds:
                        if g.get_member(message.author.id):
                            guild = g
                            break
                            
                if not guild:  
                    guild = self.bot.guilds[0] if self.bot.guilds else None

                if not guild:
                    return

                blocked_users = await self.config.guild(guild).blocked_users()
                if message.author.id in blocked_users:
                    return

                member = guild.get_member(message.author.id)
                if member:
                    immune_roles = await self.config.guild(guild).immune_roles()
                    if any(r.id in immune_roles for r in member.roles):
                        return

                departments = await self.config.guild(guild).departments()
                if not isinstance(departments, dict) or not departments:
                    departments = {"general": None}
                
                if len(departments) == 1:
                    dept_name = list(departments.keys())[0]
                    try:
                        channel = await self._create_ticket(guild, message.author, dept_name)
                        if channel:
                            role_name = member.top_role.name if member else "User"
                            ticket_id = await self.config.channel(channel).ticket_id() or "UNKNOWN"
                            date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')
                            
                            files = [await a.to_file() for a in message.attachments]
                            embed = discord.Embed(description=message.content, color=discord.Color.blue(), timestamp=now)
                            embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                            embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                            
                            await channel.send(embed=embed, files=files)
                            await message.add_reaction("✅")
                    except Exception as e:
                        print(f"[Modmail Error] Automatic ticket execution dropped: {e}")
                    return

                embed = discord.Embed(
                    title="🎟️ Open a Support Ticket?",
                    description="Please choose a department below to start your ticket.",
                    color=discord.Color.gold(),
                    timestamp=now
                )
                
                view = TicketConfirmationView(self, message.author, guild, message, departments)
                try:
                    msg = await message.author.send(embed=embed, view=view)
                    view.message = msg
                    # Issue 2 Fixed: self.bot.add_view(view) Removed
                except discord.Forbidden:
                    pass

        else:
            owner_id = await self.config.channel(message.channel).owner_id()
            if owner_id:
                ctx = await self.bot.get_context(message)
                if ctx.valid and not message.content.startswith("!anon "):
                    return

                # Calculate staff response time
                waiting_since = await self.config.channel(message.channel).waiting_since()
                if waiting_since:
                    wait_time = now.timestamp() - waiting_since
                    dept = await self.config.channel(message.channel).department()
                    hours = await self.config.guild(message.guild).support_hours()
                    was_in_hours = self.is_in_hours(hours.get('start'), hours.get('end'))
                    
                    await self.update_average(message.guild, dept, wait_time, was_in_hours)
                    await self.config.channel(message.channel).waiting_since.set(None) # Reset wait timer

                user = self.bot.get_user(owner_id)
                if not user:
                    return await message.channel.send("⚠️ Error: User not found.")

                ticket_id = await self.config.channel(message.channel).ticket_id() or "UNKNOWN"
                is_anon = message.content.startswith("!anon ")
                clean_content = message.content[6:].strip() if is_anon else message.content

                member = message.guild.get_member(message.author.id)
                role_name = member.top_role.name if member else "Staff"
                date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')

                try:
                    files_for_user = [await a.to_file() for a in message.attachments]
                    files_for_channel = [await a.to_file() for a in message.attachments]

                    user_embed = discord.Embed(description=clean_content, color=discord.Color.green(), timestamp=now)
                    
                    if is_anon:
                        guild_icon = message.guild.icon.url if message.guild.icon else self.bot.user.display_avatar.url
                        user_embed.set_author(name="Support Team", icon_url=guild_icon)
                        user_embed.set_footer(text=f"Ticket ID: {ticket_id} | {date_time_str}")
                    else:
                        user_embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                        user_embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                    
                    await user.send(embed=user_embed, files=files_for_user)

                    if is_anon:
                        await message.delete()
                        chan_embed = discord.Embed(description=clean_content, color=discord.Color.dark_grey(), timestamp=now)
                        chan_embed.set_author(name=f"[Anonymous] {message.author.name}", icon_url=message.author.display_avatar.url)
                        chan_embed.set_footer(text=f"Ticket ID: {ticket_id} | {date_time_str}")
                        await message.channel.send(embed=chan_embed, files=files_for_channel)
                    else:
                        await message.add_reaction("📤")

                except discord.Forbidden:
                    await message.channel.send("❌ Error: The user has DMs disabled.")

    ticket_group = app_commands.Group(name="modmail", description="Commands for managing modmail tickets")

    # ... (Keep ticket_open, ticket_claim, ticket_transfer, ticket_close identical) ...

    @commands.group(name="modmailset")
    @commands.admin_or_permissions(manage_guild=True)
    async def modmailset(self, ctx):
        pass

    @modmailset.command(name="hours")
    async def modmailset_hours(self, ctx, start_time: str = None, end_time: str = None):
        """Set support hours in UTC (e.g., [p]modmailset hours 09:00 17:00). Leave blank to clear."""
        if not start_time or not end_time:
            await self.config.guild(ctx.guild).support_hours.set({"start": None, "end": None})
            return await ctx.send("✅ Support hours cleared. The bot will assume 24/7 online availability.")
            
        try:
            datetime.datetime.strptime(start_time, "%H:%M")
            datetime.datetime.strptime(end_time, "%H:%M")
        except ValueError:
            return await ctx.send("❌ Invalid format. Please use HH:MM HH:MM in 24-hour UTC format (e.g. `09:00 17:00`).")

        await self.config.guild(ctx.guild).support_hours.set({"start": start_time, "end": end_time})
        await ctx.send(f"✅ Support hours set from **{start_time} to {end_time} UTC**.")

    # ... (Keep setdefault, logchannel, block, unblock identical) ...

    @modmailset.group(name="immune")
    async def modmailset_immune(self, ctx):
        pass

    # Issue 3 Fixed: Parented to modmailset_immune
    @modmailset_immune.command(name="add")
    async def m_im_add(self, ctx, role: discord.Role):
        async with self.config.guild(ctx.guild).immune_roles() as immune:
            if role.id not in immune:
                immune.append(role.id)
                await ctx.send(f"✅ Members with the **{role.name}** role can no longer open tickets by sending DMs.")
            else:
                await ctx.send("❌ That role is already on the immune list.")

    # Issue 3 Fixed: Parented to modmailset_immune
    @modmailset_immune.command(name="remove")
    async def m_im_remove(self, ctx, role: discord.Role):
        async with self.config.guild(ctx.guild).immune_roles() as immune:
            if role.id in immune:
                immune.remove(role.id)
                await ctx.send(f"✅ Removed **{role.name}** from the immune list.")
            else:
                await ctx.send("❌ That role is not on the immune list.")
