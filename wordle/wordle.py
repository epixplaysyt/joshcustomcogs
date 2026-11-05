import datetime
import re
import aiohttp
import discord
from discord.ext import tasks
from redbot.core import commands, Config

class SetWordOverrideView(discord.ui.View):
    def __init__(self, cog, ctx, word, validate):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.word = word
        self.validate = validate

    @discord.ui.button(label="Set Anyway", style=discord.ButtonStyle.danger)
    async def confirm_override(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ You cannot use this button.", ephemeral=True)
            return
        await self.cog.apply_set_word(self.ctx, self.word, self.validate, interaction=interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ You cannot use this button.", ephemeral=True)
            return
        await interaction.response.edit_message(content="❌ Action cancelled.", view=None)
        self.stop()

class WordleGuessModal(discord.ui.Modal, title="Submit Your Wordle Guess"):
    guess_input = discord.ui.TextInput(
        label="5-Letter Guess",
        style=discord.TextStyle.short,
        placeholder="e.g. TRAIN",
        min_length=5,
        max_length=5,
        required=True
    )

    def __init__(self, cog, user_id):
        super().__init__()
        self.cog = cog
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        guess = self.guess_input.value.strip().upper()
        if not re.match(r"^[A-Z]{5}$", guess):
            await interaction.response.send_message(
                "❌ Guess must contain only 5 letters (A-Z).", ephemeral=True
            )
            return
        
        await interaction.response.defer()
        await self.cog.process_guess(interaction, self.user_id, guess)

class WordleDMView(discord.ui.View):
    def __init__(self, cog, user_id, completed=False):
        super().__init__(timeout=None)
        self.cog = cog
        self.user_id = user_id

        guess_button = discord.ui.Button(
            label="Make a Guess" if not completed else "Completed for Today!",
            style=discord.ButtonStyle.primary if not completed else discord.ButtonStyle.secondary,
            emoji="✍️" if not completed else "✅",
            disabled=completed,
            custom_id=f"wordle_guess_btn_{user_id}"
        )
        guess_button.callback = self.on_guess_click
        self.add_item(guess_button)

    async def on_guess_click(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your game session.", ephemeral=True)
            return

        modal = WordleGuessModal(self.cog, self.user_id)
        await interaction.response.send_modal(modal)

class TransportWordle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=84920491823, force_registration=True)
        
        default_guild = {
            "results_channel_id": None,
            "secret_word": "METRO",
            "word_date": "",
            "validate_word": True
        }
        default_user = {
            "date": "",
            "guesses": [],
            "results": [],
            "completed": False,
            "won": False
        }
        
        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)
        self.daily_check.start()

    def cog_unload(self):
        self.daily_check.cancel()

    def get_today_string(self):
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    async def check_word_exists(self, word: str) -> bool:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}") as resp:
                return resp.status == 200

    @tasks.loop(minutes=30)
    async def daily_check(self):
        today = self.get_today_string()
        all_users = await self.config.all_users()
        
        for user_id_str, user_data in all_users.items():
            user_date = user_data.get("date", "")
            completed = user_data.get("completed", False)
            guesses = user_data.get("guesses", [])
            
            if user_date and user_date != today and not completed and len(guesses) > 0:
                user_id = int(user_id_str)
                user = self.bot.get_user(user_id)
                if user:
                    for guild in self.bot.guilds:
                        if guild.get_member(user_id):
                            results_channel_id = await self.config.guild(guild).results_channel_id()
                            if results_channel_id:
                                results_channel = guild.get_channel(results_channel_id)
                                if results_channel:
                                    results_text = "\n".join(user_data["results"])
                                    public_embed = discord.Embed(
                                        title=f"🚆 Transport Wordle Result (Unfinished) - {user.display_name}",
                                        description=f"**Score:** X/6\n\n{results_text}",
                                        color=discord.Color.dark_grey()
                                    )
                                    public_embed.set_footer(text=f"Date: {user_date}")
                                    await results_channel.send(embed=public_embed)
                            break
                
                await self.config.user_from_id(user_id).set({
                    "date": today,
                    "guesses": [],
                    "results": [],
                    "completed": False,
                    "won": False
                })

    @daily_check.before_loop
    async def before_daily_check(self):
        await self.bot.wait_until_ready()

    def evaluate_guess(self, guess: str, secret: str) -> str:
        guess_chars = list(guess)
        secret_chars = list(secret)
        result = [""] * 5

        for i in range(5):
            if guess_chars[i] == secret_chars[i]:
                result[i] = "🟩"
                secret_chars[i] = None
                guess_chars[i] = None

        for i in range(5):
            if guess_chars[i] is None:
                continue
            if guess_chars[i] in secret_chars:
                result[i] = "🟨"
                secret_chars[secret_chars.index(guess_chars[i])] = None
            else:
                result[i] = "⬛"

        return "".join(result)

    def build_embed(self, user_data):
        description = ""
        guesses = user_data.get("guesses", [])
        results = user_data.get("results", [])
        completed = user_data.get("completed", False)
        won = user_data.get("won", False)

        for i in range(6):
            if i < len(guesses):
                description += f"{results[i]}  `{guesses[i]}`\n"
            elif i == len(guesses) and not completed:
                description += "⬜⬜⬜⬜⬜  *(Current Turn)*\n"
            else:
                description += "⬛⬛⬛⬛⬛\n"

        color = discord.Color.blue()
        if completed:
            color = discord.Color.green() if won else discord.Color.red()

        embed = discord.Embed(
            title="🚆 Transport Wordle",
            description=description,
            color=color
        )
        embed.set_footer(text=f"Attempt {len(guesses)}/6 • Resets Daily at Midnight UTC")
        return embed

    async def apply_set_word(self, ctx, word, validate, interaction=None):
        today = self.get_today_string()
        await self.config.guild(ctx.guild).secret_word.set(word)
        await self.config.guild(ctx.guild).word_date.set(today)
        await self.config.guild(ctx.guild).validate_word.set(validate)

        msg = f"✅ Today's transport Wordle word has been set to **{word}** (Dictionary Validation: {'Enabled' if validate else 'Disabled'})."
        if interaction:
            await interaction.response.edit_message(content=msg, view=None)
        else:
            await ctx.send(msg, ephemeral=True)

    @commands.hybrid_command(name="setwordle")
    @commands.admin_or_permissions(manage_guild=True)
    async def setwordle(self, ctx: commands.Context, word: str, validate: bool = True):
        word = word.strip().upper()
        if len(word) != 5 or not word.isalpha():
            if ctx.interaction:
                await ctx.interaction.response.send_message("❌ Word must be exactly 5 alphabetic letters (e.g. `RAILS`, `DEPOT`).", ephemeral=True)
            else:
                await ctx.send("❌ Word must be exactly 5 alphabetic letters (e.g. `RAILS`, `DEPOT`).", ephemeral=True)
            return

        today = self.get_today_string()
        current_date = await self.config.guild(ctx.guild).word_date()
        current_word = await self.config.guild(ctx.guild).secret_word()

        if current_date == today and current_word:
            view = SetWordOverrideView(self, ctx, word, validate)
            content = f"⚠️ A word (**{current_word}**) is already active for today! Do you want to overwrite it?"
            if ctx.interaction:
                await ctx.interaction.response.send_message(content, view=view, ephemeral=True)
            else:
                await ctx.send(content, view=view, ephemeral=True)
            return

        if validate:
            exists = await self.check_word_exists(word)
            if not exists:
                msg = f"❌ **{word}** was not found in the dictionary API. Set validation to false if this is an intentional custom word."
                if ctx.interaction:
                    await ctx.interaction.response.send_message(msg, ephemeral=True)
                else:
                    await ctx.send(msg, ephemeral=True)
                return

        await self.apply_set_word(ctx, word, validate)

    @commands.hybrid_command(name="setwordlechannel")
    @commands.admin_or_permissions(manage_guild=True)
    async def setwordlechannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).results_channel_id.set(channel.id)
        await ctx.send(f"✅ Wordle results channel set to {channel.mention}.", ephemeral=True)

    @commands.hybrid_command(name="wordle")
    async def wordle(self, ctx: commands.Context):
        today = self.get_today_string()
        user_config = self.config.user(ctx.author)
        user_data = await user_config.all()

        if user_data["date"] != today:
            user_data = {
                "date": today,
                "guesses": [],
                "results": [],
                "completed": False,
                "won": False
            }
            await user_config.set(user_data)

        embed = self.build_embed(user_data)
        view = WordleDMView(self, ctx.author.id, completed=user_data["completed"])

        try:
            dm_channel = await ctx.author.create_dm()
            await dm_channel.send(
                content="Here is your active Wordle game! Click the button below to submit a guess.",
                embeds=[embed],
                view=view
            )
            if ctx.interaction:
                await ctx.interaction.response.send_message("📬 I have sent your Wordle game to your DMs!", ephemeral=True)
            else:
                await ctx.send("📬 I have sent your Wordle game to your DMs!")
        except discord.Forbidden:
            error_msg = "❌ Could not send you a DM. Please check your privacy settings to allow DMs from server members."
            if ctx.interaction:
                await ctx.interaction.response.send_message(error_msg, ephemeral=True)
            else:
                await ctx.send(error_msg)

    async def process_guess(self, interaction: discord.Interaction, user_id: int, guess: str):
        today = self.get_today_string()
        user = self.bot.get_user(user_id)
        if not user:
            return

        user_config = self.config.user(user)
        user_data = await user_config.all()

        if user_data["completed"]:
            await interaction.followup.send("You have already finished today's Wordle!", ephemeral=True)
            return

        guild_id = interaction.guild_id
        secret_word = "METRO"
        validate_word = True
        if guild_id:
            guild = self.bot.get_guild(guild_id)
            if guild:
                secret_word = await self.config.guild(guild).secret_word()
                validate_word = await self.config.guild(guild).validate_word()
        else:
            for guild in self.bot.guilds:
                if guild.get_member(user_id):
                    secret_word = await self.config.guild(guild).secret_word()
                    validate_word = await self.config.guild(guild).validate_word()
                    guild_id = guild.id
                    break

        if validate_word:
            exists = await self.check_word_exists(guess)
            if not exists:
                await interaction.followup.send(f"❌ **{guess}** is not a recognized word in the dictionary.", ephemeral=True)
                return

        feedback = self.evaluate_guess(guess, secret_word)
        user_data["guesses"].append(guess)
        user_data["results"].append(feedback)

        if guess == secret_word:
            user_data["completed"] = True
            user_data["won"] = True
        elif len(user_data["guesses"]) >= 6:
            user_data["completed"] = True
            user_data["won"] = False

        await user_config.set(user_data)

        embed = self.build_embed(user_data)
        view = WordleDMView(self, user_id, completed=user_data["completed"])

        await interaction.message.edit(embeds=[embed], view=view)
        await interaction.followup.send(f"Guess registered: **{guess}**", ephemeral=True)

        if user_data["completed"] and guild_id:
            guild = self.bot.get_guild(guild_id)
            if guild:
                results_channel_id = await self.config.guild(guild).results_channel_id()
                if results_channel_id:
                    results_channel = guild.get_channel(results_channel_id)
                    if results_channel:
                        score_str = f"{len(user_data['guesses'])}/6" if user_data["won"] else "X/6"
                        results_text = "\n".join(user_data["results"])
                        
                        public_embed = discord.Embed(
                            title=f"🚆 Transport Wordle Result - {user.display_name}",
                            description=f"**Score:** {score_str}\n\n{results_text}",
                            color=discord.Color.green() if user_data["won"] else discord.Color.red()
                        )
                        public_embed.set_footer(text=f"Date: {today}")
                        await results_channel.send(embed=public_embed)
