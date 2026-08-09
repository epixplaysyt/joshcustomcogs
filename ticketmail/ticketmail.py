import discord
from redbot.core import commands, Config
from discord import app_commands
from discord.ext import tasks
import io
import datetime

class EmbedTextModal(discord.ui.Modal, title='Edit Embed Text'):
    emb_title = discord.ui.TextInput(label='Title', style=discord.TextStyle.short, required=False, max_length=256)
    emb_desc = discord.ui.TextInput(label='Description', style=discord.TextStyle.paragraph, required=False, max_length=4000)

    def __init__(self, view: 'EmbedBuilderView'):
        super().__init__()
        self.view_obj = view
        self.emb_title.default = view.current_embed.title if view.current_embed.title else ""
        self.emb_desc.default = view.current_embed.description if view.current_embed.description else ""

    async def on_submit(self, interaction: discord.Interaction):
        self.view_obj.current_embed.title = self.emb_title.value or None
        self.view_obj.current_embed.description = self.emb_desc.value or None
        if not self.view_obj.current_embed.title and not self.view_obj.current_embed.description:
            self.view_obj.current_embed.description = "*(Empty Embed)*"
        await self.view_obj.update_message(interaction)

class EmbedStyleModal(discord.ui.Modal, title='Edit Embed Style'):
    emb_color = discord.ui.TextInput(label='Hex Color (e.g., FF0000)', style=discord.TextStyle.short, required=False, max_length=7)
    emb_footer = discord.ui.TextInput(label='Footer Text', style=discord.TextStyle.short, required=False, max_length=2048)
    emb_thumb = discord.ui.TextInput(label='Thumbnail URL', style=discord.TextStyle.short, required=False)

    def __init__(self, view: 'EmbedBuilderView'):
        super().__init__()
        self.view_obj = view
        
        current_color = str(hex(view.current_embed.color.value)).replace("0x", "") if view.current_embed.color else ""
        self.emb_color.default = current_color
        
        self.emb_footer.default = view.current_embed.footer.text if view.current_embed.footer else ""
        self.emb_thumb.default = view.current_embed.thumbnail.url if view.current_embed.thumbnail else ""

    async def on_submit(self, interaction: discord.Interaction):
        if self.emb_color.value:
            try:
                clean_hex = self.emb_color.value.replace("#", "")
                self.view_obj.current_embed.color = discord.Color(int(clean_hex, 16))
            except ValueError:
                pass 
        else:
            self.view_obj.current_embed.color = None

        if self.emb_footer.value:
            self.view_obj.current_embed.set_footer(text=self.emb_footer.value)
        else:
            self.view_obj.current_embed.remove_footer()

        if self.emb_thumb.value:
            self.view_obj.current_embed.set_thumbnail(url=self.emb_thumb.value)
        else:
            self.view_obj.current_embed.set_thumbnail(url=None)

        await self.view_obj.update_message(interaction)

class EmbedBuilderView(discord.ui.View):
    def __init__(self, cog, ctx, dept_name, existing_embed_dict):
        super().__init__(timeout=300)
        self.cog = cog
        self.ctx = ctx
        self.dept_name = dept_name
        
        if existing_embed_dict:
            self.current_embed = discord.Embed.from_dict(existing_embed_dict)
        else:
            self.current_embed = discord.Embed(
                title=f"Welcome to {dept_name.title()} Support", 
                description="Please describe your issue here.",
                color=discord.Color.blue()
            )
            
        self.message = None

    async def update_message(self, interaction):
        await interaction.response.edit_message(content="**Interactive Embed Builder**\nPreview:", embed=self.current_embed, view=self)

    @discord.ui.button(label="Edit Text", style=discord.ButtonStyle.primary, emoji="📝")
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        await interaction.response.send_modal(EmbedTextModal(self))

    @discord.ui.button(label="Edit Style & Images", style=discord.ButtonStyle.secondary, emoji="🎨")
    async def edit_style(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        await interaction.response.send_modal(EmbedStyleModal(self))

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, emoji="✅")
    async def save_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        
        async with self.cog.config.guild(self.ctx.guild).departments() as deps:
            if self.dept_name in deps:
                deps[self.dept_name]["embed"] = self.current_embed.to_dict()
                
        self.stop()
        await interaction.response.edit_message(content=f"✅ **Saved!** The custom greeting embed for **{self.dept_name.title()}** has been updated.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancel_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author: return
        self.stop()
        await interaction.response.edit_message(content="❌ **Cancelled.** No changes were saved.", embed=None, view=None)

    async def on_timeout(self):
        try:
            if self.message:
                await self.message.edit(content="⏳ Builder timed out. Unsaved changes were discarded.", view=None)
        except Exception:
            pass

class TicketConfirmationView(discord.ui.View):
    def __init__(self, cog, user: discord.User, guild: discord.Guild, initial_message: discord.Message, departments: dict):
        super().__init__(timeout=180)
        self.cog = cog
        self.user = user
        self.guild = guild
        self.initial_message = initial_message
        self.message = None

        button_styles = [
            discord.ButtonStyle.primary,
            discord.ButtonStyle.success,
            discord.ButtonStyle.secondary
        ]

        for idx, (dept_name, dept_data) in enumerate(departments.items()):
            emoji = None
            if isinstance(dept_data, dict):
                emoji = dept_data.get("emoji")
                
            style = button_styles[idx % len(button_styles)]
                
            button = discord.ui.Button(
                label=f"{dept_name.title()} Department",
                style=style,
                custom_id=f"confirm_{guild.id}_{user.id}_{dept_name}",
                emoji=emoji
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
                channel = await self.cog._create_ticket(self.guild, self.user, dept_name, self.initial_message.content)
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
        self.config = Config.get_conf(self, identifier=8472938474, force_registration=True)
        
        self.config.register_global(default_guild_id=None)
        
        self.config.register_guild(
            log_channel_id=None,
            ticket_category_id=None,
            immune_roles=[],
            blocked_users=[],
            ticket_counter=1000,
            departments={"general": {"role_id": None, "emoji": None, "embed": None}},
            support_hours={"start": None, "end": None},
            response_stats={},
            busy_mode=False,
            auto_responders={},
            snippets={}
        )
        
        self.config.register_user(
            active_channel_id=None,
            history_count=0,
            last_ticket_time=None
        )
        
        self.config.register_channel(
            owner_id=None, 
            claimed_by=None, 
            ticket_id=None,
            department=None,
            waiting_since=None
        )
        
        self.custom_statuses = [
            "🙋 Waiting for support tickets...",
            "🛠️ Moderating the server...",
            "🎫 Need help? DM me to talk to staff!"
        ]
        self.status_index = 0
        
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
                stats[department] = {'in_avg': 0.0, 'in_count': 0, 'out_avg': 0.0, 'out_count': 0}
            
            prefix = 'in' if was_in_hours else 'out'
            current_avg = stats[department][f'{prefix}_avg']
            current_count = stats[department][f'{prefix}_count']
            
            new_count = current_count + 1
            new_avg = ((current_avg * current_count) + wait_time_seconds) / new_count
            
            stats[department][f'{prefix}_avg'] = new_avg
            stats[department][f'{prefix}_count'] = new_count

    async def _get_reply_context(self, message: discord.Message):
        if not message.reference:
            return None, None
        
        ref_msg = message.reference.resolved
        if not isinstance(ref_msg, discord.Message):
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                return None, None
        
        if not ref_msg:
            return None, None

        author_name = ref_msg.author.name
        if ref_msg.author.bot and ref_msg.embeds:
            embed_obj = ref_msg.embeds[0]
            if embed_obj.author and embed_obj.author.name:
                author_name = embed_obj.author.name

        content = ref_msg.content
        if not content and ref_msg.embeds and ref_msg.embeds[0].description:
            content = ref_msg.embeds[0].description
        if not content:
            content = "*[Attachment/Media]*"

        if len(content) > 150:
            content = content[:147] + "..."

        return author_name, content

    @tasks.loop(seconds=30)
    async def presence_loop(self):
        default_guild_id = await self.config.default_guild_id()
        if not default_guild_id: 
            return
        guild = self.bot.get_guild(default_guild_id)
        if not guild: 
            return
            
        busy_mode = await self.config.guild(guild).busy_mode()
        
        if busy_mode:
            target_status = discord.Status.dnd
        else:
            hours = await self.config.guild(guild).support_hours()
            in_hours = self.is_in_hours(hours.get('start'), hours.get('end'))
            target_status = discord.Status.online if in_hours else discord.Status.idle
        
        status_text = self.custom_statuses[self.status_index]
        self.status_index = (self.status_index + 1) % len(self.custom_statuses)
        
        await self.bot.change_presence(status=target_status, activity=discord.CustomActivity(name=status_text))

    @presence_loop.before_loop
    async def before_presence_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_typing(self, channel, user, when):
        if user.bot:
            return
        if isinstance(channel, discord.DMChannel):
            active_channel_id = await self.config.user(user).active_channel_id()
            if active_channel_id:
                ticket_channel = self.bot.get_channel(active_channel_id)
                if ticket_channel:
                    await ticket_channel.typing()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        if payload.guild_id is None:
            active_channel_id = await self.config.user_from_id(payload.user_id).active_channel_id()
            if active_channel_id:
                ticket_channel = self.bot.get_channel(active_channel_id)
                if ticket_channel:
                    user = self.bot.get_user(payload.user_id)
                    username = user.name if user else "User"
                    emoji_str = str(payload.emoji)
                    
                    embed = discord.Embed(
                        description=f"Reacted with {emoji_str}",
                        color=discord.Color.blue(),
                        timestamp=datetime.datetime.now(datetime.timezone.utc)
                    )
                    embed.set_author(name=f"{username}", icon_url=user.display_avatar.url if user else None)
                    await ticket_channel.send(embed=embed)

        else:
            owner_id = await self.config.channel_from_id(payload.channel_id).owner_id()
            if owner_id:
                user = self.bot.get_user(owner_id)
                if user:
                    guild = self.bot.get_guild(payload.guild_id)
                    member = payload.member or (guild.get_member(payload.user_id) if guild else None)
                    if member and member.bot:
                        return
                    
                    role_name = member.top_role.name if member else "Staff"
                    emoji_str = str(payload.emoji)
                    now = datetime.datetime.now(datetime.timezone.utc)
                    date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')
                    ticket_id = await self.config.channel_from_id(payload.channel_id).ticket_id() or "UNKNOWN"

                    embed = discord.Embed(
                        description=f"Reacted with {emoji_str}",
                        color=discord.Color.green(),
                        timestamp=now
                    )
                    embed.set_author(name=member.display_name if member else "Staff", icon_url=member.display_avatar.url if member else None)
                    embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                    
                    try:
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass

    async def _create_ticket(self, guild: discord.Guild, user: discord.User, department: str = "general", initial_message_content: str = ""):
        departments = await self.config.guild(guild).departments()
        if not isinstance(departments, dict) or department not in departments:
            department = "general"
            
        dept_data = departments.get(department)
        role_id = dept_data.get("role_id") if isinstance(dept_data, dict) else None
        
        master_category_id = await self.config.guild(guild).ticket_category_id()
        category = guild.get_channel(master_category_id) if master_category_id else None

        counter = await self.config.guild(guild).ticket_counter() + 1
        await self.config.guild(guild).ticket_counter.set(counter)
        prefix = department[0].upper() if department else "G"
        ticket_id = f"{prefix}{counter}"

        channel_name = f"{ticket_id.lower()}-{user.name}".lower().replace(" ", "-")
        channel = await guild.create_text_channel(name=channel_name, category=category)

        if role_id:
            dept_role = guild.get_role(role_id)
            if dept_role:
                await channel.set_permissions(dept_role, read_messages=True, send_messages=True)

        now = datetime.datetime.now(datetime.timezone.utc)
        
        history_count = await self.config.user(user).history_count()
        last_ticket_time = await self.config.user(user).last_ticket_time()
        
        await self.config.user(user).history_count.set(history_count + 1)
        await self.config.user(user).last_ticket_time.set(now.timestamp())
        
        await self.config.user(user).active_channel_id.set(channel.id)
        await self.config.channel(channel).owner_id.set(user.id)
        await self.config.channel(channel).ticket_id.set(ticket_id)
        await self.config.channel(channel).department.set(department)
        await self.config.channel(channel).waiting_since.set(now.timestamp())

        hours = await self.config.guild(guild).support_hours()
        in_hours = self.is_in_hours(hours.get('start'), hours.get('end'))
        stats = await self.config.guild(guild).response_stats()
        busy_mode = await self.config.guild(guild).busy_mode()
        auto_responders = await self.config.guild(guild).auto_responders()
        
        dept_stats = stats.get(department, {})
        time_prefix = 'in' if in_hours else 'out'
        avg_wait = dept_stats.get(f'{time_prefix}_avg', 0)
        
        if avg_wait == 0:
            avg_str = "Calculating statistics..."
        else:
            avg_str = f"~{int(avg_wait // 60)}m {int(avg_wait % 60)}s"

        created_at = f"<t:{int(user.created_at.timestamp())}:R>"
        
        if history_count == 0:
            history_str = "First ticket! (0 previous)"
        else:
            last_time_str = f"<t:{int(last_ticket_time)}:R>" if last_ticket_time else "Unknown"
            history_str = f"{history_count} previous ticket(s)\n**Last Ticket:** {last_time_str}"

        embed = discord.Embed(
            title=f"🎫 Ticket Created - {ticket_id}",
            color=discord.Color.green(),
            timestamp=now
        )
        desc = (f"Support channel created for {user.mention} (`{user.id}`).\n\n"
                f"**Ticket ID:** `{ticket_id}`\n"
                f"**Account Created:** {created_at}\n"
                f"**Past Tickets:** {history_str}\n\n"
                f"**Avg Response Time ({'In-Hours' if in_hours else 'Out-of-Hours'}):** `{avg_str}`\n\n"
                f"Type here to reply, or use `!anon ` to send anonymous messages.\n"
                f"Use `!n ` for internal notes that won't be sent to the user.")
        
        if busy_mode:
            desc += "\n\n⚠️ **Notice:** This ticket was opened during high volume congestion parameters."

        next_open = None
        if not in_hours and hours.get('start'):
            next_open = self.get_next_open_timestamp(hours.get('start'))
            if next_open:
                desc += f"\n\n🌙 **Notice:** Operations are currently closed. Staff will return <t:{next_open}:R>."

        embed.description = desc
        embed.set_thumbnail(url=user.display_avatar.url)
        await channel.send(embed=embed)
        
        try:
            user_embed = discord.Embed(
                title=f"✅ Ticket Opened ({ticket_id})",
                description=f"You are connected to the **{department.title()}** department.",
                color=discord.Color.green(),
                timestamp=now
            )
            
            user_embed.add_field(
                name=f"Expected Response Time ({'In-Hours' if in_hours else 'Out-of-Hours'})",
                value=f"`{avg_str}`",
                inline=False
            )
            
            if busy_mode:
                user_embed.add_field(
                    name="⚠️ High Ticket Volume Warning",
                    value="We are currently experiencing a large influx of support tickets. There may be a longer delay than usual before staff are able to answer. Thank you for your understanding and patience!",
                    inline=False
                )
                
            if not in_hours and next_open:
                user_embed.add_field(
                    name="🌙 Operations Closed",
                    value=f"We are currently closed. The team will review your request when online <t:{next_open}:R>.",
                    inline=False
                )
            
            await user.send(embed=user_embed)

            dept_embed_dict = dept_data.get("embed") if isinstance(dept_data, dict) else None
            if dept_embed_dict:
                custom_greeting_embed = discord.Embed.from_dict(dept_embed_dict)
                await user.send(embed=custom_greeting_embed)
            
            if initial_message_content:
                matched_response = None
                for kw, resp in auto_responders.items():
                    if kw.lower() in initial_message_content.lower():
                        matched_response = resp
                        break
                        
                if matched_response:
                    ar_embed = discord.Embed(
                        title="🤖 Automated Response",
                        description=matched_response,
                        color=discord.Color.blue(),
                        timestamp=now
                    )
                    await user.send(embed=ar_embed)
                    
                    chan_ar_embed = discord.Embed(
                        title="🤖 Auto-Responder Triggered",
                        description=f"**Trigger:** User's first message matched a keyword.\n**Response Sent:**\n{matched_response}",
                        color=discord.Color.blue(),
                        timestamp=now
                    )
                    await channel.send(embed=chan_ar_embed)
                    
        except discord.Forbidden:
            await channel.send("⚠️ **Warning:** The user has DMs disabled.")

        return channel

    async def _generate_html_transcript(self, channel: discord.TextChannel, owner: discord.User, closer: discord.Member, reason: str, ticket_id: str) -> discord.File:
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
                <p><strong>Channel Name:</strong> {channel.name}</p>
                <p><strong>User:</strong> {owner.name} ({owner.id})</p>
                <p><strong>Closed By:</strong> {closer.name} ({closer.id})</p>
                <p><strong>Reason:</strong> {reason}</p>
                <p><strong>Date Saved:</strong> {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
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
            is_anon_msg = False

            member_obj = guild.get_member(m.author.id)
            if member_obj:
                role_str = member_obj.top_role.name
                if not m.author.bot:
                    username = member_obj.display_name

            if m.author.bot and m.embeds:
                embed_obj = m.embeds[0]
                if embed_obj.author and embed_obj.author.name:
                    if embed_obj.author.name.startswith("[Anonymous]"):
                        is_anon_msg = True
                        username = embed_obj.author.name.replace("[Anonymous] ", "")
                        avatar_url = embed_obj.author.icon_url or avatar_url
                    elif embed_obj.author.name == "Support Team":
                        is_anon_msg = True
                        username = "Support Team"
                        avatar_url = embed_obj.author.icon_url or avatar_url
                    else:
                        username = embed_obj.author.name
                        avatar_url = embed_obj.author.icon_url or avatar_url
                
                if embed_obj.footer and embed_obj.footer.text:
                    parts = [p.strip() for p in embed_obj.footer.text.split("|")]
                    for part in parts:
                        if part.startswith("Role:"):
                            role_str = part.replace("Role: ", "")
                        if "UTC" in part and not part.startswith("Ticket ID"):
                            timestamp = part

                if embed_obj.description:
                    content = embed_obj.description
            
            attachments_html = ""
            for a in m.attachments:
                if a.content_type and a.content_type.startswith('image/'):
                    attachments_html += f'<br><img class="attachment" src="{a.url}">'
                else:
                    attachments_html += f'<br><a href="{a.url}" style="color: #00a8fc;">[Attachment: {a.filename}]</a>'

            if not content and not attachments_html:
                continue

            if is_anon_msg:
                role_str = ""

            footer_meta = f" - {role_str}" if role_str else ""

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

                waiting = await self.config.channel(channel).waiting_since()
                if not waiting:
                    await self.config.channel(channel).waiting_since.set(now.timestamp())

                ticket_id = await self.config.channel(channel).ticket_id() or "UNKNOWN"
                member = guild.get_member(message.author.id)
                role_name = member.top_role.name if member else "User"
                date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')

                reply_author, reply_text = await self._get_reply_context(message)

                files = [await a.to_file() for a in message.attachments]
                embed = discord.Embed(description=message.content, color=discord.Color.blue(), timestamp=now)
                embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                
                if reply_author and reply_text:
                    embed.add_field(name=f"💬 Replying to {reply_author}", value=f"> {reply_text}", inline=False)

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
                    departments = {"general": {"role_id": None, "emoji": None, "embed": None}}
                
                if len(departments) == 1:
                    dept_name = list(departments.keys())[0]
                    try:
                        channel = await self._create_ticket(guild, message.author, dept_name, message.content)
                        if channel:
                            role_name = member.top_role.name if member else "User"
                            ticket_id = await self.config.channel(channel).ticket_id() or "UNKNOWN"
                            date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')
                            
                            reply_author, reply_text = await self._get_reply_context(message)

                            files = [await a.to_file() for a in message.attachments]
                            embed = discord.Embed(description=message.content, color=discord.Color.blue(), timestamp=now)
                            embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                            embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                            
                            if reply_author and reply_text:
                                embed.add_field(name=f"💬 Replying to {reply_author}", value=f"> {reply_text}", inline=False)

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
                except discord.Forbidden:
                    pass

        else:
            owner_id = await self.config.channel(message.channel).owner_id()
            if owner_id:
                ctx = await self.bot.get_context(message)
                
                is_anon = False
                is_note = False
                clean_content = message.content

                if message.content.startswith("!anon "):
                    is_anon = True
                    clean_content = message.content[6:].strip()
                elif message.content.startswith("!n "):
                    is_note = True
                    clean_content = message.content[3:].strip()
                elif message.content.startswith("!"):
                    snippets = await self.config.guild(message.guild).snippets()
                    first_word = message.content.split()[0][1:]
                    if first_word in snippets:
                        snippet = snippets[first_word]
                        is_anon = snippet.get("anon", False)
                        clean_content = snippet.get("text", "")
                    elif ctx.valid:
                        return  
                elif ctx.valid:
                    return  

                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass

                files_for_channel = [await a.to_file() for a in message.attachments]
                files_for_user = [await a.to_file() for a in message.attachments]

                member = message.guild.get_member(message.author.id)
                staff_name = member.display_name if member else message.author.display_name

                if is_note:
                    note_embed = discord.Embed(
                        title="📝 Internal Note", 
                        description=clean_content, 
                        color=discord.Color.gold(),
                        timestamp=now
                    )
                    note_embed.set_author(name=staff_name, icon_url=message.author.display_avatar.url)
                    await message.channel.send(embed=note_embed, files=files_for_channel)
                    return

                waiting_since = await self.config.channel(message.channel).waiting_since()
                if waiting_since:
                    wait_time = now.timestamp() - waiting_since
                    dept = await self.config.channel(message.channel).department()
                    hours = await self.config.guild(message.guild).support_hours()
                    was_in_hours = self.is_in_hours(hours.get('start'), hours.get('end'))
                    
                    await self.update_average(message.guild, dept, wait_time, was_in_hours)
                    await self.config.channel(message.channel).waiting_since.set(None)

                user = self.bot.get_user(owner_id)
                if not user:
                    warning_embed = discord.Embed(description="⚠️ Error: User not found. They may have left the server.", color=discord.Color.red())
                    return await message.channel.send(embed=warning_embed)

                ticket_id = await self.config.channel(message.channel).ticket_id() or "UNKNOWN"
                role_name = member.top_role.name if member else "Staff"
                date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')

                reply_author, reply_text = await self._get_reply_context(message)

                try:
                    user_embed = discord.Embed(description=clean_content, color=discord.Color.green(), timestamp=now)
                    
                    if reply_author and reply_text:
                        user_embed.add_field(name=f"💬 Replying to {reply_author}", value=f"> {reply_text}", inline=False)

                    if is_anon:
                        guild_icon = message.guild.icon.url if message.guild.icon else self.bot.user.display_avatar.url
                        user_embed.set_author(name="Support Team", icon_url=guild_icon)
                        user_embed.set_footer(text=f"Ticket ID: {ticket_id} | {date_time_str}")
                    else:
                        user_embed.set_author(name=staff_name, icon_url=message.author.display_avatar.url)
                        user_embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                    
                    await user.send(embed=user_embed, files=files_for_user)

                    chan_embed = discord.Embed(description=clean_content, color=discord.Color.dark_grey() if is_anon else discord.Color.light_embed(), timestamp=now)
                    
                    if is_anon:
                        chan_embed.set_author(name=f"[Anonymous] {staff_name}", icon_url=message.author.display_avatar.url)
                    else:
                        chan_embed.set_author(name=staff_name, icon_url=message.author.display_avatar.url)
                        
                    chan_embed.set_footer(text=f"Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                    
                    if reply_author and reply_text:
                        chan_embed.add_field(name=f"💬 Replying to {reply_author}", value=f"> {reply_text}", inline=False)
                        
                    await message.channel.send(embed=chan_embed, files=files_for_channel)

                except discord.Forbidden:
                    error_embed = discord.Embed(description="❌ Error: The user has DMs disabled.", color=discord.Color.red())
                    await message.channel.send(embed=error_embed)

    ticket_group = app_commands.Group(name="modmail", description="Commands for managing modmail tickets")

    @ticket_group.command(name="open", description="Open a ticket for a specific user.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_open(self, interaction: discord.Interaction, user: discord.User):
        active_channel_id = await self.config.user(user).active_channel_id()
        if active_channel_id and interaction.guild.get_channel(active_channel_id):
            return await interaction.response.send_message(f"❌ This user already has an open ticket: <#{active_channel_id}>", ephemeral=True)

        channel = await self._create_ticket(interaction.guild, user, "general", "")
        await interaction.response.send_message(f"✅ Ticket channel created in {channel.mention}", ephemeral=True)

    @ticket_group.command(name="claim", description="Claim this ticket to show you are handling it.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_claim(self, interaction: discord.Interaction):
        owner_id = await self.config.channel(interaction.channel).owner_id()
        if not owner_id:
            return await interaction.response.send_message("❌ This channel is not an active ticket.", ephemeral=True)
        
        await interaction.channel.edit(topic=f"Assigned Handler: {interaction.user.display_name}")
        
        embed = discord.Embed(
            description=f"✋ **{interaction.user.mention} is now handling this ticket.**",
            color=discord.Color.brand_green()
        )
        await interaction.response.send_message(embed=embed)

    @ticket_group.command(name="transfer", description="Move this ticket to another department.")
    @app_commands.describe(department="The name of the department to move this ticket to.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_transfer(self, interaction: discord.Interaction, department: str):
        owner_id = await self.config.channel(interaction.channel).owner_id()
        if not owner_id:
            return await interaction.response.send_message("❌ This channel is not an active ticket.", ephemeral=True)

        departments = await self.config.guild(interaction.guild).departments()
        department = department.lower()

        if not isinstance(departments, dict) or department not in departments:
            options = ", ".join([d.title() for d in departments.keys()]) if isinstance(departments, dict) else "None"
            return await interaction.response.send_message(f"❌ Department not found. Options: `{options}`", ephemeral=True)

        old_dept = await self.config.channel(interaction.channel).department()
        old_dept_data = departments.get(old_dept) if isinstance(departments, dict) else {}
        old_role_id = old_dept_data.get("role_id") if isinstance(old_dept_data, dict) else None

        dept_data = departments[department]
        new_role_id = dept_data.get("role_id") if isinstance(dept_data, dict) else None

        if old_role_id:
            old_role = interaction.guild.get_role(old_role_id)
            if old_role:
                await interaction.channel.set_permissions(old_role, overwrite=None)

        if new_role_id:
            new_role = interaction.guild.get_role(new_role_id)
            if new_role:
                await interaction.channel.set_permissions(new_role, read_messages=True, send_messages=True)

        ticket_id = await self.config.channel(interaction.channel).ticket_id() or "UNKNOWN"
        await self.config.channel(interaction.channel).department.set(department)
        
        success_embed = discord.Embed(
            description=f"✅ Ticket moved to the **{department.title()}** department.",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=success_embed)

        user = self.bot.get_user(owner_id)
        if user:
            try:
                embed = discord.Embed(
                    title="🔄 Department Transferred",
                    description=f"Your open ticket (**{ticket_id}**) has been successfully moved to the **{department.title()}** department.",
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                embed.set_footer(text="A specialized support member will be with you shortly.")
                await user.send(embed=embed)

                dept_embed_dict = dept_data.get("embed") if isinstance(dept_data, dict) else None
                if dept_embed_dict:
                    custom_greeting_embed = discord.Embed.from_dict(dept_embed_dict)
                    await user.send(embed=custom_greeting_embed)

            except discord.Forbidden:
                pass

    @ticket_group.command(name="close", description="Closed this ticket and save the transcript logs.")
    @app_commands.describe(reason="The reason for closing the ticket.")
    @app_commands.default_permissions(manage_messages=True)
    async def ticket_close(self, interaction: discord.Interaction, reason: str):
        owner_id = await self.config.channel(interaction.channel).owner_id()
        if not owner_id:
            return await interaction.response.send_message("❌ This channel is not an active ticket.", ephemeral=True)

        closing_embed = discord.Embed(
            description="🔒 Closing ticket and archiving transcript...",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=closing_embed, ephemeral=True)
        
        ticket_id = await self.config.channel(interaction.channel).ticket_id() or "UNKNOWN"
        user = self.bot.get_user(owner_id)
        owner_obj = user or discord.Object(id=owner_id)
        owner_obj.name = user.name if user else "Offline Identity"

        transcript_file = await self._generate_html_transcript(interaction.channel, owner_obj, interaction.user, reason, ticket_id)

        log_channel_id = await self.config.guild(interaction.guild).log_channel_id()
        log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None
        
        if log_channel:
            date_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %I:%M %p UTC')
            embed = discord.Embed(title=f"🔒 Archived Ticket Record - {ticket_id}", color=discord.Color.red())
            embed.add_field(name="User", value=f"<@{owner_id}> ({owner_id})")
            embed.add_field(name="Closed By", value=interaction.user.mention)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.set_footer(text=f"Archive Date: {date_str}")
            await log_channel.send(embed=embed, file=transcript_file)

        if user:
            try:
                date_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %I:%M %p UTC')
                user_embed = discord.Embed(
                    title=f"🔒 Ticket Closed - {ticket_id}",
                    description=f"Your ticket has been closed by **{interaction.user.display_name}**.",
                    color=discord.Color.red(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc)
                )
                user_embed.add_field(name="Reason", value=reason, inline=False)
                user_embed.set_footer(text=f"Date: {date_str}")
                await user.send(embed=user_embed)
            except discord.Forbidden:
                pass
        
        await self.config.user_from_id(owner_id).active_channel_id.set(None)
        await self.config.channel(interaction.channel).clear()
        await interaction.channel.delete(reason=f"Modmail closure by {interaction.user.name}")

    @commands.group(name="modmailset")
    @commands.admin_or_permissions(manage_guild=True)
    async def modmailset(self, ctx):
        pass

    @modmailset.command(name="busy")
    async def modmailset_busy(self, ctx):
        current_state = await self.config.guild(ctx.guild).busy_mode()
        new_state = not current_state
        await self.config.guild(ctx.guild).busy_mode.set(new_state)
        
        if new_state:
            await ctx.send("🚨 **Busy mode has been ENABLED.**\n"
                           "* The bot status is now overridden to **Do Not Disturb**.\n"
                           "* New ticket owners will receive a dynamic high-volume warning embed field.")
        else:
            await ctx.send("✅ **Busy mode has been DISABLED.** Normal scheduling operations resumed.")

    @modmailset.command(name="hours")
    async def modmailset_hours(self, ctx, start_time: str = None, end_time: str = None):
        if not start_time or not end_time:
            await self.config.guild(ctx.guild).support_hours.set({"start": None, "end": None})
            return await ctx.send("✅ Support hours cleared. Modmail will operate 24/7.")
            
        try:
            datetime.datetime.strptime(start_time, "%H:%M")
            datetime.datetime.strptime(end_time, "%H:%M")
        except ValueError:
            return await ctx.send("❌ Invalid format. Please use 24h format `HH:MM` (e.g. `09:00 17:00`).")

        await self.config.guild(ctx.guild).support_hours.set({"start": start_time, "end": end_time})
        await ctx.send(f"✅ Operational support hours mapped from **{start_time} to {end_time} UTC**.")

    @modmailset.command(name="setdefault")
    async def modmailset_setdefault(self, ctx):
        await self.config.default_guild_id.set(ctx.guild.id)
        await ctx.send(f"✅ **{ctx.guild.name}** has been established as the destination server.")

    @modmailset.command(name="logchannel")
    async def modmailset_logchannel(self, ctx, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).log_channel_id.set(channel.id)
        await ctx.send(f"✅ Logs will now be saved in {channel.mention}.")

    @modmailset.command(name="category")
    async def modmailset_category(self, ctx, category: discord.CategoryChannel):
        await self.config.guild(ctx.guild).ticket_category_id.set(category.id)
        await ctx.send(f"✅ All new tickets will now be created in the **{category.name}** category.")

    @modmailset.group(name="department")
    async def modmailset_department(self, ctx):
        pass

    @modmailset_department.command(name="set")
    async def m_dep_set(self, ctx, name: str, role: discord.Role):
        name = name.lower()
        async with self.config.guild(ctx.guild).departments() as deps:
            if not isinstance(deps, dict):
                deps = {}
            if name not in deps or not isinstance(deps[name], dict):
                deps[name] = {"role_id": role.id, "emoji": None, "embed": None}
            else:
                deps[name]["role_id"] = role.id
        await ctx.send(f"✅ Department **{name.title()}** is now securely handled by the **{role.name}** role.")

    @modmailset_department.command(name="emoji")
    async def m_dep_emoji(self, ctx, name: str, emoji: str = None):
        name = name.lower()
        async with self.config.guild(ctx.guild).departments() as deps:
            if name not in deps:
                return await ctx.send(f"❌ Department `{name.title()}` does not exist. Please configure it first.")
            deps[name]["emoji"] = emoji
        if emoji:
            await ctx.send(f"✅ Department **{name.title()}** now uses emoji: {emoji}")
        else:
            await ctx.send(f"✅ Department **{name.title()}** emoji stripped.")

    @modmailset_department.command(name="message")
    async def m_dep_message(self, ctx, name: str):
        name = name.lower()
        departments = await self.config.guild(ctx.guild).departments()
        if not isinstance(departments, dict) or name not in departments:
            return await ctx.send(f"❌ Department `{name.title()}` does not exist.")
            
        existing_embed = departments[name].get("embed")
        view = EmbedBuilderView(self, ctx, name, existing_embed)
        
        await ctx.send(
            "**Interactive Greeting Embed Builder**\n"
            "This will create the greeting that is automatically sent to users when they open a ticket in this department.\n\n"
            "Click a button below to begin:",
            embed=view.current_embed,
            view=view
        )

    @modmailset_department.command(name="remove")
    async def m_dep_remove(self, ctx, name: str):
        name = name.lower()
        async with self.config.guild(ctx.guild).departments() as deps:
            if isinstance(deps, dict) and name in deps:
                del deps[name]
                await ctx.send(f"✅ Department **{name.title()}** has been removed.")
            else:
                await ctx.send(f"❌ Department **{name.title()}** does not exist.")

    @modmailset.command(name="snippet")
    async def modmailset_snippet(self, ctx, name: str, is_anonymous: bool, *, text: str):
        name = name.lower()
        async with self.config.guild(ctx.guild).snippets() as snips:
            snips[name] = {"anon": is_anonymous, "text": text}
        await ctx.send(f"✅ Saved macro snippet `{name}`. Staff can now use `!{name}` to deploy.")

    @modmailset.command(name="autoresponder")
    async def modmailset_autoresponder(self, ctx, keyword: str, *, response: str):
        keyword = keyword.lower()
        async with self.config.guild(ctx.guild).auto_responders() as ar:
            ar[keyword] = response
        await ctx.send(f"✅ Automated trigger keyword `{keyword}` initialized and mapped.")

async def setup(bot):
    await bot.add_cog(Modmail(bot))
