from .modmail import Modmail

async def setup(bot):
    cog = Modmail(bot)
    await bot.add_cog(cog)
    try:
        bot.tree.remove_command(cog.ticket_group.name)
    except Exception:
        pass
    bot.tree.add_command(cog.ticket_group)
