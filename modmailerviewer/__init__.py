from .viewer import ModmailerViewer


async def setup(bot):
    await bot.add_cog(ModmailerViewer(bot))
