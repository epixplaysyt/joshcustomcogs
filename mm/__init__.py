from .mm import MMWelcome

async def setup(bot):
    await bot.add_cog(MMWelcome(bot))
