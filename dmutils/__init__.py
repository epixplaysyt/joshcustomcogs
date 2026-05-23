from .dmutils import DMUtils

async def setup(bot):
    await bot.add_cog(DMUtils(bot))
