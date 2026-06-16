import discord
from redbot.core import commands, Config

class LastToLeave(commands.Cog):
    """Host 'Last to Leave VC' events with host protection and logging."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9483726153, force_registration=True)
        self.config.register_guild(
            vc_id=None,
            participant_role_id=None,
            host_role_id=None,
            announce_channel_id=None,
            is_active=False
        )

    @commands.group(name="ltl")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_events=True)
    async def ltl(self, ctx):
        """Commands for managing the Last to Leave VC event."""
        pass

    @ltl.command(name="setup")
    async def ltl_setup(self, ctx, vc: discord.VoiceChannel, participant_role: discord.Role, host_role: discord.Role, announce_channel: discord.TextChannel = None):
        """Setup the VC, Participant Role, Host Role, and Logging channel."""
        announce_chan = announce_channel or ctx.channel

        await self.config.guild(ctx.guild).vc_id.set(vc.id)
        await self.config.guild(ctx.guild).participant_role_id.set(participant_role.id)
        await self.config.guild(ctx.guild).host_role_id.set(host_role.id)
        await self.config.guild(ctx.guild).announce_channel_id.set(announce_chan.id)
        
        await ctx.send(f"✅ Setup complete. Host: {host_role.name}, Participants: {participant_role.name}.")

    @ltl.command(name="start")
    async def ltl_start(self, ctx):
        """Start the event."""
        data = await self.config.guild(ctx.guild).all()
        vc = ctx.guild.get_channel(data["vc_id"])
        role = ctx.guild.get_role(data["participant_role_id"])
        host_role = ctx.guild.get_role(data["host_role_id"])

        if not all([vc, role, host_role]):
            return await ctx.send("❌ Configuration error. Check setup.")

        # Assign role to all non-host members in VC
        for member in vc.members:
            if host_role not in member.roles:
                await member.add_roles(role)

        await self.config.guild(ctx.guild).is_active.set(True)
        await ctx.send("🚨 Event started!")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel: return
        
        guild = member.guild
        data = await self.config.guild(guild).all()
        if not data["is_active"]: return
        
        host_role = guild.get_role(data["host_role_id"])
        # Ignore hosts
        if host_role in member.roles: return

        if before.channel and before.channel.id == data["vc_id"]:
            role = guild.get_role(data["participant_role_id"])
            await member.remove_roles(role)
            
            # Log Elimination
            announce_chan = guild.get_channel(data["announce_channel_id"])
            embed = discord.Embed(title="❌ Player Eliminated", description=f"{member.name} has left!", color=discord.Color.red())
            await announce_chan.send(embed=embed)

            # Check Winner
            participants = [m for m in before.channel.members if host_role not in m.roles]
            if len(participants) == 1:
                winner = participants[0]
                await self.config.guild(guild).is_active.set(False)
                win_embed = discord.Embed(title="🏆 Winner!", description=f"{winner.mention} is the last to leave!", color=discord.Color.gold())
                await announce_chan.send(embed=win_embed)

async def setup(bot):
    await bot.add_cog(LastToLeave(bot))
