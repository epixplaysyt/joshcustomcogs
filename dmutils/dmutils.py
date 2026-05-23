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
        # Maps user_id -> {"staff_id": int, "conversation_id": str}
        self.active_conversations: Dict[int, dict] = {}
        
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        default_guild = {
            "prizes": {},
            "messages": {}
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
        prize_id = f"P{secrets.token_hex(4).upper()}"

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

    @commands.command(name="staffmessage")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def staff_message(self, ctx: commands.Context, user: discord.Member, *, message: str):
        """Send an initial message to a user as staff and open an interactive conversation channel."""
        if user.id in self.active_conversations:
            return await ctx.send(f"⚠️ **{user.display_name}** already has an active conversation open. Use `[p]staffreply` to message them.")

        conv_id = f"M{secrets.token_hex(4).upper()}"

        embed = discord.Embed(
            title="Message from Server Staff",
            description=f"{message}\n\n*ℹ️ Reply directly to pass a message back to staff, or type `stop` at any time to end this chat session.*"
        )
        embed.set_author(name=f"{ctx.author.display_name} | Session: #{conv_id}", icon_url=ctx.author.display_avatar.url)
        
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            
            self.active_conversations[user.id] = {
                "staff_id": ctx.author.id,
                "conversation_id": conv_id
            }

            async with self.config.guild(ctx.guild).messages() as messages:
                messages[conv_id] = {
                    "staff_id": ctx.author.id,
                    "staff_name": str(ctx.author),
                    "user_id": user.id,
                    "user_name": str(user),
                    "initial_content": message
                }

            await ctx.send(f"✅ Conversation successfully initiated with **{user.display_name}**. (Session ID: `#{conv_id}`)\nUse `[p]staffreply @user <message>` to keep texting them, or `[p]stopdm @user` to close the connection.")
        except discord.Forbidden:
            await ctx.send(f"❌ **{user.display_name}** has their DMs disabled. I could not deliver the message.")

    @commands.command(name="staffreply")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def staff_reply(self, ctx: commands.Context, user: discord.Member, *, message: str):
        """Send a follow-up reply to an ongoing active conversation stream."""
        session_data = self.active_conversations.get(user.id)
        if not session_data:
            return await ctx.send(f"❌ There are no active message sessions currently open for **{user.display_name}**. Use `[p]staffmessage` first.")

        conv_id = session_data["conversation_id"]

        embed = discord.Embed(
            title="New Reply from Server Staff",
            description=f"{message}\n\n*ℹ️ Reply directly to pass a message back to staff, or type `stop` at any time to end this chat session.*"
        )
        embed.set_author(name=f"{ctx.author.display_name} | Session: #{conv_id}", icon_url=ctx.author.display_avatar.url)
        self._apply_template(embed)

        try:
            await user.send(embed=embed)
            await ctx.message.add_reaction("✅")
        except discord.Forbidden:
            self.active_conversations.pop(user.id, None)
            await ctx.send(f"❌ Failed to deliver message. **{user.display_name}** has closed their DMs. Session `#{conv_id}` has been forcefully terminated.")

    @commands.command(name="stopdm")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_messages=True)
    async def stop_dm(self, ctx: commands.Context, user: discord.Member):
        """Staff command to close an active conversation session channel."""
        session_data = self.active_conversations.pop(user.id, None)
        if not session_data:
            return await ctx.send(f"❌ There are no active chat sessions matching **{user.display_name}**.")

        conv_id = session_data["conversation_id"]
        
        try:
            embed = discord.Embed(
                title="🔒 Conversation Closed",
                description="This staff communication session has been marked as completed and closed by server management. Direct routing is now turned off."
            )
            embed.set_author(name=f"Session: #{conv_id}")
            self._apply_template(embed)
            await user.send(embed=embed)
        except discord.Forbidden:
            pass

        await ctx.send(f"🔒 Session `#{conv_id}` with **{user.display_name}** has been closed successfully.")

    @commands.command(name="stop")
    @commands.dm_only()
    async def user_stop(self, ctx: commands.Context):
        """User command to end an ongoing direct message staff session."""
        session_data = self.active_conversations.pop(ctx.author.id, None)
        if not session_data:
            return await ctx.send("❌ You do not have an active staff conversation session open to close.")

        conv_id = session_data["conversation_id"]
        staff_member = self.bot.get_user(session_data["staff_id"])

        if staff_member:
            try:
                embed = discord.Embed(
                    title="🔒 Session Closed by User",
                    description=f"The active user communication block has been ended by the recipient."
                )
                embed.set_author(name=f"{ctx.author.name} ({ctx.author.id}) | Session: #{conv_id}")
                self._apply_template(embed)
                await staff_member.send(embed=embed)
            except discord.Forbidden:
                pass

        await ctx.send(f"🔒 Conversation `#{conv_id}` has been disconnected. No further messages will be forwarded.")

    @commands.hybrid_command(name="search")
    @commands.guild_only()
    @app_commands.describe(search_id="The unique verification ID starting with P (Prize) or M (Message)")
    async def search(self, ctx: commands.Context, search_id: str):
        """Search the verification registries for an active Prize or Staff Message tracking reference ID."""
        clean_id = search_id.upper().replace("#", "").strip()
        
        if clean_id.startswith("P"):
            prizes = await self.config.guild(ctx.guild).prizes()
            if clean_id not in prizes:
                return await ctx.send(f"❌ No registered prize payout match found for ID: `#{clean_id}`.", ephemeral=True)
            
            data = prizes[clean_id]
            embed = discord.Embed(
                title="🔍 Prize Registry Log Found",
                description=f"Authentic receipt verification details for transaction identifier `#{clean_id}`."
            )
            embed.set_author(name="Database Verification Success")
            embed.add_field(name="Recipient", value=f"<@{data['user_id']}> ({data['user_name']})", inline=False)
            embed.add_field(name="Amount Paid", value=data['amount'], inline=True)
            embed.add_field(name="Authorized By", value=f"<@{data['authorizer_id']}> ({data['authorizer_name']})", inline=True)
            self._handle_proof_attachment(embed, data['proof_url'], "Proof Registry Link")

        elif clean_id.startswith("M"):
            messages = await self.config.guild(ctx.guild).messages()
            if clean_id not in messages:
                return await ctx.send(f"❌ No registered conversation match found for ID: `#{clean_id}`.", ephemeral=True)
            
            data = messages[clean_id]
            embed = discord.Embed(
                title="🔍 Conversation Session Found",
                description=f"Authentic messaging session validation for tracking identifier `#{clean_id}`."
            )
            embed.set_author(name="Database Verification Success")
            embed.add_field(name="Staff Dispatcher", value=f"<@{data['staff_id']}> ({data['staff_name']})", inline=True)
            embed.add_field(name="Target Recipient", value=f"<@{data['user_id']}> ({data['user_name']})", inline=True)
            embed.add_field(name="Opening Content Stack", value=f"```{data['initial_content']}
```", inline=False)

        else:
            return await ctx.send("❌ Invalid format identifier. Verification IDs must begin with **P** (Prizes) or **M** (Messages).", ephemeral=True)

        self._apply_template(embed)
        await ctx.send(embed=embed, ephemeral=True)

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
        """Listen for inbound direct messages from users and forward them contextually to staff."""
        if message.guild is not None or message.author.bot:
            return

        session_data = self.active_conversations.get(message.author.id)
        if not session_data:
            return

        # Explicit plaintext exit check if they type stop instead of running the command structure
        if message.content.strip().lower() == "stop":
            ctx = await self.bot.get_context(message)
            await self.bot.invoke(ctx)
            return

        staff_member = self.bot.get_user(session_data["staff_id"])
        if not staff_member:
            return

        conv_id = session_data["conversation_id"]

        embed = discord.Embed(
            title="New Reply Received",
            description=message.content
        )
        embed.set_author(name=f"{message.author.name} ({message.author.id}) | Session: #{conv_id}", icon_url=message.author.display_avatar.url)
        
        self._apply_template(embed)

        if message.attachments:
            attachment_urls = "\n".join([att.url for att in message.attachments])
            embed.add_field(name="Attachments", value=attachment_urls, inline=False)

        try:
            await staff_member.send(embed=embed)
            await message.add_reaction("✅")
        except discord.Forbidden:
            await message.channel.send("⚠️ I couldn't deliver your message because the staff member's DMs are currently closed.")
