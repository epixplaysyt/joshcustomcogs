from .wordle import TransportWordle

async def setup(bot):
    await bot.add_cog(TransportWordle(bot))
