import discord
from redbot.core import commands, Config
from discord import app_commands
import io
import datetime

class Modmail(commands.Cog):
    """A single-server Modmail system with tag-tracked anon replies and reason-based closing."""

    def __init__(self, bot):
        self.bot = bot
        
        # Config Setup
        self.config = Config.get_conf(self, identifier=8472938471, force_registration=True)
        
        self.config.register_guild(
            log_channel_id=None,
            immune_roles=[],
            blocked_users=[],
            departments={"general": None}
        )
        
        self.config.register_user(active_channel_id=None)
        self.config.register_channel(owner_id=None, claimed_by=None)

    async def _create_ticket(self, guild: discord.Guild, user: discord.User, department: str = "general"):
        """Helper method to create a ticket channel."""
        departments = await self.config.guild(guild).departments()
        
        if department not in departments:
            department = "general"
            
        category_id = departments.get(department)
        category = guild.get_channel(category_id) if category_id else None

        channel_name = f"ticket-{user.name}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(name=channel_name, category=category)

        await self.config.user(user).active_channel_id.set(channel.id)
        await self.config.channel(channel).owner_id.set(user.id)

        created_at = f"<t:{int(user.created_at.timestamp())}:R>"
        
        embed = discord.Embed(
            title="🎫 Ticket Created",
            description=f"Support ticket opened for {user.mention} (`{user.id}`).\n\n"
                        f"**Account Created:** {created_at}\n\n"
                        f"Type normally to reply to them, or start your message with `!anon ` to reply anonymously.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        await channel.send(embed=embed)
        
        try:
            await user.send(f"✅ **Ticket Opened**\nYou are now connected to the **{department.title()}** department. Please describe your issue.")
        except discord.Forbidden:
            await channel.send("⚠️ **Warning:** Could not send a DM to this user. They may have DMs disabled.")

        return channel

    async def _generate_html_transcript(self, channel: discord.TextChannel, owner: discord.User, closer: discord.Member, reason: str) -> discord.File:
        """Generates a detailed, Discord-styled HTML transcript file."""
        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Transcript: {channel.name}</title>
            <style>
                body {{ background-color: #313338; color: #dbdee1; font-family: 'gg sans', 'Helvetica Neue', Helvetica, Arial, sans-serif; padding: 20px; }}
                .header {{ background-color: #2b2d31; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .header h1 {{ margin: 0 0 10px 0; color: #fff; font-size: 24px; }}
                .header p {{ margin: 5px 0; font-size: 14px; color: #b5bac1; }}
                .message {{ display: flex; margin-bottom: 16px; margin-top: 16px; }}
                .avatar {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 16px; flex-shrink: 0; object-fit: cover; }}
                .msg-body {{ display: flex; flex-direction: column; max-width: 80%; }}
                .msg-header {{ display: flex; align-items: baseline; margin-bottom: 4px; }}
                .username {{ color: #f2f3f5; font-weight: 500; font-size: 16px; margin-right: 8px; }}
                .timestamp {{ color: #949ba4; font-size: 12px; }}
                .anon-badge {{ background-color: #5865f2; color: white; font-size: 10px; font-weight: bold; padding: 1px 4px; border-radius: 3px; margin-left: 6px; text-transform: uppercase; }}
                .content {{ font-size: 15px; line-height: 1.375; white-space: pre-wrap; word-wrap: break-word; }}
                .attachment {{ max-width: 400px; max-height: 400px; margin-top: 8px; border-radius: 8px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Ticket Transcript: {channel.name}</h1>
                <p><strong>User:</strong> {owner.name} ({owner.id})</p>
                <p><strong>Closed By:</strong> {closer.name} ({closer.id})</p>
                <p><strong>Reason:</strong> {reason}</p>
                <p><strong>Date:</strong> {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
            </div>
            <div class="messages">
        """

        messages = [m async for m in channel.history(limit=None, oldest_first=True)]
        for m in messages:
            username = m.author.name
            avatar_url = m.author.display_avatar.url
            content = m.clean_content
            timestamp = m.created_at.strftime('%m/%d/%Y %I:%M %p')
            is_anon_msg = False

            # Trace back author data through custom logged embeds
            if m.author.bot and m.embeds:
                emb = m.embeds[0]
                if emb.author and emb.author.name:
                    if emb.author.name.startswith("[Anonymous]"):
                        is_anon_msg = True
                        username = emb.author.name.replace("[Anonymous] ", "")
                        avatar_url = emb.author.icon_url or avatar_url
                    else:
                        username = emb.author.name
                        avatar_url = emb.author.icon_url or avatar_url
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

            badge_str = '<span class="anon-badge">Anonymous</span>' if is_anon_msg else ''

            html += f"""
                <div class="message">
                    <img class="avatar" src="{avatar_url}">
                    <div class="msg-body">
                        <div class="msg-header">
                            <span class="username">{username}</span>
                            {badge_str}
                            <span class="timestamp">{timestamp}</span>
                        </div>
                        <div class="content">{content}{attachments_html}</div>
                    </div>
                </div>
            """
        
        html += f"""
            </div>
        </body>
        </html>
        """
        
        transcript_file = io.BytesIO(html.encode('utf-8'))
        return discord.File(transcript_file, filename=f"transcript_{channel.name}.html")

    # ========================
    # EVENT LISTENER (FORWARDING)
    # ========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if not self.bot.guilds:
            return
        guild = self.bot.guilds[0]

        # --- SCENARIO 1: User sends a DM to the bot ---
        if message.guild is None:
            blocked_users = await self.config.guild(guild).blocked_users()
            if message.author.id in blocked_users:
                return

            active_channel_id = await self.config.user(message.author).active_channel_id()

            if active_channel_id:
                channel = guild.get_channel(active_channel_id)
                if channel:
                    files = [await a.to_file() for a in message.attachments]
                    embed = discord.Embed(description=message.content, color=discord.Color.blue(), timestamp=datetime.datetime.now(datetime.timezone.utc))
                    embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                    await channel.send(embed=embed, files=files)
                    await message.add_reaction("✅")
                else:
                    await self.config.user(message.author).active_channel_id.set(None)
            else:
                member = guild.get_member(message.author.id)
                if member:
                    immune_roles = await self.config.guild(guild).immune_roles()
                    if any(r.id in immune_roles for r in member.roles):
                        return

                channel = await self._create_ticket(guild, message.author, "general")
                if channel:
                    files = [await a.to_file() for a in message.attachments]
                    embed = discord.Embed(description=message.content, color=discord.Color.blue(), timestamp=datetime.datetime.now(datetime.timezone.utc))
                    embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                    await channel.send(embed=embed, files=files)

        # --- SCENARIO 2: Staff replies in a ticket channel ---
        else:
            owner_id = await self.config.channel(message.channel).owner_id()
            if owner_id:
                ctx = await self.bot.get_context(message)
                if ctx.valid and not message.content.startswith("!anon "):
                    return

                user = self.bot.get_user(owner_id)
                if not user:
                    return await message.channel.send("⚠️ Cannot forward message. The user is unreachable.")

                is_anon = message.content.startswith("!anon ")
                clean_content = message.content[6:].strip() if is_anon else message.content

                try:
                    # Capture files before potential message deletion mechanics
                    files_for_user = [await a.to_file() for a in message.attachments]
                    files_for_channel = [await a.to_file() for a in message.attachments]

                    user_embed = discord.Embed(description=clean_content, color=discord.Color.green(), timestamp=datetime.datetime.now(datetime.timezone.utc))
                    
                    if is_anon:
                        guild_icon = guild.icon.url if guild.icon else self.bot.user.display_avatar.url
                        user_embed.set_author(name="Support Team", icon_url=guild_icon)
                    else:
                        user_embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                    
                    await user.send(embed=user_embed, files=files_for_user)

                    if is_anon:
                        # Replace content in staff channel to display identity transparently for staff logs
                        await message.delete()
                        chan_embed = discord.Embed(description=clean_content, color=discord.Color.dark_grey(), timestamp=datetime.datetime.now(datetime.timezone.utc))
                        chan_embed.set_author(name=f"[Anonymous] {message.author.name}", icon_url=message.author.display_avatar.url)
                        await message.channel.send(embed=chan_embed, files=files_for_channel)
                    else:
                        await message.add_reaction("📤")

                except discord.Forbidden:
                    await message.channel.send("❌ **Delivery Failed:** The user has closed their DMs.")

    # ========================
    # SLASH COMMANDS (STAFF ACTIONS)
    # ========================

    ticket_group = app_commands.Group(name="modmail", description="Manage support tickets")

    @ticket_group.command(name="open", description="Manually open a ticket for a user.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_open(self, interaction: discord.Interaction, user: discord.User):
        active_channel_id = await self.config.user(user).active_channel_id()
        if active_channel_id and interaction.guild.get_channel(active_channel_id):
            return await interaction.response.send_message(f"❌ {user.mention} already has an active ticket: <#{active_channel_id}>", ephemeral=True)

        channel = await self._create_ticket(interaction.guild, user, "general")
        await interaction.response.send_message(f"✅ Ticket opened for {user.mention} in {channel.mention}", ephemeral=True)

    @ticket_group.command(name="claim", description="Claim this ticket so others know you are handling it.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_claim(self, interaction: discord.Interaction):
        owner_id = await self.config.channel(interaction.channel).owner_id()
        if not owner_id:
            return await interaction.response.send_message("❌ This is not an active ticket channel.", ephemeral=True)
        
        await interaction.channel.edit(topic=f"Claimed by: {interaction.user.name}")
        await interaction.response.send_message(f"✋ **{interaction.user.mention} has claimed this ticket.**")

    @ticket_group.command(name="close", description="Close the ticket, notify the player, and file the transcript.")
    @app_commands.describe(reason="The reason given to the player for closing this ticket.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_close(self, interaction: discord.Interaction, reason: str):
        owner_id = await self.config.channel(interaction.channel).owner_id()
        if not owner_id:
            return await interaction.response.send_message("❌ This is not an active ticket channel.", ephemeral=True)

        await interaction.response.send_message("🔒 Processing ticket closure and filing transcript...", ephemeral=True)
        
        user = self.bot.get_user(owner_id)
        owner_obj = user or discord.Object(id=owner_id)
        owner_obj.name = user.name if user else "Unknown User"

        # 1. Generate Transcript Data
        transcript_file = await self._generate_html_transcript(interaction.channel, owner_obj, interaction.user, reason)

        # 2. Log Filed internally
        log_channel_id = await self.config.guild(interaction.guild).log_channel_id()
        log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None
        
        if log_channel:
            embed = discord.Embed(title="🔒 Ticket Closed & Archived", color=discord.Color.red())
            embed.add_field(name="User", value=f"<@{owner_id}> ({owner_id})")
            embed.add_field(name="Closed By", value=interaction.user.mention)
            embed.add_field(name="Reason", value=reason, inline=False)
            await log_channel.send(embed=embed, file=transcript_file)

        # 3. Notify Player (Send ONLY reason and closer info)
        if user:
            try:
                user_embed = discord.Embed(
                    title="🔒 Ticket Closed",
                    description=f"Your support ticket has been closed by staff member: **{interaction.user.name}**.",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                user_embed.add_field(name="Reason Given", value=reason, inline=False)
                await user.send(embed=user_embed)
            except discord.Forbidden:
                pass
        
        # Cleanup
        await self.config.user_from_id(owner_id).active_channel_id.set(None)
        await self.config.channel(interaction.channel).clear()
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user.name}")

    # ========================
    # PREFIX COMMANDS (SETUP)
    # ========================

    @commands.group(name="modmailset")
    @commands.admin_or_permissions(manage_guild=True)
    async def modmailset(self, ctx):
        """Configuration commands for the Modmail system."""
        pass

    @modmailset.command(name="logchannel")
    async def modmailset_logchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where HTML transcripts will be filed."""
        await self.config.guild(ctx.guild).log_channel_id.set(channel.id)
        await ctx.send(f"✅ Transcripts will now be archived securely in {channel.mention}.")

    @modmailset.command(name="block")
    async def modmailset_block(self, ctx, user: discord.User):
        """Block a user from opening tickets."""
        async with self.config.guild(ctx.guild).blocked_users() as blocked:
            if user.id not in blocked:
                blocked.append(user.id)
                await ctx.send(f"🚫 **{user.name}** has been blocked from Modmail.")
            else:
                await ctx.send("❌ User is already blocked.")

    @modmailset.command(name="unblock")
    async def modmailset_unblock(self, ctx, user: discord.User):
        """Unblock a user from opening tickets."""
        async with self.config.guild(ctx.guild).blocked_users() as blocked:
            if user.id in blocked:
                blocked.remove(user.id)
                await ctx.send(f"✅ **{user.name}** has been unblocked from Modmail.")
            else:
                await ctx.send("❌ User is not blocked.")

    @modmailset.group(name="department")
    async def modmailset_department(self, ctx):
        """Manage ticket departments and categories."""
        pass

    @modmailset_department.command(name="set")
    async def m_dep_set(self, ctx, name: str, category: discord.CategoryChannel):
        """Link a department name to a specific category."""
        name = name.lower()
        async with self.config.guild(ctx.guild).departments() as deps:
            deps[name] = category.id
        await ctx.send(f"✅ Department **{name.title()}** linked to category **{category.name}**.")

    @modmailset.group(name="immune")
    async def modmailset_immune(self, ctx):
        """Manage roles immune from accidentally creating tickets in DMs."""
        pass

    @modmailset_immune.command(name="add")
    async def m_im_add(self, ctx, role: discord.Role):
        async with self.config.guild(ctx.guild).immune_roles() as immune:
            if role.id not in immune:
                immune.append(role.id)
                await ctx.send(f"✅ Users with the **{role.name}** role will no longer trigger DM tickets.")
            else:
                await ctx.send("❌ Role is already immune.")

    @modmailset_immune.command(name="remove")
    async def m_im_remove(self, ctx, role: discord.Role):
        async with self.config.guild(ctx.guild).immune_roles() as immune:
            if role.id in immune:
                immune.remove(role.id)
                await ctx.send(f"✅ Role **{role.name}** removed from immunity list.")
            else:
                await ctx.send("❌ Role is not in the immune list.")

async def setup(bot):
    bot.tree.add_command(Modmail.ticket_group)
    await bot.add_cog(Modmail(bot))
