import discord
from redbot.core import commands, Config
from discord import app_commands
import datetime

# --- Helper Function for Fuzzy Matching ---
def get_edit_distance(s1: str, s2: str) -> int:
    """Calculates the Levenshtein distance between two strings."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for index2, char2 in enumerate(s2):
        new_distances = [index2 + 1]
        for index1, char1 in enumerate(s1):
            if char1 == char2:
                new_distances.append(distances[index1])
            else:
                new_distances.append(1 + min((distances[index1], distances[index1+1], new_distances[-1])))
        distances = new_distances
    return distances[-1]

class ManagerApprovalView(discord.ui.View):
    def __init__(self, cog, interaction: discord.Interaction, channel: discord.TextChannel, answer: str, auto_mark: bool, reg_cd: int, win_cd: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.interaction = interaction
        self.channel = channel
        self.answer = answer
        self.auto_mark = auto_mark
        self.reg_cd = reg_cd
        self.win_cd = win_cd

    @discord.ui.button(label="Allow", style=discord.ButtonStyle.success)
    async def allow(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You have approved the guessing session.")
        await self.cog._open_guessing_channel(self.interaction.guild, self.channel, self.answer, self.auto_mark, self.reg_cd, self.win_cd)
        self.stop()

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You have denied the guessing session.")
        try:
            await self.interaction.user.send("Your request to open the guessing channel was **denied** by a manager.")
        except discord.Forbidden:
            pass
        self.stop()

class Guesses(commands.Cog):
    """Cog for managing a customisable #guesses channel game with auto-marking."""

    def __init__(self, bot):
        self.bot = bot
        
        # RedBot Config Setup
        self.config = Config.get_conf(self, identifier=9283746150, force_registration=True)
        default_guild = {
            "guess_channel_id": None,
            "role_host": None,
            "role_manager": None,
            "role_probation": None,
            "role_winner": None,
            "role_booster": None,
            "msg_open": "🎯 **A new guessing session has started!**\nCheck out the question posted in <#1331301801927905423> and submit your guesses here!",
            "msg_close": "🛑 **Guessing Closed!**\nThe correct answer was: **{answer}**\nGuessed by: {winner}",
            "msg_duplicate": "{user}, you have already made that guess for this question!",
            "msg_cooldown": "{user}, you are on cooldown! You can guess again in {time}."
        }
        self.config.register_guild(**default_guild)

        # In-memory Session State
        self.is_active = False
        self.user_guesses = {} # Tracks guesses per user: {user_id: set(guesses)}
        self.last_guess_time = {} # Tracks cooldowns: {user_id: datetime}
        
        # Current Session Properties
        self.session_answer = ""
        self.session_auto_mark = False
        self.session_regular_cd = 120 
        self.session_winner_cd = 30

    async def _open_guessing_channel(self, guild, channel, answer: str, auto_mark: bool, reg_cd: int, win_cd: int):
        """Helper method to handle the actual unlocking logic and set session properties."""
        self.is_active = True
        self.user_guesses.clear()
        self.last_guess_time.clear()
        
        # Apply the chosen properties for this session
        self.session_answer = answer
        self.session_auto_mark = auto_mark
        self.session_regular_cd = reg_cd
        self.session_winner_cd = win_cd

        # Unlock the channel for the default role
        await channel.set_permissions(guild.default_role, send_messages=True)
        
        # Get custom open message
        msg_text = await self.config.guild(guild).msg_open()
        
        embed = discord.Embed(
            description=msg_text,
            color=discord.Color.green()
        )
        footer_text = f"Cooldowns | Regular: {reg_cd}m | Winners: {win_cd}m\nAuto-Marking: {'✅ Enabled' if auto_mark else '❌ Disabled'}"
        embed.set_footer(text=footer_text)
        
        await channel.send(embed=embed)

    async def _close_guessing_channel(self, guild, channel, answer: str, winner: discord.Member = None):
        """Helper method to lock the channel and announce the answer."""
        self.is_active = False

        # Lock the channel
        await channel.set_permissions(guild.default_role, send_messages=False)

        # Get custom close message
        config_data = await self.config.guild(guild).all()
        msg_template = config_data["msg_close"]
        
        winner_text = winner.mention if winner else "No one (or manually closed)"
        msg_text = msg_template.replace("{answer}", answer).replace("{winner}", winner_text)

        embed = discord.Embed(
            description=msg_text,
            color=discord.Color.red()
        )
        await channel.send(embed=embed)

    # ========================
    # SLASH COMMANDS (ACTIONS)
    # ========================

    @app_commands.command(name="guessopen", description="Unlocks the configured guesses channel and links to the question channel.")
    @app_commands.describe(
        answer="The correct answer to the question (required for auto-marking)",
        auto_mark="Automatically react ✅/❌ and close when the answer is guessed?",
        regular_cooldown="Cooldown for regular users (Defaults to 2 Hours)",
        winner_cooldown="Cooldown for previous winners (Defaults to 30 Mins)"
    )
    @app_commands.choices(
        regular_cooldown=[
            app_commands.Choice(name="30 Minutes", value=30),
            app_commands.Choice(name="1 Hour", value=60),
            app_commands.Choice(name="2 Hours", value=120),
            app_commands.Choice(name="4 Hours", value=240),
            app_commands.Choice(name="12 Hours", value=720)
        ],
        winner_cooldown=[
            app_commands.Choice(name="No Cooldown", value=0),
            app_commands.Choice(name="15 Minutes", value=15),
            app_commands.Choice(name="30 Minutes", value=30),
            app_commands.Choice(name="1 Hour", value=60),
            app_commands.Choice(name="2 Hours", value=120)
        ]
    )
    async def guessopen(self, interaction: discord.Interaction, answer: str, auto_mark: bool = True, regular_cooldown: int = 120, winner_cooldown: int = 30):
        guild = interaction.guild
        config_data = await self.config.guild(guild).all()
        
        channel_id = config_data["guess_channel_id"]
        if not channel_id:
            return await interaction.response.send_message("The guess channel hasn't been configured yet.", ephemeral=True)
        
        channel = guild.get_channel(channel_id)
        if not channel:
            return await interaction.response.send_message("The configured guess channel no longer exists.", ephemeral=True)

        # Role Verification
        user_role_ids = [r.id for r in interaction.user.roles]
        host_role_id = config_data["role_host"]
        probation_role_id = config_data["role_probation"]
        manager_role_id = config_data["role_manager"]

        if host_role_id not in user_role_ids:
            return await interaction.response.send_message("You do not have the required Host role to do this.", ephemeral=True)

        # Probation Check
        if probation_role_id in user_role_ids:
            manager_role = guild.get_role(manager_role_id)
            managers = [m for m in guild.members if manager_role in m.roles] if manager_role else []
            
            if not managers:
                return await interaction.response.send_message("You are on probation, but no Managers could be found to approve this.", ephemeral=True)
            
            manager = managers[0]
            view = ManagerApprovalView(self, interaction, channel, answer, auto_mark, regular_cooldown, winner_cooldown)
            try:
                await manager.send(
                    f"**Approval Required:** {interaction.user.mention} (on probation) wants to open the guesses channel.\n"
                    f"**Answer:** {answer}\n"
                    f"**Auto-Marking:** {'Enabled' if auto_mark else 'Disabled'}\n"
                    f"**Cooldowns:** Regular: {regular_cooldown}m | Winners: {winner_cooldown}m",
                    view=view
                )
                await interaction.response.send_message("You are on probation. An approval request has been sent to a manager.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("Could not DM the manager. Please ask them to enable DMs.", ephemeral=True)
            return

        # Normal Execution
        await self._open_guessing_channel(guild, channel, answer, auto_mark, regular_cooldown, winner_cooldown)
        await interaction.response.send_message("Guessing channel unlocked!", ephemeral=True)

    @app_commands.command(name="guessclose", description="Manually locks the guesses channel.")
    @app_commands.describe(answer="Optional: Override the correct answer if you made a typo when opening.")
    async def guessclose(self, interaction: discord.Interaction, answer: str = None):
        guild = interaction.guild
        config_data = await self.config.guild(guild).all()
        
        # Verify Host
        if config_data["role_host"] not in [r.id for r in interaction.user.roles]:
            return await interaction.response.send_message("You do not have the required Host role to do this.", ephemeral=True)

        channel_id = config_data["guess_channel_id"]
        channel = guild.get_channel(channel_id) if channel_id else None
        
        if not channel:
            return await interaction.response.send_message("Could not find the configured guess channel.", ephemeral=True)

        if not self.is_active:
            return await interaction.response.send_message("The guessing channel is already closed.", ephemeral=True)

        # Fallback to the session answer if not provided
        final_answer = answer if answer else self.session_answer

        await self._close_guessing_channel(guild, channel, final_answer)
        await interaction.response.send_message("Guessing channel locked successfully.", ephemeral=True)


    # ========================
    # PREFIX COMMANDS (CONFIG)
    # ========================
    @commands.group(name="guessset")
    @commands.admin_or_permissions(manage_guild=True)
    async def guessset(self, ctx):
        """Configuration commands for the Guesses cog."""
        pass

    @guessset.command(name="channel")
    async def guessset_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where guessing will take place."""
        await self.config.guild(ctx.guild).guess_channel_id.set(channel.id)
        await ctx.send(f"Guesses channel set to {channel.mention}.")

    @guessset.group(name="role")
    async def guessset_role(self, ctx):
        """Configure the roles used by the guessing game."""
        pass

    @guessset_role.command(name="host")
    async def guessset_role_host(self, ctx, role: discord.Role):
        await self.config.guild(ctx.guild).role_host.set(role.id)
        await ctx.send(f"Host role set to **{role.name}**.")

    @guessset_role.command(name="manager")
    async def guessset_role_manager(self, ctx, role: discord.Role):
        await self.config.guild(ctx.guild).role_manager.set(role.id)
        await ctx.send(f"Manager role set to **{role.name}**.")

    @guessset_role.command(name="probation")
    async def guessset_role_probation(self, ctx, role: discord.Role):
        await self.config.guild(ctx.guild).role_probation.set(role.id)
        await ctx.send(f"Probation role set to **{role.name}**.")

    @guessset_role.command(name="winner")
    async def guessset_role_winner(self, ctx, role: discord.Role):
        await self.config.guild(ctx.guild).role_winner.set(role.id)
        await ctx.send(f"Previous Winner role set to **{role.name}**.")

    @guessset_role.command(name="booster")
    async def guessset_role_booster(self, ctx, role: discord.Role = None):
        """Sets a custom booster role. (Leave blank to use Discord's native Server Booster status)"""
        val = role.id if role else None
        await self.config.guild(ctx.guild).role_booster.set(val)
        status = f"**{role.name}**" if role else "Discord Native Boosting Status"
        await ctx.send(f"Booster verification set to {status}.")

    @guessset.group(name="msg")
    async def guessset_msg(self, ctx):
        """Configure custom messages. Use {user}, {answer}, {time}, or {winner} where applicable."""
        pass

    @guessset_msg.command(name="open")
    async def guessset_msg_open(self, ctx, *, text: str):
        await self.config.guild(ctx.guild).msg_open.set(text)
        await ctx.send("Opening message updated.")
        
    @guessset_msg.command(name="close")
    async def guessset_msg_close(self, ctx, *, text: str):
        await self.config.guild(ctx.guild).msg_close.set(text)
        await ctx.send("Closing message updated. (Hint: Use `{winner}` to show who guessed correctly!)")

    @guessset_msg.command(name="duplicate")
    async def guessset_msg_duplicate(self, ctx, *, text: str):
        await self.config.guild(ctx.guild).msg_duplicate.set(text)
        await ctx.send("Duplicate guess message updated.")

    @guessset_msg.command(name="cooldown")
    async def guessset_msg_cooldown(self, ctx, *, text: str):
        await self.config.guild(ctx.guild).msg_cooldown.set(text)
        await ctx.send("Cooldown message updated.")

    # ========================
    # EVENT LISTENER (LOGIC)
    # ========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not self.is_active:
            return

        config_data = await self.config.guild(message.guild).all()
        
        # Only parse messages in the active guess channel
        if message.channel.id != config_data["guess_channel_id"]:
            return

        # Do not moderate valid prefix commands inside the guess channel
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        author = message.author
        now = datetime.datetime.now(datetime.timezone.utc)
        guess_text = message.content.lower().strip()

        # Initialize user's guess set if missing
        if author.id not in self.user_guesses:
            self.user_guesses[author.id] = set()

        # 1. Check for Duplicate Guesses per user
        if guess_text in self.user_guesses[author.id]:
            await message.delete()
            msg_text = config_data["msg_duplicate"].replace("{user}", author.mention)
            await message.channel.send(msg_text, delete_after=10)
            return

        # 2. Evaluate roles for Cooldowns
        user_role_ids = [r.id for r in author.roles]
        
        is_native_booster = author.premium_since is not None
        custom_booster_id = config_data["role_booster"]
        is_custom_booster = custom_booster_id in user_role_ids if custom_booster_id else False
        is_booster = is_native_booster or is_custom_booster

        is_prev_winner = config_data["role_winner"] in user_role_ids

        # If they aren't a booster, check if they have a cooldown applied
        if not is_booster:
            cd_minutes = self.session_winner_cd if is_prev_winner else self.session_regular_cd
            
            if cd_minutes > 0:
                cooldown_time = datetime.timedelta(minutes=cd_minutes)
                last_guess = self.last_guess_time.get(author.id)

                if last_guess and (now - last_guess) < cooldown_time:
                    remaining = cooldown_time - (now - last_guess)
                    minutes, seconds = divmod(int(remaining.total_seconds()), 60)
                    hours, minutes = divmod(minutes, 60)
                    time_str = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"
                    
                    await message.delete()
                    msg_text = config_data["msg_cooldown"].replace("{user}", author.mention).replace("{time}", time_str)
                    await message.channel.send(msg_text, delete_after=10)
                    return

        # 3. Valid Guess Processing
        self.user_guesses[author.id].add(guess_text)
        self.last_guess_time[author.id] = now
        
        # 4. Auto-Marking Logic
        if self.session_auto_mark:
            # Check Levenshtein distance against the session answer
            target_answer = self.session_answer.lower().strip()
            distance = get_edit_distance(guess_text, target_answer)
            
            if distance <= 1:
                # Correct! (Allows exactly 1 spelling mistake/addition/removal)
                await message.add_reaction("✅")
                await self._close_guessing_channel(message.guild, message.channel, self.session_answer, winner=author)
            else:
                # Incorrect
                await message.add_reaction("❌")
