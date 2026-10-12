import datetime
import discord
from redbot.core import Config, commands, checks

class HistoryPaginator(discord.ui.View):
    def __init__(self, target_user: discord.User, history_data: list, current_month_data: dict = None):
        super().__init__(timeout=60)
        self.target_user = target_user
        self.pages = list(history_data)
        if current_month_data:
            self.pages.append(current_month_data)

        self.current_page = len(self.pages) - 1 if self.pages else 0

        self._update_buttons()

    def _update_buttons(self):
        self.btn_first.disabled = self.current_page <= 0
        self.btn_prev.disabled = self.current_page <= 0
        self.btn_next.disabled = self.current_page >= len(self.pages) - 1
        self.btn_last.disabled = self.current_page >= len(self.pages) - 1

    def make_embed(self) -> discord.Embed:
        if not self.pages:
            return discord.Embed(
                title=f"Quota History — {self.target_user.display_name}",
                description="No tracking history found for this user.",
                color=discord.Color.red()
            )

        entry = self.pages[self.current_page]
        is_current = entry.get("is_current", False)
        status_icon = "✅ Met" if entry.get("met") else "❌ Incomplete"

        embed = discord.Embed(
            title=f"Quota Activity — {self.target_user.display_name}",
            color=discord.Color.green() if entry.get("met") else discord.Color.blue()
        )
        embed.set_thumbnail(url=self.target_user.display_avatar.url)
        embed.add_field(name="Period", value=f"{entry.get('month', 'Unknown')} {'(Current)' if is_current else ''}", inline=False)
        embed.add_field(name="Department", value=str(entry.get("department", "Unassigned")), inline=True)
        embed.add_field(name="Messages Sent", value=str(entry.get("count", 0)), inline=True)
        embed.add_field(name="Monthly Quota", value=str(entry.get("quota", 0)) if entry.get("quota", 0) > 0 else "None", inline=True)
        embed.add_field(name="Status", value=status_icon, inline=True)
        embed.set_footer(text=f"Page {self.current_page + 1} of {len(self.pages)}")
        return embed

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def btn_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.primary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def btn_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.pages) - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

class QuotaTracker(commands.Cog):
    """Track monthly staff message quotas by department with interactive history pagination."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)

        default_global = {
            "main_guild_id": None
        }
        default_guild = {
            "departments": {}
        }
        default_member = {
            "department": None,
            "message_count": 0,
            "month_year": "",
            "quota_notified": False,
            "history": []
        }

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        self.config.register_member(**default_member)

    def _get_current_month_str(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")

    async def _send_embed(self, ctx: commands.Context, title: str, description: str, color=discord.Color.blue()):
        embed = discord.Embed(title=title, description=description, color=color)
        await ctx.send(embed=embed)

    async def _check_and_reset_monthly_data(self, member: discord.Member, member_config):
        current_month = self._get_current_month_str()
        saved_month = await member_config.month_year()

        if not saved_month:
            await member_config.month_year.set(current_month)
            return

        if saved_month != current_month:
            dept_name = await member_config.department()
            msg_count = await member_config.message_count()

            guild_depts = await self.config.guild(member.guild).departments()
            dept_info = guild_depts.get(dept_name, {}) if dept_name else {}
            quota = dept_info.get("quota", 0)
            met = quota > 0 and msg_count >= quota

            history_entry = {
                "month": saved_month,
                "department": dept_name or "Unassigned",
                "count": msg_count,
                "quota": quota,
                "met": met
            }

            async with member_config.history() as history:
                history.append(history_entry)

            await member_config.month_year.set(current_month)
            await member_config.message_count.set(0)
            await member_config.quota_notified.set(False)

    async def _notify_managers(self, guild: discord.Guild, role_id: int, staff_member: discord.Member, department_name: str, current_count: int, quota: int):
        manager_role = guild.get_role(role_id)
        if not manager_role:
            return

        embed = discord.Embed(
            title="🎉 Staff Quota Met!",
            description=f"**{staff_member.display_name}** ({staff_member.mention}) has reached their monthly quota for the **{department_name}** department.",
            color=discord.Color.green()
        )
        embed.add_field(name="Progress", value=f"{current_count} / {quota} messages")
        embed.set_footer(text=f"Server: {guild.name}")

        for manager in manager_role.members:
            if manager.bot:
                continue
            try:
                await manager.send(embed=embed)
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        main_guild_id = await self.config.main_guild_id()
        if not main_guild_id or message.guild.id != main_guild_id:
            return

        member_config = self.config.member(message.author)
        department_name = await member_config.department()
        if not department_name:
            return

        guild_depts = await self.config.guild(message.guild).departments()
        if department_name not in guild_depts:
            return

        await self._check_and_reset_monthly_data(message.author, member_config)

        current_count = await member_config.message_count() + 1
        await member_config.message_count.set(current_count)

        dept_info = guild_depts[department_name]
        quota = dept_info.get("quota", 0)
        manager_role_id = dept_info.get("manager_role_id")
        already_notified = await member_config.quota_notified()

        if quota > 0 and current_count >= quota and not already_notified:
            await member_config.quota_notified.set(True)
            if manager_role_id:
                await self._notify_managers(
                    guild=message.guild,
                    role_id=manager_role_id,
                    staff_member=message.author,
                    department_name=department_name,
                    current_count=current_count,
                    quota=quota
                )

    @commands.command(name="myquota")
    async def myquota(self, ctx: commands.Context):
        """Check your quota status and history with arrow button navigation."""
        main_guild_id = await self.config.main_guild_id()
        if not main_guild_id:
            return await self._send_embed(ctx, "Configuration Error", "The main server for quota tracking has not been set yet.", discord.Color.red())

        main_guild = self.bot.get_guild(main_guild_id)
        if not main_guild:
            return await self._send_embed(ctx, "Error", "Could not connect to the main tracking server.", discord.Color.red())

        member = main_guild.get_member(ctx.author.id)
        if not member:
            return await self._send_embed(ctx, "Access Denied", "You are not registered in the main staff server.", discord.Color.red())

        member_config = self.config.member(member)
        await self._check_and_reset_monthly_data(member, member_config)

        dept_name = await member_config.department()
        guild_depts = await self.config.guild(main_guild).departments()
        quota = guild_depts.get(dept_name, {}).get("quota", 0) if dept_name else 0
        msg_count = await member_config.message_count()

        current_month_data = {
            "month": self._get_current_month_str(),
            "department": dept_name or "Unassigned",
            "count": msg_count,
            "quota": quota,
            "met": quota > 0 and msg_count >= quota,
            "is_current": True
        }

        history = await member_config.history()
        view = HistoryPaginator(target_user=ctx.author, history_data=history, current_month_data=current_month_data)
        await ctx.send(embed=view.make_embed(), view=view)

    @commands.command(name="checkquota")
    async def checkquota(self, ctx: commands.Context, member: discord.Member):
        """Check a staff member's quota and scroll through their history."""
        main_guild_id = await self.config.main_guild_id()
        if not main_guild_id:
            return await self._send_embed(ctx, "Configuration Error", "The main server for quota tracking has not been set yet.", discord.Color.red())

        main_guild = self.bot.get_guild(main_guild_id)
        if not main_guild:
            return await self._send_embed(ctx, "Error", "Could not connect to the main tracking server.", discord.Color.red())

        target_member = main_guild.get_member(member.id)
        if not target_member:
            return await self._send_embed(ctx, "Error", "User was not found in the main server.", discord.Color.red())

        member_config = self.config.member(target_member)
        await self._check_and_reset_monthly_data(target_member, member_config)

        dept_name = await member_config.department()
        guild_depts = await self.config.guild(main_guild).departments()
        quota = guild_depts.get(dept_name, {}).get("quota", 0) if dept_name else 0
        msg_count = await member_config.message_count()

        current_month_data = {
            "month": self._get_current_month_str(),
            "department": dept_name or "Unassigned",
            "count": msg_count,
            "quota": quota,
            "met": quota > 0 and msg_count >= quota,
            "is_current": True
        }

        history = await member_config.history()
        view = HistoryPaginator(target_user=target_member, history_data=history, current_month_data=current_month_data)
        await ctx.send(embed=view.make_embed(), view=view)

    @commands.group(name="quotaset")
    @checks.admin_or_permissions(manage_guild=True)
    async def quotaset(self, ctx: commands.Context):
        """Configure quota settings."""
        pass

    @quotaset.command(name="mainserver")
    async def set_main_server(self, ctx: commands.Context):
        """Set the current server as the primary tracking server."""
        await self.config.main_guild_id.set(ctx.guild.id)
        await self._send_embed(ctx, "Main Server Set", f"Quota tracking is now active for **{ctx.guild.name}**.", discord.Color.green())

    @quotaset.command(name="adddept")
    async def add_department(self, ctx: commands.Context, name: str, quota: int, manager_role: discord.Role):
        """Add or update a department."""
        async with self.config.guild(ctx.guild).departments() as depts:
            depts[name] = {
                "quota": quota,
                "manager_role_id": manager_role.id
            }
        await self._send_embed(ctx, "Department Created", f"Department **{name}** set to **{quota}** messages/month with manager role **{manager_role.name}**.", discord.Color.green())

    @quotaset.command(name="remdept")
    async def remove_department(self, ctx: commands.Context, name: str):
        """Remove a department."""
        async with self.config.guild(ctx.guild).departments() as depts:
            if name in depts:
                del depts[name]
                await self._send_embed(ctx, "Department Removed", f"Department **{name}** has been removed.", discord.Color.green())
            else:
                await self._send_embed(ctx, "Not Found", f"Department **{name}** does not exist.", discord.Color.red())

    @quotaset.command(name="assign")
    async def assign_staff(self, ctx: commands.Context, member: discord.Member, department_name: str):
        """Assign a member to a department."""
        guild_depts = await self.config.guild(ctx.guild).departments()
        if department_name not in guild_depts:
            return await self._send_embed(ctx, "Error", f"Department **{department_name}** does not exist.", discord.Color.red())

        await self.config.member(member).department.set(department_name)
        await self._send_embed(ctx, "Staff Assigned", f"Assigned **{member.display_name}** to **{department_name}**.", discord.Color.green())

    @quotaset.command(name="removestaff")
    async def remove_staff(self, ctx: commands.Context, member: discord.Member):
        """Completely remove a staff member and clear all tracking data."""
        await self.config.member(member).clear()
        await self._send_embed(ctx, "Staff Removed", f"All tracking data and assignments for **{member.display_name}** have been cleared.", discord.Color.green())
