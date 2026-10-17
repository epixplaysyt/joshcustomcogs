import discord

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
        cancel_button.callback = self.cancel_button
        self.add_item(cancel_button)

    def make_callback(self, dept_name):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            self.stop()
            
            try:
                channel = await self.cog._create_ticket(self.guild, self.user, dept_name, self.initial_message.content)
            except Exception:
                await interaction.message.edit(content="❌ Failed to create ticket. Please ensure the bot has 'Manage Channels' permissions.", view=None)
                return

            if channel:
                main_guild = await self.cog._get_main_guild(self.guild)
                member = main_guild.get_member(self.user.id)
                if not member:
                    for g in self.cog.bot.guilds:
                        if g.get_member(self.user.id):
                            member = g.get_member(self.user.id)
                            break
                role_name = member.top_role.name if member else "User"
                ticket_id = await self.cog.config.channel(channel).ticket_id() or "UNKNOWN"
                import datetime
                now = datetime.datetime.now(datetime.timezone.utc)
                date_time_str = now.strftime('%Y-%m-%d %I:%M %p UTC')
                
                files = [await a.to_file() for a in self.initial_message.attachments]
                embed = discord.Embed(
                    description=self.initial_message.content, 
                    color=discord.Color.blue(), 
                    timestamp=now
                )
                embed.set_author(name=self.user.name, icon_url=self.user.display_avatar.url, url=f"https://discord.com/users/{self.user.id}")
                embed.set_footer(text=f"User ID: {self.user.id} | Ticket ID: {ticket_id} | Role: {role_name} | {date_time_str}")
                
                await channel.send(embed=embed, files=files)

                pings = [m.mention for m in self.initial_message.mentions]
                if pings:
                    try:
                        ghost = await channel.send(" ".join(pings))
                        await ghost.delete()
                    except Exception:
                        pass

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

class ReplyConfirmationView(discord.ui.View):
    def __init__(self, cog, author: discord.User, message_content: str, anonymous: bool, attachments=None, specific_target_id=None):
        super().__init__(timeout=300)
        self.cog = cog
        self.author = author
        self.message_content = message_content
        self.anonymous = anonymous
        self.attachments = attachments or []
        self.specific_target_id = specific_target_id
        self.message = None

    @discord.ui.button(label="Yes, Send to All", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_reply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("❌ You cannot use this button.", ephemeral=True)
        
        self.stop()
        for child in self.children:
            child.disabled = True
        
        if interaction.response.is_done():
            try:
                await interaction.edit_original_response(content="✅ **Reply broadcasted successfully!**", embed=None, view=self)
            except Exception:
                pass
        else:
            await interaction.response.edit_message(content="✅ **Reply broadcasted successfully!**", embed=None, view=self)

        await self.cog._execute_staff_reply_action(
            channel=interaction.channel,
            author=self.author,
            content=self.message_content,
            anonymous=self.anonymous,
            attachments=self.attachments,
            specific_target_id=self.specific_target_id
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancel_reply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("❌ You cannot use this button.", ephemeral=True)
        
        self.stop()
        for child in self.children:
            child.disabled = True
        
        if interaction.response.is_done():
            try:
                await interaction.edit_original_response(content="❌ **Reply cancelled.** Message was not sent.", embed=None, view=self)
            except Exception:
                pass
        else:
            await interaction.response.edit_message(content="❌ **Reply cancelled.** Message was not sent.", embed=None, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(content="⏳ Confirmation timed out. Message was not sent.", embed=None, view=self)
        except Exception:
            pass
