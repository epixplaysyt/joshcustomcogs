import discord
import json
import secrets
from typing import Dict
from redbot.core import commands, app_commands, Config

TEMPLATE_COLOR = 15702551
TEMPLATE_FOOTER_TEXT = "Copyright © MM Tech Studios: https://discord.com/invite/DVaRQRQRcB"
TEMPLATE_FOOTER_ICON = "https://cdn.discordapp.com/icons/1180039158778052608/1166261e5d411b9ff13dc94e39d7aeeb.png"


class EmbedJSONModal(discord.ui.Modal, title="Create Custom Embed"):
    """Modal for pasting JSON to generate a Discord embed."""
    
    json_payload = discord.ui.TextInput(
        label="Embed JSON",
        style=discord.TextStyle.paragraph,
        placeholder='{"title": "Example", "description": "This is a test embed."}',
        required=True
    )

    def __init__(self, target_user: discord.Member):
        super().__init__()
        self.target_user = target_user

    async def on_submit(self, interaction: discord.Interaction):
        try:
            data = json.loads(self.json_payload.value)
            embed = discord.Embed.from_dict(data)
            
            await self.target_user.send(embed=embed)
            await interaction.response.send_message(f"✅ Successfully sent the custom embed to **{self.target_user.display_name}**.", ephemeral=True)
        except json.JSONDecodeError:
            await interaction.response.send_message("❌ Invalid JSON format. Please check your syntax and try again.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Could not send a DM to **{self.target_user.display_name}**. They likely have DMs disabled.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: `{e}`", ephemeral=True)


class DMUtils(commands.Cog):
    """Utilities for direct messaging users using a standardized brand template."""

    def __init__(self, bot):
        self.bot = bot
        self.active_conversations: Dict[int, int] = {}
        
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        default_guild = {
            "prizes": {}
        }
        self.config.register_guild(**default_guild)

    def _apply_template(self, embed: discord.Embed) -> discord.Embed:
        """Helper method to inject the strict brand layout configurations."""
        embed.color = TEMPLATE_COLOR
        embed.set_footer(text=TEMPLATE_FOOTER_TEXT, icon_url=TEMPLATE_FOOTER_ICON)
        return embed

    def _handle_proof_attachment(self, embed: discord.Embed, url: str, field_name: str):
        """Helper to embed proof images or fallback to a text link if it is not an image."""
        # Strip Discord URL query parameters (?ex=...&is=...) to safely isolate the file extension
        clean_url = url.split("?")[0].lower()
        image_extensions = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
        
        if any(clean_url.endswith(ext) for ext in image_extensions):
            embed.set_image(url=url)
        else:
            # Only display the text hyperlink if the file cannot be embedded as a native image
            embed.add_field(name=field_name, value=f"[Click here to view proof]({url})", inline=False)

    @commands.command(name="prizenotify")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def prize_notify(self, ctx: commands.Context, user: discord.Member, amount: str, proof_url: str):
        """Notify a user that their prize has been paid out and generate a tracking ID."""
        prize_id = secrets.token_hex(4).upper()

        embed = discord.Embed(
            title="🎉 Prize Payout Confirmation",
            description="Congratulations! Your recent prize has been successfully processed and paid out."
        )
        embed.set_author(name=f"Verification ID: #{prize_id}")
        embed.add_field(name="Amount", value=amount, inline=True)
        embed.add_field(name="Authorized By", value=ctx.author.display_name, inline=True)
        
        self._handle_proof_attachment(embed, proof_url, "Proof of Payment")
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            
            async with self.config.guild(ctx.guild).prizes() as prizes:
                prizes[prize_id] = {
                    "user_id": user.id,
                    "user_name": str(user),
                    "amount": amount,
                    "authorizer_id": ctx.author.id,
                    "authorizer_name": str(ctx.author),
                    "proof_url": proof_url
                }
                
            await ctx.send(f"✅ Prize payout notification successfully sent to **{user.display_name}**. (ID: `#{prize_id}`)")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not send the notification.")

    @commands.hybrid_command(name="prizesearch")
    @commands.guild_only()
    @app_commands.describe(prize_id="The unique verification ID of the prize")
    async def prize_search(self, ctx: commands.Context, prize_id: str):
        """Search for a prize record by its verification ID to check for scams."""
        clean_id = prize_id.upper().replace("#", "").strip()
        prizes = await self.config.guild(ctx.guild).prizes()
        
        if clean_id not in prizes:
            return await ctx.send(f"❌ No registered prize found matching the ID: `#{clean_id}`.", ephemeral=True)

        data = prizes[clean_id]
        
        embed = discord.Embed(
            title=f"🔍 Prize Record Found",
            description=f"Authentic receipt verification details for transaction identifier `#{clean_id}`."
        )
        embed.set_author(name=f"Database Verification Success")
        embed.add_field(name="Recipient", value=f"<@{data['user_id']}> ({data['user_name']})", inline=False)
        embed.add_field(name="Amount Paid", value=data['amount'], inline=True)
        embed.add_field(name="Authorized By", value=f"<@{data['authorizer_id']}> ({data['authorizer_name']})", inline=True)
        
        self._handle_proof_attachment(embed, data['proof_url'], "Proof Registry Link")
        self._apply_template(embed)
        
        # ephemeral=True makes the slash command response private to the person executing it
        await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="staffmessage")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def staff_message(self, ctx: commands.Context, user: discord.Member, *, message: str):
        """Send a direct message to a user as staff."""
        embed = discord.Embed(
            title="Message from Server Staff",
            description=f"{message}\n\n*ℹ️ You can reply directly to this DM to message the staff member back.*"
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            self.active_conversations[user.id] = ctx.author.id
            await ctx.send(f"✅ Message sent to **{user.display_name}**. Any replies they send to me will be forwarded directly to your DMs.")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not deliver the message.")

    @commands.hybrid_command(name="customembed")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    @app_commands.describe(user="The user to send the custom embed to")
    async def custom_embed(self, ctx: commands.Context, user: discord.Member):
        """Opens a modal to paste JSON and sends the resulting embed to a user."""
        if not ctx.interaction:
            return await ctx.send("⚠️ This command requires a modal. Please run it as a slash command (`/customembed`).")
        
        await ctx.interaction.response.send_modal(EmbedJSONModal(user))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for DMs from users to route back to staff."""
        if message.guild is not None or message.author.bot:
            return

        staff_id = self.active_conversations.get(message.author.id)
        if not staff_id:
            return

        staff_member = self.bot.get_user(staff_id)
        if not staff_member:
            return

        embed = discord.Embed(
            title="New Reply Received",
            description=message.content
        )
        embed.set_author(name=f"{message.author.name} ({message.author.id})", icon_url=message.author.display_avatar.url)
        
        self._apply_template(embed)

        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Attachments", value=attachment_urls, inline=False)

        try:
            await staff_member.send(embed=embed)
            await message.add_reaction("✅")
        except discord.Forbidden:
            await message.channel.send("⚠️ I couldn't deliver your message because the staff member's DMs are currently closed.")
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: `{e}`", ephemeral=True)


class DMUtils(commands.Cog):
    """Utilities for direct messaging users using a standardized brand template."""

    def __init__(self, bot):
        self.bot = bot
        self.active_conversations: Dict[int, int] = {}
        
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        default_guild = {
            "prizes": {}
        }
        self.config.register_guild(**default_guild)

    def _apply_template(self, embed: discord.Embed) -> discord.Embed:
        """Helper method to inject the strict brand layout configurations."""
        embed.color = TEMPLATE_COLOR
        embed.set_footer(text=TEMPLATE_FOOTER_TEXT, icon_url=TEMPLATE_FOOTER_ICON)
        return embed

    def _handle_proof_attachment(self, embed: discord.Embed, url: str, field_name: str):
        """Helper to embed proof images or fallback to a text link if it is not an image."""
        clean_url = url.split("?")[0].lower()
        image_extensions = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
        
        if any(clean_url.endswith(ext) for ext in image_extensions):
            embed.set_image(url=url)
        else:
            embed.add_field(name=field_name, value=f"[Click here to view proof]({url})", inline=False)

    @commands.command(name="prizenotify")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def prize_notify(self, ctx: commands.Context, user: discord.Member, amount: str, proof_url: str):
        """Notify a user that their prize has been paid out and generate a tracking ID."""
        prize_id = secrets.token_hex(4).upper()

        embed = discord.Embed(
            title="🎉 Prize Payout Confirmation",
            description="Congratulations! Your recent prize has been successfully processed and paid out."
        )
        embed.set_author(name=f"Verification ID: #{prize_id}")
        embed.add_field(name="Amount", value=amount, inline=True)
        embed.add_field(name="Authorized By", value=ctx.author.display_name, inline=True)
        
        self._handle_proof_attachment(embed, proof_url, "Proof of Payment")
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            
            async with self.config.guild(ctx.guild).prizes() as prizes:
                prizes[prize_id] = {
                    "user_id": user.id,
                    "user_name": str(user),
                    "amount": amount,
                    "authorizer_id": ctx.author.id,
                    "authorizer_name": str(ctx.author),
                    "proof_url": proof_url
                }
                
            await ctx.send(f"✅ Prize payout notification successfully sent to **{user.display_name}**. (ID: `#{prize_id}`)")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not send the notification.")

    @commands.hybrid_command(name="prizesearch")
    @commands.guild_only()
    @app_commands.describe(prize_id="The unique verification ID of the prize")
    async def prize_search(self, ctx: commands.Context, prize_id: str):
        """Search for a prize record by its verification ID to check for scams."""
        clean_id = prize_id.upper().replace("#", "").strip()
        prizes = await self.config.guild(ctx.guild).prizes()
        
        if clean_id not in prizes:
            return await ctx.send(f"❌ No registered prize found matching the ID: `#{clean_id}`.", ephemeral=True)

        data = prizes[clean_id]
        
        embed = discord.Embed(
            title=f"🔍 Prize Record Found",
            description=f"Authentic receipt verification details for transaction identifier `#{clean_id}`."
        )
        embed.set_author(name=f"Database Verification Success")
        embed.add_field(name="Recipient", value=f"<@{data['user_id']}> ({data['user_name']})", inline=False)
        embed.add_field(name="Amount Paid", value=data['amount'], inline=True)
        embed.add_field(name="Authorized By", value=f"<@{data['authorizer_id']}> ({data['authorizer_name']})", inline=True)
        
        self._handle_proof_attachment(embed, data['proof_url'], "Proof Registry Link")
        self._apply_template(embed)
        
        await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="staffmessage")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def staff_message(self, ctx: commands.Context, user: discord.Member, *, message: str):
        """Send a direct message to a user as staff."""
        embed = discord.Embed(
            title="Message from Server Staff",
            description=f"{message}\n\n*ℹ️ You can reply directly to this DM to message the staff member back.*"
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            self.active_conversations[user.id] = ctx.author.id
            await ctx.send(f"✅ Message sent to **{user.display_name}**. Any replies they send to me will be forwarded directly to your DMs.")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not deliver the message.")

    @commands.hybrid_command(name="customembed")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    @app_commands.describe(user="The user to send the custom embed to")
    async def custom_embed(self, ctx: commands.Context, user: discord.Member):
        """Opens a modal to paste JSON and sends the resulting embed to a user."""
        if not ctx.interaction:
            return await ctx.send("⚠️ This command requires a modal. Please run it as a slash command (`/customembed`).")
        
        await ctx.interaction.response.send_modal(EmbedJSONModal(user))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for DMs from users to route back to staff."""
        if message.guild is not None or message.author.bot:
            return

        staff_id = self.active_conversations.get(message.author.id)
        if not staff_id:
            return

        staff_member = self.bot.get_user(staff_id)
        if not staff_member:
            return

        embed = discord.Embed(
            title="New Reply Received",
            description=message.content
        )
        embed.set_author(name=f"{message.author.name} ({message.author.id})", icon_url=message.author.display_avatar.url)
        
        self._apply_template(embed)

        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Attachments", value=attachment_urls, inline=False)

        try:
            await staff_member.send(embed=embed)
            await message.add_reaction("✅")
        except discord.Forbidden:
            await message.channel.send("⚠️ I couldn't deliver your message because the staff member's DMs are currently closed.")        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: `{e}`", ephemeral=True)


class DMUtils(commands.Cog):
    """Utilities for direct messaging users using a standardized brand template."""

    def __init__(self, bot):
        self.bot = bot
        self.active_conversations: Dict[int, int] = {}
        
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        default_guild = {
            "prizes": {}
        }
        self.config.register_guild(**default_guild)

    def _apply_template(self, embed: discord.Embed) -> discord.Embed:
        """Helper method to inject the strict brand layout configurations."""
        embed.color = TEMPLATE_COLOR
        embed.set_footer(text=TEMPLATE_FOOTER_TEXT, icon_url=TEMPLATE_FOOTER_ICON)
        return embed

    def _handle_proof_attachment(self, embed: discord.Embed, url: str, field_name: str):
        """Helper to embed proof images or fallback to a text link if it is not an image."""
        # Strip Discord URL query parameters (?ex=...&is=...) to safely isolate the file extension
        clean_url = url.split("?")[0].lower()
        image_extensions = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
        
        if any(clean_url.endswith(ext) for ext in image_extensions):
            embed.set_image(url=url)
        else:
            # Only display the text hyperlink if the file cannot be embedded as a native image
            embed.add_field(name=field_name, value=f"[Click here to view proof]({url})", inline=False)

    @commands.command(name="prizenotify")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def prize_notify(self, ctx: commands.Context, user: discord.Member, amount: str, proof_url: str):
        """Notify a user that their prize has been paid out and generate a tracking ID."""
        prize_id = secrets.token_hex(4).upper()

        embed = discord.Embed(
            title="🎉 Prize Payout Confirmation",
            description="Congratulations! Your recent prize has been successfully processed and paid out."
        )
        embed.set_author(name=f"Verification ID: #{prize_id}")
        embed.add_field(name="Amount", value=amount, inline=True)
        embed.add_field(name="Authorized By", value=ctx.author.display_name, inline=True)
        
        self._handle_proof_attachment(embed, proof_url, "Proof of Payment")
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            
            async with self.config.guild(ctx.guild).prizes() as prizes:
                prizes[prize_id] = {
                    "user_id": user.id,
                    "user_name": str(user),
                    "amount": amount,
                    "authorizer_id": ctx.author.id,
                    "authorizer_name": str(ctx.author),
                    "proof_url": proof_url
                }
                
            await ctx.send(f"✅ Prize payout notification successfully sent to **{user.display_name}**. (ID: `#{prize_id}`)")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not send the notification.")

    @commands.hybrid_command(name="prizesearch")
    @commands.guild_only()
    @app_commands.describe(prize_id="The unique verification ID of the prize")
    async def prize_search(self, ctx: commands.Context, prize_id: str):
        """Search for a prize record by its verification ID to check for scams."""
        clean_id = prize_id.upper().replace("#", "").strip()
        prizes = await self.config.guild(ctx.guild).prizes()
        
        if clean_id not in prizes:
            return await ctx.send(f"❌ No registered prize found matching the ID: `#{clean_id}`.", ephemeral=True)

        data = prizes[clean_id]
        
        embed = discord.Embed(
            title=f"🔍 Prize Record Found",
            description=f"Authentic receipt verification details for transaction identifier `#{clean_id}`."
        )
        embed.set_author(name=f"Database Verification Success")
        embed.add_field(name="Recipient", value=f"<@{data['user_id']}> ({data['user_name']})", inline=False)
        embed.add_field(name="Amount Paid", value=data['amount'], inline=True)
        embed.add_field(name="Authorized By", value=f"<@{data['authorizer_id']}> ({data['authorizer_name']})", inline=True)
        
        self._handle_proof_attachment(embed, data['proof_url'], "Proof Registry Link")
        self._apply_template(embed)
        
        # ephemeral=True makes the slash command response private to the person executing it
        await ctx.send(embed=embed, ephemeral=True)

    @commands.command(name="staffmessage")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def staff_message(self, ctx: commands.Context, user: discord.Member, *, message: str):
        """Send a direct message to a user as staff."""
        embed = discord.Embed(
            title="Message from Server Staff",
            description=f"{message}\n\n*ℹ️ You can reply directly to this DM to message the staff member back.*"
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            self.active_conversations[user.id] = ctx.author.id
            await ctx.send(f"✅ Message sent to **{user.display_name}**. Any replies they send to me will be forwarded directly to your DMs.")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not deliver the message.")

    @commands.hybrid_command(name="customembed")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    @app_commands.describe(user="The user to send the custom embed to")
    async def custom_embed(self, ctx: commands.Context, user: discord.Member):
        """Opens a modal to paste JSON and sends the resulting embed to a user."""
        if not ctx.interaction:
            return await ctx.send("⚠️ This command requires a modal. Please run it as a slash command (`/customembed`).")
        
        await ctx.interaction.response.send_modal(EmbedJSONModal(user))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for DMs from users to route back to staff."""
        if message.guild is not None or message.author.bot:
            return

        staff_id = self.active_conversations.get(message.author.id)
        if not staff_id:
            return

        staff_member = self.bot.get_user(staff_id)
        if not staff_member:
            return

        embed = discord.Embed(
            title="New Reply Received",
            description=message.content
        )
        embed.set_author(name=f"{message.author.name} ({message.author.id})", icon_url=message.author.display_avatar.url)
        
        self._apply_template(embed)

        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Attachments", value=attachment_urls, inline=False)

        try:
            await staff_member.send(embed=embed)
            await message.add_reaction("✅")
        except discord.Forbidden:
            await message.channel.send("⚠️ I couldn't deliver your message because the staff member's DMs are currently closed.")        
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: `{e}`", ephemeral=True)


class DMUtils(commands.Cog):
    """Utilities for direct messaging users using a standardized brand template."""

    def __init__(self, bot):
        self.bot = bot
        self.active_conversations: Dict[int, int] = {}
        
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        default_guild = {
            "prizes": {}
        }
        self.config.register_guild(**default_guild)

    def _apply_template(self, embed: discord.Embed) -> discord.Embed:
        """Helper method to inject the strict brand layout configurations."""
        embed.color = TEMPLATE_COLOR
        embed.set_footer(text=TEMPLATE_FOOTER_TEXT, icon_url=TEMPLATE_FOOTER_ICON)
        return embed

    def _handle_proof_attachment(self, embed: discord.Embed, url: str, field_name: str):
        """Helper to add proof hyperlinks and embed the image if a valid format is detected."""
        embed.add_field(name=field_name, value=f"[Click here to view proof]({url})", inline=False)
        
        # Strip Discord URL query parameters (?ex=...&is=...) to safely isolate the file extension
        clean_url = url.split("?")[0].lower()
        image_extensions = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
        
        if any(clean_url.endswith(ext) for ext in image_extensions):
            embed.set_image(url=url)

    @commands.command(name="prizenotify")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def prize_notify(self, ctx: commands.Context, user: discord.Member, amount: str, proof_url: str):
        """Notify a user that their prize has been paid out and generate a tracking ID."""
        prize_id = secrets.token_hex(4).upper()

        embed = discord.Embed(
            title="🎉 Prize Payout Confirmation",
            description="Congratulations! Your recent prize has been successfully processed and paid out."
        )
        embed.set_author(name=f"Verification ID: #{prize_id}")
        embed.add_field(name="Amount", value=amount, inline=True)
        embed.add_field(name="Authorized By", value=ctx.author.display_name, inline=True)
        
        # Attach proof hyperlink and attempt image embedding
        self._handle_proof_attachment(embed, proof_url, "Proof of Payment")
        
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            
            async with self.config.guild(ctx.guild).prizes() as prizes:
                prizes[prize_id] = {
                    "user_id": user.id,
                    "user_name": str(user),
                    "amount": amount,
                    "authorizer_id": ctx.author.id,
                    "authorizer_name": str(ctx.author),
                    "proof_url": proof_url
                }
                
            await ctx.send(f"✅ Prize payout notification successfully sent to **{user.display_name}**. (ID: `#{prize_id}`)")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not send the notification.")

    @commands.command(name="prizesearch")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def prize_search(self, ctx: commands.Context, prize_id: str):
        """Search for a prize record by its verification ID to prevent scams."""
        clean_id = prize_id.upper().replace("#", "").strip()
        prizes = await self.config.guild(ctx.guild).prizes()
        
        if clean_id not in prizes:
            return await ctx.send(f"❌ No registered prize found matching the ID: `#{clean_id}`. Treat this interaction with caution.")

        data = prizes[clean_id]
        
        embed = discord.Embed(
            title=f"🔍 Prize Record Found",
            description=f"Authentic receipt verification details for transaction identifier `#{clean_id}`."
        )
        embed.set_author(name=f"Database Lookup")
        embed.add_field(name="Recipient", value=f"<@{data['user_id']}> ({data['user_name']})", inline=False)
        embed.add_field(name="Amount Paid", value=data['amount'], inline=True)
        embed.add_field(name="Authorized By", value=f"<@{data['authorizer_id']}> ({data['authorizer_name']})", inline=True)
        
        # Attach proof hyperlink and attempt image embedding from saved database parameters
        self._handle_proof_attachment(embed, data['proof_url'], "Proof Registry Link")
        
        self._apply_template(embed)
        await ctx.send(embed=embed)

    @commands.command(name="staffmessage")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def staff_message(self, ctx: commands.Context, user: discord.Member, *, message: str):
        """Send a direct message to a user as staff."""
        embed = discord.Embed(
            title="Message from Server Staff",
            description=f"{message}\n\n*ℹ️ You can reply directly to this DM to message the staff member back.*"
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            self.active_conversations[user.id] = ctx.author.id
            await ctx.send(f"✅ Message sent to **{user.display_name}**. Any replies they send to me will be forwarded directly to your DMs.")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not deliver the message.")

    @commands.hybrid_command(name="customembed")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    @app_commands.describe(user="The user to send the custom embed to")
    async def custom_embed(self, ctx: commands.Context, user: discord.Member):
        """Opens a modal to paste JSON and sends the resulting embed to a user."""
        if not ctx.interaction:
            return await ctx.send("⚠️ This command requires a modal. Please run it as a slash command (`/customembed`).")
        
        await ctx.interaction.response.send_modal(EmbedJSONModal(user))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Listen for DMs from users to route back to staff."""
        if message.guild is not None or message.author.bot:
            return

        staff_id = self.active_conversations.get(message.author.id)
        if not staff_id:
            return

        staff_member = self.bot.get_user(staff_id)
        if not staff_member:
            return

        embed = discord.Embed(
            title="New Reply Received",
            description=message.content
        )
        embed.set_author(name=f"{message.author.name} ({message.author.id})", icon_url=message.author.display_avatar.url)
        
        self._apply_template(embed)

        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Attachments", value=attachment_urls, inline=False)

        try:
            await staff_member.send(embed=embed)
            await message.add_reaction("✅")
        except discord.Forbidden:
            await message.channel.send("⚠️ I couldn't deliver your message because the staff member's DMs are currently closed.")
