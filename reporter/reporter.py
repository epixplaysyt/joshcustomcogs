import discord
from discord import app_commands
from redbot.core import commands, Config
from redbot.core.bot import Red

class MessageReporter(commands.Cog):
    """Report messages to staff via Context Menu."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9483726154, force_registration=True)
        self.config.register_guild(report_channel=None)
      
        self.ctx_menu = app_commands.ContextMenu(
            name="Report Message",
            callback=self._report_message,
        )

    async def cog_load(self):
        """Add the context menu to the bot's command tree on load."""
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        """Remove the context menu from the command tree on unload."""
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.command()
    async def setreportchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel where reported messages will be sent.
        
        Usage: [p]setreportchannel #channel-name
        """
        await self.config.guild(ctx.guild).report_channel.set(channel.id)
        await ctx.send(f"✅ Reports will now be sent to {channel.mention}.")

    async def _report_message(self, interaction: discord.Interaction, message: discord.Message):
        """The callback triggered when a user right-clicks a message and hits Report Message."""
        if not interaction.guild:
            await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
            return

        channel_id = await self.config.guild(interaction.guild).report_channel()
        if not channel_id:
            await interaction.response.send_message(
                "The report channel has not been set up by the server admins.", 
                ephemeral=True
            )
            return
          
        report_channel = interaction.guild.get_channel(channel_id)
        if not report_channel:
            await interaction.response.send_message(
                "The configured report channel could not be found. Please contact an admin.", 
                ephemeral=True
            )
            return
        
        embed = discord.Embed(
            title="🚨 Message Reported",
            description=message.content or "*No text content (may be an image or embed)*",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Reported User", value=f"{message.author.mention}\nID: `{message.author.id}`", inline=True)
        embed.add_field(name="Reporter", value=f"{interaction.user.mention}\nID: `{interaction.user.id}`", inline=True)
        embed.add_field(name="Location", value=f"{message.channel.mention}", inline=False)
        embed.add_field(name="Message Link", value=f"[Click here to jump to message]({message.jump_url})", inline=False)

        if message.attachments:
            embed.add_field(name="Attachments", value=f"{len(message.attachments)} attachment(s) included.", inline=False)
            first_attachment = message.attachments[0]
            if first_attachment.url.lower().endswith(('png', 'jpg', 'jpeg', 'gif', 'webp')):
                embed.set_image(url=first_attachment.url)

        try:
            await report_channel.send(embed=embed)
            await interaction.response.send_message(
                "✅ Thank you. The message has been successfully reported to the staff team.", 
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to send messages to the staff report channel.", 
                ephemeral=True
            )
