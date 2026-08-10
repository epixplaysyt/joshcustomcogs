from .compsender import JsonEmbeds

async def setup(bot):
    await bot.add_cog(JsonEmbeds(bot))
