from .ltl import LastToLeave

async def setup(bot):
    await bot.add_cog(LastToLeave(bot))
