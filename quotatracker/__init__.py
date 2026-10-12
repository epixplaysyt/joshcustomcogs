from .quotatracker import QuotaTracker

async def setup(bot):
    await bot.add_cog(QuotaTracker(bot))
