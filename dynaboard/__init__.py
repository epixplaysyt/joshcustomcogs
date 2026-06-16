from .dynaboard import InfoBoard

async def setup(bot):
    await bot.add_cog(InfoBoard(bot))

