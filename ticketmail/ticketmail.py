import discord
from redbot.core import commands, Config
from discord import app_commands
import io
import datetime

class TicketConfirmationView(discord.ui.View):
    """Dynamic confirmation interface presenting department choices to the user."""
    def __init__(self, cog, user: discord.User, guild: discord.Guild, initial_message: discord.Message, departments: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.user = user
        self.guild = guild
        self.initial_message = initial_message
        self.message = None

        # Generate a green selection button for each active registration department
        for dept_name in departments.keys():
            button = discord.ui.Button(
                label=f"Open {dept_name.title()}",
                style=discord.Style.green,
                custom_id=f"confirm_{dept_name}"
            )
            button.callback = self.make_callback(dept_name)
            self.add_item(button)
            
        # Standard safety exit option
        cancel_button = discord.ui.Button(label="Cancel", style=discord.Style.red, custom_id="cancel_ticket")
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    def make_callback(self, dept_name):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            self.cog.pending_confirmations.discard(self.user.id)
            self.stop()
            
            # Execute channel infrastructure build
            channel = await self.cog._create_ticket(self.guild, self.user, dept_name)
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
        self.cog.pending_confirmations.discard(self.user.id)
        self.stop()
        await interaction.response.edit_message(content="❌ Ticket creation cancelled.", view=None)

    async def on_timeout(self):
        self.cog.pending_confirmations.discard(self.user.id)
        try:
            if self.message:
                await self.message.edit(content="⏳ Ticket creation confirmation timed out.", view=None)
        except Exception:
            pass


class Modmail(commands.Cog):
    """Single-server Modmail engine with confirmation routing, role footprint tracking, and alpha ID tracking."""

    def __init__(self, bot):
        self.bot = bot
        self.pending_confirmations = set()
        
        self.config = Config.get_conf(self, identifier=8472938471, force_registration=True)
        self.config.register_guild(
            log_channel_id=None,
            immune_roles=[],
            blocked_users=[],
            ticket_counter=1000,
            departments={"general": None}
        )
        self.config.register_user(active_channel_id=None)
        self.config.register_channel(owner_id=None, claimed_by=None, ticket_id=None)

    async def _create_ticket(self, guild: discord.Guild, user: discord.User, department: str = "general"):
        """Compiles structural ticket environments and formats system identifiers."""
        departments = await self.config.guild(guild).departments()
        if department not in departments:
            department = "general"
            
        category_id = departments.get(department)
        category = guild.get_channel(category_id) if category_id else None

        # Build Unique Serial Identifier Sequence (e.g. G1001)
        counter = await self.config.guild(guild).ticket_counter() + 1
        await self.config.guild(guild).ticket_counter.set(counter)
        prefix = department[0].upper() if department else "G"
        ticket_id = f"{prefix}{counter}"

        channel_name = f"{ticket_id.lower()}-{user.name}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(name=channel_name, category=category)

        await self.config.user(user).active_channel_id.set(channel.id)
        await self.config.channel(channel).owner_id.set(user.id)
        await self.config.channel(channel).ticket_id.set(ticket_id)

        created_at = f"<t:{int(user.created_at.timestamp())}:R>"
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
        
        embed = discord.Embed(
            title=f"🎫 Ticket Created — {ticket_id}",
            description=f"Support channel instantiated for {user.mention} (`{user.id}`).\n\n"
                        f"**Ticket ID:** `{ticket_id}`\n"
                        f"**Account Created:** {created_at}\n\n"
                        f"Type directly here to reply, or use `!anon ` to send anonymous messages.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text=f"Date Opened: {date_str}")
        await channel.send(embed=embed)
        
        try:
            await user.send(
                f"✅ **Ticket Opened ({ticket_id})**\n"
                f"You are connected to the **{department.title()}** branch. Please send your inquiries below."
            )
        except discord.Forbidden:
            await channel.send("⚠️ **Warning:** The user blocks incoming direct messaging interfaces.")

        return channel

    async def _generate_html_transcript(self, channel: discord.TextChannel, owner: discord.User, closer: discord.Member, reason: str, ticket_id: str) -> discord.File:
        """Assembles fully compliant Discord themed layouts tracking identity, absolute times, and roles."""
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Transcript: {ticket_id}</title>
            <style>
                body {{ background-color: #313338; color: #dbdee1; font-family: 'gg sans', sans-serif; padding: 20px; }}
                .header {{ background-color: #2b2d31; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .header h1 {{ margin: 0 0 10px 0; color: #fff; font-size: 24px; }}
                .header p {{ margin: 5px 0; font-size: 14px; color: #b5bac1; }}
                .message {{ display: flex; margin-bottom: 16px; margin-top: 16px; }}
                .avatar {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 16px; flex-shrink: 0; object-fit: cover; }}
                .msg-body {{ display: flex; flex-direction: column; max-width: 80%; }}
                .msg-header {{ display: flex; align-items: baseline; margin-bottom: 4px; }}
                .username {{ color: #f2f3f5; font-weight: 500; font-size: 16px; margin-right: 6px; }}
                .timestamp {{ color: #949ba4; font-size: 12px; }}
                .content {{ font-size: 15px; line-height: 1.375; white-space: pre-wrap; word-wrap: break-word; }}
                .attachment {{ max-width: 400px; max-height: 400px; margin-top: 8px; border-radius: 8px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Transcript Ticket Record: {ticket_id}</h1>
                <p><strong>Channel Context:</strong> {channel.name}</p>
                <p><strong>Target User:</strong> {owner.name} ({owner.id})</p>
                <p><strong>Closed By:</strong> {closer.name} ({closer.id})</p>
                <p><strong>Closure Summary Reason:</strong> {reason}</p>
                <p><strong>Date Compiled:</strong> {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
            </div>
            <div class="messages">
        """

        messages = [m async for m in channel.history(limit=None, oldest_first=True)]
        guild = channel.guild

        for m in messages:
            username = m.author.name
            avatar_url = m.author.display_avatar.url
            content = m.clean_content
            timestamp = m.created_at.strftime('%Y-%m-%d %I:%M %p UTC')
            role_str = ""

            member_obj = guild.get_member(m.author.id)
            if member_obj:
                role_str = member_obj.top_role.name

            # Extract author data through logged embeds
            if m.author.bot and m.embeds:
                embed_obj = m.embeds[0]
                if embed_obj.author and embed_obj.author.name:
                    if embed_obj.author.name.startswith("[Anonymous]"):
                        username = embed_obj.author.name.replace("[Anonymous] ", "")
                        avatar_url = embed_obj.author.icon_url or avatar_url
                    else:
                        username = embed_obj.author.name
                        avatar_url = embed_obj.author.icon_url or avatar_url
                
                # Extract role info and timestamp directly out of the embed's footer signature if it exists
                if embed_obj.footer and embed_obj.footer.text:
                    parts = [p.strip() for p in embed_obj.footer.text.split("|")]
                    for part in parts:
                        if part.startswith("Role:"):
                            role_str = part.replace("Role: ", "")
                        if "UTC" in part and not part.startswith("Ticket ID"):
                            timestamp = part

                if embed_obj.description:
                    content = embed_obj.description
            
            # Format Attachments
            attachments_html = ""
            for a in m.attachments:
                if a.content_type and a.content_type.startswith('image/'):
                    attachments_html += f'<br><img class="attachment" src="{a.url}">'
                else:
                    attachments_html += f'<br><a href="{a.url}" style="color: #00a8fc;">[Attachment: {a.filename}]</a>'

            if not content and not attachments_html:
                continue

            footer_meta = f" — {role_str}" if role_str else ""

            html += f"""
                <div class="message">
                    <img class="avatar" src="{avatar_url}">
                    <div class="msg-body">
                        <div class="msg-header">
                            <span class="username">{username}</span>
                            <span class="timestamp">{timestamp}{footer_meta}</span>
                        </div>
                        <div class="content">{content}{attachments_html}</div>
                    </div>
                </div>
            """
        
        html += """</div></body></html>"""
        transcript_file = io.BytesIO(html.encode('utf-8'))
        return discord.File(transcript_file, filename=f"transcript_{ticket_id}.html")

    async def cog_unload(self):
        """Removes the command structure gracefully during reload phases."""
        try:
            self.bot.tree.remove_command(self.ticket_group.name)
        except Exception:
            pass

    # ========================
    # ROUTING LISTENERS
    # ========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not self.bot.guilds:
            return
        guild = self.bot.guilds[0]

        # Scenario A: Inbound User DM Gateway
        if message.guild is None:
            blocked_users = await self.config.guild(guild).blocked_users()
            if message.author.id in blocked_users:
                return

            active_channel_id = await self.config.user(message.author).active_channel_id()

            if active_channel_id:
                channel = guild.get_channel(active_channel_id)
                if channel:
                    ticket_id = await self.config.channel(channel).ticket_id() or "UNKNOWN"
                    member = guild.get_member(message.author.id)
                    role_name = member.top_role.name if member else "User"
                    now = datetime.datetime.now(datetime.timezone.utc)
                    date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')

                    files = [await a.to_file() for a in message.attachments]
                    embed = discord.Embed(description=message.content, color=discord.Color.blue(), timestamp=now)
                    embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                    embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                    
                    await channel.send(embed=embed, files=files)
                    await message.add_reaction("✅")
                else:
                    await self.config.user(message.author).active_channel_id.set(None)
            else:
                if message.author.id in self.pending_confirmations:
                    return

                member = guild.get_member(message.author.id)
                if member:
                    immune_roles = await self.config.guild(guild).immune_roles()
                    if any(r.id in immune_roles for r in member.roles):
                        return

                departments = await self.config.guild(guild).departments()
                if not departments:
                    departments = {"general": None}

                self.pending_confirmations.add(message.author.id)
                
                embed = discord.Embed(
                    title="🎟️ Establish a Support Connection?",
                    description="Confirm your intent to reach the internal staff network by selecting your target destination branch category below.",
                    color=discord.Color.gold(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                date_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %I:%M %p UTC')
                embed.set_footer(text=f"Request Date: {date_str}")
                
                view = TicketConfirmationView(self, message.author, guild, message, departments)
                try:
                    msg = await message.author.send(embed=embed, view=view)
                    view.message = msg
                except discord.Forbidden:
                    self.pending_confirmations.discard(message.author.id)

        # Scenario B: Outbound Staff Mod-Channel Forwarding
        else:
            owner_id = await self.config.channel(message.channel).owner_id()
            if owner_id:
                ctx = await self.bot.get_context(message)
                if ctx.valid and not message.content.startswith("!anon "):
                    return

                user = self.bot.get_user(owner_id)
                if not user:
                    return await message.channel.send("⚠️ Operational Error: Targeted user object has evaporated.")

                ticket_id = await self.config.channel(message.channel).ticket_id() or "UNKNOWN"
                is_anon = message.content.startswith("!anon ")
                clean_content = message.content[6:].strip() if is_anon else message.content

                member = guild.get_member(message.author.id)
                role_name = member.top_role.name if member else "Staff"
                now = datetime.datetime.now(datetime.timezone.utc)
                date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')

                try:
                    files_for_user = [await a.to_file() for a in message.attachments]
                    files_for_channel = [await a.to_file() for a in message.attachments]

                    user_embed = discord.Embed(description=clean_content, color=discord.Color.green(), timestamp=now)
                    user_embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                    
                    if is_anon:
                        guild_icon = guild.icon.url if guild.icon else self.bot.user.display_avatar.url
                        user_embed.set_author(name="Support Team", icon_url=guild_icon)
                    else:
                        user_embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                    
                    await user.send(embed=user_embed, files=files_for_user)

                    if is_anon:
                        await message.delete()
                        chan_embed = discord.Embed(description=clean_content, color=discord.Color.dark_grey(), timestamp=now)
                        chan_embed.set_author(name=f"[Anonymous] {message.author.name}", icon_url=message.author.display_avatar.url)
                        chan_embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                        await message.channel.send(embed=chan_embed, files=files_for_channel)
                    else:
                        await message.add_reaction("📤")

                except discord.Forbidden:
                    await message.channel.send("❌ Error: Targeted destination rejects inbound transmission flows.")

    # ========================
    # SLASH CORE EXECUTIVE COMMANDS
    # ========================

    ticket_group = app_commands.Group(name="modmail", description="Command suite for managing modmail ticketing operations")

    @ticket_group.command(name="open", description="Explicitly instantiate a standard system ticket pipeline for a specific user.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_open(self, interaction: discord.Interaction, user: discord.User):
        active_channel_id = await self.config.user(user).active_channel_id()
        if active_channel_id and interaction.guild.get_channel(active_channel_id):
            return await interaction.response.send_message(f"❌ User maintains open infrastructure: <#{active_channel_id}>", ephemeral=True)

        channel = await self._create_ticket(interaction.guild, user, "general")
        await interaction.response.send_message(f"✅ Context pipeline established inside {channel.mention}", ephemeral=True)

    @ticket_group.command(name="claim", description="Set channel operational status labels to signify assigned control.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_claim(self, interaction: discord.Interaction):
        owner_id = await self.config.channel(interaction.channel).owner_id()
        if not owner_id:
            return await interaction.response.send_message("❌ Execution context invalid: Not an active channel link.", ephemeral=True)
        
        await interaction.channel.edit(topic=f"Assigned Handler: {interaction.user.name}")
        await interaction.response.send_message(f"✋ **{interaction.user.mention} assumes administrative assignment processing role.**")

    @ticket_group.command(name="close", description="Deconstruct active ticket pipelines, compile system logs, and dispatch notifications.")
    @app_commands.describe(reason="Reason details passed strictly to target user summary.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_close(self, interaction: discord.Interaction, reason: str):
        owner_id = await self.config.channel(interaction.channel).owner_id()
        if not owner_id:
            return await interaction.response.send_message("❌ Execution context invalid: Not an active channel link.", ephemeral=True)

        await interaction.response.send_message("🔒 Initiating context deconstruction sequences...", ephemeral=True)
        
        ticket_id = await self.config.channel(interaction.channel).ticket_id() or "UNKNOWN"
        user = self.bot.get_user(owner_id)
        owner_obj = user or discord.Object(id=owner_id)
        owner_obj.name = user.name if user else "Offline Identity"

        # Compilation phase
        transcript_file = await self._generate_html_transcript(interaction.channel, owner_obj, interaction.user, reason, ticket_id)

        log_channel_id = await self.config.guild(interaction.guild).log_channel_id()
        log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None
        
        if log_channel:
            date_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %I:%M %p UTC')
            embed = discord.Embed(title=f"🔒 Archived Ticket Record — {ticket_id}", color=discord.Color.red())
            embed.add_field(name="User", value=f"<@{owner_id}> ({owner_id})")
            embed.add_field(name="Closed By", value=interaction.user.mention)
            embed.add_field(name="Reason Profile", value=reason, inline=False)
            embed.set_footer(text=f"Archive Date: {date_str}")
            await log_channel.send(embed=embed, file=transcript_file)

        if user:
            try:
                date_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %I:%M %p UTC')
                user_embed = discord.Embed(
                    title=f"🔒 Ticket Closed — {ticket_id}",
                    description=f"Your ticket has been officially closed by: **{interaction.user.name}**.",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                user_embed.add_field(name="Resolution Reason", value=reason, inline=False)
                user_embed.set_footer(text=f"Date: {date_str}")
                await user.send(embed=user_embed)
            except discord.Forbidden:
                pass
        
        await self.config.user_from_id(owner_id).active_channel_id.set(None)
        await self.config.channel(interaction.channel).clear()
        await interaction.channel.delete(reason=f"Modmail pipeline closure: {interaction.user.name}")

    # ========================
    # ADMIN SETUP PRESETS
    # ========================

    @commands.group(name="modmailset")
    @commands.admin_or_permissions(manage_guild=True)
    async def modmailset(self, ctx):
        """Configuration entry terminal parameters."""
        pass

    @modmailset.command(name="logchannel")
    async def modmailset_logchannel(self, ctx, channel: discord.TextChannel):
        """Bind file transcript payload storage destinations."""
        await self.config.guild(ctx.guild).log_channel_id.set(channel.id)
        await ctx.send(f"✅ Archive pipeline targeted into {channel.mention}.")

    @modmailset.command(name="block")
    async def modmailset_block(self, ctx, user: discord.User):
        """Restricts users from creating confirmation views."""
        async with self.config.guild(ctx.guild).blocked_users() as blocked:
            if user.id not in blocked:
                blocked.append(user.id)
                await ctx.send(f"🚫 User ID **{user.name}** dropped from configuration routing access paths.")
            else:
                await ctx.send("❌ Record registers matching entity state already blocked.")

    @modmailset.command(name="unblock")
    async def modmailset_unblock(self, ctx, user: discord.User):
        """Restores a blacklisted individual's access paths."""
        async with self.config.guild(ctx.guild).blocked_users() as blocked:
            if user.id in blocked:
                blocked.remove(user.id)
                await ctx.send(f"✅ Identity data profile for **{user.name}** cleared.")
            else:
                await ctx.send("❌ Identity registry data lookup match failed.")

    @modmailset.group(name="department")
    async def modmailset_department(self, ctx):
        """Map functional system category containers."""
        pass

    @modmailset_department.command(name="set")
    async def m_dep_set(self, ctx, name: str, category: discord.CategoryChannel):
        """Maps an individual system classification to a categorical parent."""
        name = name.lower()
        async with self.config.guild(ctx.guild).departments() as deps:
            deps[name] = category.id
        await ctx.send(f"✅ Managed category group **{name.title()}** attached into **{category.name}**.")

    @modmailset.group(name="immune")
    async def modmailset_immune(self, ctx):
        """Manage organizational bypass tags."""
        pass

    @modmailset.command(name="add")
    async def m_im_add(self, ctx, role: discord.Role):
        async with self.config.guild(ctx.guild).immune_roles() as immune:
            if role.id not in immune:
                immune.append(role.id)
                await ctx.send(f"✅ Filter arrays added immune protection exceptions for: **{role.name}**.")
            else:
                await ctx.send("❌ Internal array tables match duplicate profile entries.")

    @modmailset.command(name="remove")
    async def m_im_remove(self, ctx, role: discord.Role):
        async with self.config.guild(ctx.guild).immune_roles() as immune:
            if role.id in immune:
                immune.remove(role.id)
                await ctx.send(f"✅ Removed role protection attributes for: **{role.name}**.")
            else:
                await ctx.send("❌ No filtering attributes found for given tag group elements.")
