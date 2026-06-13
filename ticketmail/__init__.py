from .modmail import Modmail

async def setup(bot):
    # Initialize the cog instance
    cog = Modmail(bot)
    
    # Load the cog into Red's core ecosystem
    await bot.add_cog(cog)
    
    # Register the application (slash) command group to the bot's global command tree
    bot.tree.add_command(cog.ticket_group)

