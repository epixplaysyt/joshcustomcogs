from .ticketmail import Modmail

async def setup(bot):
    cog = Modmail(bot)
    await bot.add_cog(cog)
    bot.tree.add_command(cog.ticket_group)
