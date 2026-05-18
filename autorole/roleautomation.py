from typing import Optional
import discord
from redbot.core import commands, Config

class RoleAutomation(commands.Cog):
    """Automate role replacements and condition audits."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8675309123, force_registration=True)
        
        default_guild = {
            "trigger_role": None,
            "replacement_role": None,
            "audit_trigger_role": None,
            "audit_required_role": None
        }
        self.config.register_guild(**default_guild)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Listens for role updates and replaces the target role automatically."""
        if before.roles == after.roles:
            return

        guild = after.guild
        trigger_id = await self.config.guild(guild).trigger_role()
        replacement_id = await self.config.guild(guild).replacement_role()

        if not trigger_id or not replacement_id:
            return

        added_roles = [role for role in after.roles if role not in before.roles]
        
        for role in added_roles:
            if role.id == trigger_id:
                replacement_role = guild.get_role(replacement_id)
                if not replacement_role:
                    return

                try:
                    await after.remove_roles(role, reason="Role Automation: Swap trigger removed.")
                    await after.add_roles(replacement_role, reason="Role Automation: Swap replacement added.")
                except discord.Forbidden:
                    pass  
                except discord.HTTPException:
                    pass

    @commands.hybrid_command(name="updateroles")
    @commands.guild_only()
    async def update_roles(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Manually trigger the role replacement setup for yourself or another player."""
        guild = ctx.guild
        author = ctx.author
        
        # Default to the command invoker if no member is provided
        if member is None:
            member = author
            
        # Permission check: If trying to update someone else, user must be an admin
        if member != author:
            is_admin = author.guild_permissions.administrator or await self.bot.is_admin(author)
            if not is_admin:
                await ctx.send("❌ You can only run this command on yourself. Administrators can run it on other players.", ephemeral=True)
                return

        trigger_id = await self.config.guild(guild).trigger_role()
        replacement_id = await self.config.guild(guild).replacement_role()

        if not trigger_id or not replacement_id:
            await ctx.send("❌ Role automation is not fully configured on this server yet.", ephemeral=True)
            return

        trigger_role = guild.get_role(trigger_id)
        replacement_role = guild.get_role(replacement_id)

        if not trigger_role or not replacement_role:
            await ctx.send("❌ Configured automation roles could not be found in the server.", ephemeral=True)
            return

        # Condition Check: If they do not have Role X, do nothing and do not give Role Y
        if trigger_role not in member.roles:
            if member == author:
                await ctx.send(f"ℹ️ You do not currently have the required trigger role (**{trigger_role.name}**). No changes were made.", ephemeral=True)
            else:
                await ctx.send(f"ℹ️ **{member.display_name}** does not have the trigger role (**{trigger_role.name}**). No changes were made.", ephemeral=True)
            return

        # Perform the manual swap
        try:
            await member.remove_roles(trigger_role, reason=f"Manual Role Swap requested by {author.display_name}")
            await member.add_roles(replacement_role, reason=f"Manual Role Swap requested by {author.display_name}")
            
            if member == author:
                await ctx.send(f"✅ Successfully updated your roles! Removed **{trigger_role.name}** and added **{replacement_role.name}**.", ephemeral=True)
            else:
                await ctx.send(f"✅ Successfully updated roles for **{member.display_name}**! Removed **{trigger_role.name}** and added **{replacement_role.name}**.", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ I do not have permission to modify these roles. Please check my role hierarchy position.", ephemeral=True)
        except discord.HTTPException:
            await ctx.send("❌ An error occurred while communicating with Discord to update roles.", ephemeral=True)

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_roles=True)
    async def roleauto(self, ctx: commands.Context):
        """Manage role automation configurations."""
        pass

    @roleauto.command(name="trigger")
    async def set_trigger(self, ctx: commands.Context, role: discord.Role):
        """Set the role that triggers the swap-out behavior."""
        await self.config.guild(ctx.guild).trigger_role.set(role.id)
        await ctx.send(f"✅ Trigger role set to: **{role.name}** ({role.id})")

    @roleauto.command(name="replacement")
    async def set_replacement(self, ctx: commands.Context, role: discord.Role):
        """Set the role that replaces the trigger role."""
        await self.config.guild(ctx.guild).replacement_role.set(role.id)
        await ctx.send(f"✅ Replacement role set to: **{role.name}** ({role.id})")

    @roleauto.command(name="audittrigger")
    async def set_audit_trigger(self, ctx: commands.Context, role: discord.Role):
        """Set the role checked during an audit (Role A)."""
        await self.config.guild(ctx.guild).audit_trigger_role.set(role.id)
        await ctx.send(f"✅ Audit condition role set to: **{role.name}** ({role.id})")

    @roleauto.command(name="auditrequired")
    async def set_audit_required(self, ctx: commands.Context, role: discord.Role):
        """Set the role required to keep the audit trigger role (Role B)."""
        await self.config.guild(ctx.guild).audit_required_role.set(role.id)
        await ctx.send(f"✅ Audit required companion role set to: **{role.name}** ({role.id})")

    @roleauto.command(name="runaudit")
    async def run_audit(self, ctx: commands.Context):
        """Audit all members. Removes Role A if they lack Role B."""
        guild = ctx.guild
        trigger_id = await self.config.guild(guild).audit_trigger_role()
        required_id = await self.config.guild(guild).audit_required_role()

        if not trigger_id or not required_id:
            return await ctx.send("❌ Error: Please configure both audit roles first using `[p]roleauto audittrigger` and `[p]roleauto auditrequired`.")

        trigger_role = guild.get_role(trigger_id)
        required_role = guild.get_role(required_id)

        if not trigger_role or not required_role:
            return await ctx.send("❌ Error: One or both configured audit roles no longer exist in this server.")

        status_msg = await ctx.send("🔄 Scanning server members and adjusting roles. This may take a moment...")
        
        removed_count = 0
        failed_count = 0

        for member in guild.members:
            if trigger_role in member.roles and required_role not in member.roles:
                try:
                    await member.remove_roles(trigger_role, reason="Role Automation Audit: Missing required role relationship.")
                    removed_count += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed_count += 1

        await status_msg.edit(
            content=f"📊 **Audit Complete!**\n"
                    f"- Members updated (Role removed): `{removed_count}`\n"
                    f"- Failed updates (Hierarchy/Permissions issue): `{failed_count}`"
        )

async def setup(bot):
    await bot.add_cog(RoleAutomation(bot))
