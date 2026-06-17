import discord
from redbot.core import commands, Config
from discord import app_commands
import datetime

# --- Helper Function for Fuzzy Matching ---
def get_edit_distance(s1: str, s2: str) -> int:
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
        super().__init__(timeout=600)  # View expires after 10 minutes
        self.cog = cog
        self.interaction = interaction
        self.channel = channel
        self.answer = answer
        self.auto_mark = auto_mark
        self.reg_cd = reg_cd
        self.win_cd = win_cd

    async def _disable_all_items(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Allow", style=discord.ButtonStyle.success)
    async def allow(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all_items(interaction)
        await interaction.response.send_message("You have approved the guessing session.")
        await self.cog._open_guessing_channel(self.interaction.guild, self.channel, self.answer, self.auto_mark, self.reg_cd, self.win_cd)
        self.cog.pending_requests.discard(self.interaction.guild.id)
        self.stop()

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._disable_all_items(interaction)
        await interaction.response.send_message("You have denied the guessing session.")
        self.cog.pending_requests.discard(self.interaction.guild.id)
        self.stop()

class Guesses(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9283746150, force_registration=True)
        default_guild = {
            "guess_channel_id": None, "role_host": None, "role_manager": None,
            "role_probation": None, "role_winner": None, "role_booster": None,
            "msg_open": "🎯 **New session!** Check <#1331301801927905423> and guess here!",
            "msg_close": "🛑 **Closed!** Answer: **{answer}**. Winner: {winner}",
            "msg_duplicate": "{user}, already guessed that!",
            "msg_cooldown": "{user}, wait {time}."
        }
        self.config.register_guild(**default_guild)
        self.is_active = False
        self.user_guesses = {}
        self.last_guess_time = {}
        self.pending_requests = set() # Tracks active probation requests
        self.session_answer = ""
        self.session_auto_mark = False
        self.session_regular_cd = 120
        self.session_winner_cd = 30

    async def _open_guessing_channel(self, guild, channel, answer, auto_mark, reg_cd, win_cd):
        self.is_active = True
        self.user_guesses.clear()
        self.last_guess_time.clear()
        self.session_answer = answer
        self.session_auto_mark = auto_mark
        self.session_regular_cd = reg_cd
        self.session_winner_cd = win_cd
        await channel.set_permissions(guild.default_role, send_messages=True)
        msg_text = await self.config.guild(guild).msg_open()
        embed = discord.Embed(description=msg_text, color=discord.Color.green())
        embed.set_footer(text=f"Auto-Mark: {'✅' if auto_mark else '❌'}")
        await channel.send(embed=embed)

    async def _close_guessing_channel(self, guild, channel, answer, winner=None):
        self.is_active = False
        await channel.set_permissions(guild.default_role, send_messages=False)
        msg_template = await self.config.guild(guild).msg_close()
        winner_text = winner.mention if winner else "No one"
        embed = discord.Embed(description=msg_template.replace("{answer}", answer).replace("{winner}", winner_text), color=discord.Color.red())
        await channel.send(embed=embed)

    @app_commands.command(name="guessopen", description="Opens the guessing channel.")
    async def guessopen(self, interaction: discord.Interaction, answer: str, auto_mark: bool = True, regular_cooldown: int = 120, winner_cooldown: int = 30):
        guild = interaction.guild
        config = await self.config.guild(guild).all()
        channel = guild.get_channel(config["guess_channel_id"])
        
        if config["role_host"] not in [r.id for r in interaction.user.roles]:
            return await interaction.response.send_message("Unauthorized.", ephemeral=True)

        # Probation Handling with Concurrency Lock
        if config["role_probation"] in [r.id for r in interaction.user.roles]:
            if guild.id in self.pending_requests:
                return await interaction.response.send_message("Request already pending.", ephemeral=True)
            
            manager_role = guild.get_role(config["role_manager"])
            if not manager_role or not manager_role.members:
                return await interaction.response.send_message("No managers found to approve.", ephemeral=True)
            
            self.pending_requests.add(guild.id)
            view = ManagerApprovalView(self, interaction, channel, answer, auto_mark, regular_cooldown, winner_cooldown)
            for m in manager_role.members:
                try: await m.send(f"**Approval Required:** {interaction.user.mention} needs approval.", view=view)
                except: continue
            return await interaction.response.send_message("Request sent to all managers.", ephemeral=True)

        await self._open_guessing_channel(guild, channel, answer, auto_mark, regular_cooldown, winner_cooldown)
        await interaction.response.send_message("Channel opened.", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.is_active or message.channel.id != (await self.config.guild(message.guild).guess_channel_id()):
            return
        
        author = message.author
        guess_text = message.content.lower().strip()
        
        if author.id not in self.user_guesses: self.user_guesses[author.id] = set()
        if guess_text in self.user_guesses[author.id]:
            await message.delete()
            return await message.channel.send("Already guessed!", delete_after=5)

        self.user_guesses[author.id].add(guess_text)
        if self.session_auto_mark and get_edit_distance(guess_text, self.session_answer.lower()) <= 1:
            await message.add_reaction("✅")
            await self._close_guessing_channel(message.guild, message.channel, self.session_answer, winner=author)
        else:
            await message.add_reaction("❌")
