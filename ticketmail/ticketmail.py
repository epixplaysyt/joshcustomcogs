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
                emb = m.embeds[0]
                if emb.author and emb.author.name:
                    if emb.author.name.startswith("[Anonymous]"):
                        username = emb.author.name.replace("[Anonymous] ", "")
                        avatar_url = emb.author.icon_url or avatar_url
                    else:
                        username = emb.author.name
                        avatar_url = emb.author.icon_url or avatar_url
                
                # Extract role info and timestamp directly out of the embed's footer signature if it exists
                if emb.footer and emb.footer.text:
                    parts = [p.strip() for p in emb.footer.text.split("|")]
                    for part in parts:
                        if part.startswith("Role:"):
                            role_str = part.replace("Role: ", "")
                        if "UTC" in part and not part.startswith("Ticket ID"):
                            timestamp = part

                if emb.description:
                    content = emb.description
            
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
            
