from .eventboard import EventBoard

async def setup(bot):
    await bot.add_cog(EventBoard(bot))
