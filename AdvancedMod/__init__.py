from .advmod import AdvancedMod

async def setup(bot):
    await bot.add_cog(AdvancedMod(bot))
