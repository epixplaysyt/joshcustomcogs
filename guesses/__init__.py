from .guesses import Guesses

async def setup(bot):
    await bot.add_cog(Guesses(bot))
  
