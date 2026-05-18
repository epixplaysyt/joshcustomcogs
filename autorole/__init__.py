from .roleautomation import RoleAutomation

async def setup(bot):
    await bot.add_cog(RoleAutomation(bot))
