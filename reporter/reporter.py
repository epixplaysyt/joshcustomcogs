import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.bot import Red

class ResolveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Mark Resolved", style=discord.ButtonStyle.success, custom_id="resolve_report_button")
    async def resolve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        
        reporter_field = embed.fields[1].value
        reporter_id = int(reporter_field.split("ID: `")[1].split("`")[0])
        
        try:
            user = await interaction.client.fetch_user(reporter_id)
            await user.send("Your recent report has been dealt with. The result cannot be revealed for confidentiality reasons.")
        except discord.HTTPException:
            pass

        embed.color = discord.Color.green()
        embed.title = "✅ Message Reported (Resolved)"
        embed.set_footer(text=f"Resolved by {interaction.user.display_name}")
        
        button.disabled = True
        button.label = "Resolved"
        
        await interaction.response.edit_message(content=f"**Resolved by {interaction.user.mention}**", embed=embed, view=self)

class ReportModal(discord.ui.Modal):
    def __init__(self, message: discord.Message, config: Config):
        super().__init__(title="Report Message")
        self.message = message
        self.config = config

        self.extra_info = discord.ui.TextInput(
            label="Additional Information (Optional)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1024
        )
        self.add_item(self.extra_info)

    async def on_submit(self, interaction: discord.Interaction):
        guild_data = await self.config.guild(interaction.guild).all()
        channel_id = guild_data["report_channel"]
        mod_role_id = guild_data["mod_role"]

        report_channel = interaction.guild.get_channel(channel_id)
        if not report_channel:
            await interaction.response.send_message("The configured report channel could not be found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🚨 Message Reported",
            description=self.message.content or "*No text content*",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Reported User", value=f"{self.message.author.mention}\nID: `{self.message.author.id}`", inline=True)
        embed.add_field(name="Reporter", value=f"{interaction.user.mention}\nID: `{interaction.user.id}`", inline=True)
        embed.add_field(name="Location", value=f"{self.message.channel.mention}", inline=False)
        
        if self.extra_info.value.strip():
            embed.add_field(name="Additional Info", value=self.extra_info.value.strip(), inline=False)

        embed.add_field(name="Message Link", value=f"[Click here to jump to message]({self.message.jump_url})", inline=False)

        if self.message.attachments:
            embed.add_field(name="Attachments", value=f"{len(self.message.attachments)} attachment(s) included.", inline=False)
            first_attachment = self.message.attachments[0]
            if first_attachment.url.lower().endswith(('png', 'jpg', 'jpeg', 'gif', 'webp')):
                embed.set_image(url=first_attachment.url)

        content = ""
        if mod_role_id:
            mod_role = interaction.guild.get_role(mod_role_id)
            if mod_role:
                content = mod_role.mention

        try:
            await report_channel.send(content=content, embed=embed, view=ResolveView())
            await interaction.response.send_message("✅ Thank you. The message has been successfully reported.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to send messages to the staff report channel.", ephemeral=True)

class MessageReporter(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9483726154, force_registration=True)
        self.config.register_guild(report_channel=None, mod_role=None)
        
        self.ctx_menu = app_commands.ContextMenu(
            name="Report Message",
            callback=self._report_message,
        )

    async def cog_load(self):
        self.bot.tree.add_command(self.ctx_menu)
        self.bot.add_view(ResolveView())

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.command()
    async def setreportchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).report_channel.set(channel.id)
        await ctx.send(f"✅ Reports will now be sent to {channel.mention}.")

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.command()
    async def setreportrole(self, ctx: commands.Context, role: discord.Role):
        await self.config.guild(ctx.guild).mod_role.set(role.id)
        await ctx.send(f"✅ The {role.name} role will now be pinged for new reports.")

    async def _report_message(self, interaction: discord.Interaction, message: discord.Message):
        if not interaction.guild:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return

        channel_id = await self.config.guild(interaction.guild).report_channel()
        
        if not channel_id:
            await interaction.response.send_message("The report channel has not been set up.", ephemeral=True)
            return

        await interaction.response.send_modal(ReportModal(message, self.config))
