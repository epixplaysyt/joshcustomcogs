import discord
from redbot.core import commands, checks

class TextPurge(commands.Cog):
    """Purges messages while preserving any message containing attachments."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    @checks.mod_or_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purgetext(self, ctx: commands.Context, limit: int = 100):
        """Deletes up to [limit] messages in the current channel, skipping any with attachments.
        
        Usage: [p]purgetext <number_of_messages>
        """
        if limit <= 0:
            return await ctx.send("Please specify a number greater than 0.")
        
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        def is_without_attachment(message: discord.Message) -> bool:
            return len(message.attachments) == 0

        deleted = await ctx.channel.purge(limit=limit, check=is_without_attachment)

        await ctx.send(
            f"Cleared {len(deleted)} text-only message(s). Preserved all messages with attachments.",
            delete_after=5
        )

async def setup(bot):
    await bot.add_cog(TextPurge(bot))
