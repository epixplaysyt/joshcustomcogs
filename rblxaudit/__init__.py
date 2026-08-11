from .audit_logger import AuditLogger

async def setup(bot):
    await bot.add_cog(AuditLogger(bot))
