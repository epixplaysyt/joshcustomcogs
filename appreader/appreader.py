import csv
import io
import asyncio
import discord
from redbot.core import Config, commands
from redbot.core.utils.predicates import MessagePredicate
from redbot.core.utils.chat_formatting import pagify

def round_score(val):
    if not val:
        return val
    val_str = str(val).strip()
    if "/" in val_str:
        parts = val_str.split("/")
        try:
            num = round(float(parts[0].strip()))
            return f"{num} / {parts[1].strip()}"
        except ValueError:
            return val_str
    else:
        try:
            return str(round(float(val_str)))
        except ValueError:
            return val_str

def has_app_role():
    async def predicate(ctx):
        if await ctx.bot.is_owner(ctx.author):
            return True
        if ctx.guild and ctx.author.guild_permissions.administrator:
            return True
        if ctx.guild:
            role_id = await ctx.cog.config.guild(ctx.guild).allowed_role_id()
            if role_id and ctx.author.get_role(role_id):
                return True
        raise commands.UserFeedbackCheckFailure("You do not have the required role to use this command, or the role hasn't been set up yet using `setapprole`.")
    return commands.check(predicate)


class SearchModal(discord.ui.Modal, title='Search Candidate'):
    search_input = discord.ui.TextInput(
        label='Discord Username',
        placeholder='Enter username to search...',
        style=discord.TextStyle.short
    )

    def __init__(self, view: 'AppReaderView'):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        query = self.search_input.value.lower()
        for idx, app in enumerate(self.view.applications):
            if query in (app["discord_username"] or "").lower():
                self.view.current_index = idx
                self.view.current_app_page = 0
                self.view.update_buttons_and_components()
                await interaction.response.edit_message(embed=self.view.get_embed(), view=self.view)
                return
        await interaction.response.send_message(f"Could not find a candidate matching `{query}`.", ephemeral=True)


class AppReaderView(discord.ui.View):
    def __init__(self, applications, ctx, cog):
        super().__init__(timeout=900)  # 15 minutes
        self.applications = applications
        self.ctx = ctx
        self.cog = cog
        self.current_index = 0
        self.current_app_page = 0
        self.message = None
        self.update_buttons_and_components()

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(content="**⏳ Viewing session ended. Run the command again to continue.**", view=self)
            except discord.HTTPException:
                pass

    def get_app_pages(self):
        app = self.applications[self.current_index]
        pages = []
        current_description = ""
        
        for item in app["q_and_a"]:
            q = item["question"]
            a = item["answer"]
            s = round_score(item["score"])
            f = item["feedback"]
            
            if not a and not s and not f:
                continue
                
            chunk = f"**{q}**\n"
            if a:
                chunk += f"{a}\n"
            if s:
                chunk += f"**Score:** {s}\n"
            if f:
                chunk += f"**Feedback:** {f}\n"
                
            chunk += "\n"
            
            if len(current_description) + len(chunk) > 3900:
                if current_description:
                    pages.append(current_description.strip())
                
                # If a single massive answer surpasses limits, chunk it forcibly
                if len(chunk) > 3900:
                    pages.append(chunk[:3900])
                    current_description = chunk[3900:]
                else:
                    current_description = chunk
            else:
                current_description += chunk
                
        if current_description:
            pages.append(current_description.strip())
            
        if not pages:
            pages.append("No answers provided.")
            
        return pages

    def update_buttons_and_components(self):
        self.clear_items()
        
        # --- Row 0: Application Navigation ---
        btn_prev_app = discord.ui.Button(style=discord.ButtonStyle.primary, emoji="⬅️", custom_id="prev_app", disabled=(self.current_index == 0))
        btn_prev_app.callback = self.prev_app
        self.add_item(btn_prev_app)
        
        btn_next_app = discord.ui.Button(style=discord.ButtonStyle.primary, emoji="➡️", custom_id="next_app", disabled=(self.current_index == len(self.applications) - 1))
        btn_next_app.callback = self.next_app
        self.add_item(btn_next_app)

        btn_search = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="🔍", custom_id="search_app")
        btn_search.callback = self.search_app
        self.add_item(btn_search)
        
        app = self.applications[self.current_index]
        if self.ctx.author.id in app["votes"]:
            btn_vote = discord.ui.Button(style=discord.ButtonStyle.success, label="Voted to Proceed ✅", custom_id="vote_app")
        else:
            btn_vote = discord.ui.Button(style=discord.ButtonStyle.secondary, label="Vote to Proceed 🗳️", custom_id="vote_app")
        btn_vote.callback = self.vote_button
        self.add_item(btn_vote)
        
        btn_release = discord.ui.Button(style=discord.ButtonStyle.success, label="Release Score", emoji="✉️", custom_id="release_score")
        btn_release.callback = self.release_button
        self.add_item(btn_release)

        # --- Row 1: Pagination (Only Appears if Application exceeds Discord limits) ---
        pages = self.get_app_pages()
        if len(pages) > 1:
            btn_prev_page = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="⬆️", label="Prev Page", custom_id="prev_page", disabled=(self.current_app_page == 0), row=1)
            btn_prev_page.callback = self.prev_page
            self.add_item(btn_prev_page)
            
            btn_next_page = discord.ui.Button(style=discord.ButtonStyle.secondary, emoji="⬇️", label="Next Page", custom_id="next_page", disabled=(self.current_app_page == len(pages) - 1), row=1)
            btn_next_page.callback = self.next_page
            self.add_item(btn_next_page)

    async def prev_app(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
        self.current_index -= 1
        self.current_app_page = 0
        self.update_buttons_and_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def next_app(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
        self.current_index += 1
        self.current_app_page = 0
        self.update_buttons_and_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
        
    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
        self.current_app_page -= 1
        self.update_buttons_and_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
        self.current_app_page += 1
        self.update_buttons_and_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def search_app(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
        await interaction.response.send_modal(SearchModal(self))

    async def vote_button(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            
        user_id = interaction.user.id
        max_votes = await self.cog.config.guild(self.ctx.guild).max_candidates()
        
        async with self.cog.config.guild(self.ctx.guild).apps() as saved_apps:
            if not saved_apps or self.current_index >= len(saved_apps):
                return await interaction.response.send_message("Application data is out of sync. Please restart the viewer.", ephemeral=True)
            
            target_app = saved_apps[self.current_index]
            
            if user_id in target_app["votes"]:
                target_app["votes"].remove(user_id)
            else:
                current_votes = sum(1 for a in saved_apps if user_id in a["votes"])
                if current_votes >= max_votes:
                    return await interaction.response.send_message(f"You have already reached your maximum of {max_votes} votes.", ephemeral=True)
                target_app["votes"].append(user_id)
            
            self.applications = saved_apps

        self.update_buttons_and_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def release_button(self, interaction: discord.Interaction):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            
        app = self.applications[self.current_index]
        username = app["discord_username"]
        score = round_score(app["total_score"])
        
        if not username or not score:
            return await interaction.response.send_message("This application is missing a valid Discord Username or Total Score.", ephemeral=True)
            
        member = self.ctx.guild.get_member_named(username)
        if not member:
            return await interaction.response.send_message(f"Could not find a user named `{username}` in the `{self.ctx.guild.name}` server.", ephemeral=True)
            
        try:
            custom_msg = await self.cog.config.guild(self.ctx.guild).custom_dm_message()
            embed = discord.Embed(
                title="🎉 Assessment Score Release",
                description=f"Congratulations **{member.display_name}**!\n\n{custom_msg}\n\n**Your Score:** `{score}`",
                color=discord.Color.green()
            )
            await member.send(embed=embed)
            await interaction.response.send_message(f"✅ Successfully sent the score embed to **{member.display_name}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Failed to send DM to **{member.display_name}**. They likely have DMs disabled.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: `{e}`", ephemeral=True)

    def get_embed(self):
        app = self.applications[self.current_index]
        pages = self.get_app_pages()
        
        embed = discord.Embed(
            title=f"Application {self.current_index + 1} of {len(self.applications)}",
            color=discord.Color.blue()
        )
        
        if len(pages) > 1:
            embed.title += f" (Page {self.current_app_page + 1} of {len(pages)})"
        
        if app["discord_username"]:
            embed.set_author(name=f"User: {app['discord_username']}")
        if app["total_score"]:
            embed.title += f" | Total Score: {round_score(app['total_score'])}"
        
        embed.description = pages[self.current_app_page]
        return embed

class ScoreMailer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=823479234823, force_registration=True)
        self.config.register_guild(
            allowed_role_id=None,
            custom_dm_message="Congratulations for completing the tester application! This score is only part of your application.",
            custom_success_message="Congratulations! Your application has been successful and you will proceed to the next stage.",
            custom_fail_message="Unfortunately, your application was not successful this time. Thank you for your interest.",
            apps=[],
            csv_text="",
            max_candidates=0,
            manual_success=[]
        )

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def setapprole(self, ctx, role: discord.Role):
        await self.config.guild(ctx.guild).allowed_role_id.set(role.id)
        await ctx.send(f"✅ The application reader role has been set to **{role.name}**.")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def setdmmsg(self, ctx, *, message: str):
        await self.config.guild(ctx.guild).custom_dm_message.set(message)
        await ctx.send(f"✅ The custom score DM message has been updated to:\n> {message}")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def setsuccessmsg(self, ctx, *, message: str):
        await self.config.guild(ctx.guild).custom_success_message.set(message)
        await ctx.send(f"✅ The custom successful candidate DM message has been updated to:\n> {message}")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def setfailmsg(self, ctx, *, message: str):
        await self.config.guild(ctx.guild).custom_fail_message.set(message)
        await ctx.send(f"✅ The custom failed candidate DM message has been updated to:\n> {message}")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def uploadapps(self, ctx, max_candidates: int):
        if max_candidates <= 0:
            return await ctx.send("The maximum number of candidates must be at least 1.")
            
        if not ctx.message.attachments:
            return await ctx.send("Please attach a `.csv` file to your message.")

        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith('.csv'):
            return await ctx.send("The attached file must be a CSV.")

        try:
            file_bytes = await attachment.read()
            text = file_bytes.decode('utf-8-sig') 
        except Exception as e:
            return await ctx.send(f"Failed to read the file. Error: `{e}`")
        
        reader = csv.reader(io.StringIO(text))
        
        try:
            headers = next(reader)
        except StopIteration:
            return await ctx.send("The CSV file is empty.")
            
        discord_col = 0
        score_col = 1
        
        for idx, header in enumerate(headers):
            h_lower = header.lower()
            if "discord username" in h_lower and not header.endswith("[Score]") and not header.endswith("[Feedback]"):
                discord_col = idx
            elif "total score" in h_lower:
                score_col = idx

        applications = []
        for row in reader:
            discord_username = row[discord_col].strip() if len(row) > discord_col else ""
            total_score = row[score_col].strip() if len(row) > score_col else ""
            
            col_map = {}
            for idx, header in enumerate(headers):
                if header.lower() in ["username", "email", "email address"]:
                    continue 
                    
                val = row[idx].strip() if idx < len(row) else ""
                
                is_score = header.endswith("[Score]")
                is_feedback = header.endswith("[Feedback]")
                
                if is_score:
                    base_q = header[:header.rfind("[Score]")].strip()
                elif is_feedback:
                    base_q = header[:header.rfind("[Feedback]")].strip()
                else:
                    base_q = header.strip()
                    
                if base_q not in col_map:
                    col_map[base_q] = {"question": base_q, "answer": None, "score": None, "feedback": None}
                    
                if is_score:
                    if val and val not in ["-- / 0", "-"]:
                        col_map[base_q]["score"] = val
                elif is_feedback:
                    if val:
                        col_map[base_q]["feedback"] = val
                else:
                    if val:
                        col_map[base_q]["answer"] = val
                        
            app_data = list(col_map.values())
            if any(item["answer"] for item in app_data):
                applications.append({
                    "discord_username": discord_username,
                    "total_score": total_score,
                    "q_and_a": app_data,
                    "votes": [] 
                })
                
        if not applications:
            return await ctx.send("No valid applications found in the CSV.")

        await self.config.guild(ctx.guild).apps.set(applications)
        await self.config.guild(ctx.guild).csv_text.set(text)
        await self.config.guild(ctx.guild).max_candidates.set(max_candidates)
        await self.config.guild(ctx.guild).manual_success.set([])
        
        await ctx.send(f"Successfully loaded {len(applications)} applications. Readers can vote for up to {max_candidates} candidates to proceed.")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def replaceapps(self, ctx):
        old_apps = await self.config.guild(ctx.guild).apps()
        if not old_apps:
            return await ctx.send("No applications currently exist to replace. Please use `uploadapps` first.")
            
        if not ctx.message.attachments:
            return await ctx.send("Please attach your updated `.csv` file to your message.")

        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith('.csv'):
            return await ctx.send("The attached file must be a CSV.")

        try:
            file_bytes = await attachment.read()
            text = file_bytes.decode('utf-8-sig') 
        except Exception as e:
            return await ctx.send(f"Failed to read the file. Error: `{e}`")
        
        reader = csv.reader(io.StringIO(text))
        
        try:
            headers = next(reader)
        except StopIteration:
            return await ctx.send("The CSV file is empty.")
            
        discord_col = 0
        score_col = 1
        
        for idx, header in enumerate(headers):
            h_lower = header.lower()
            if "discord username" in h_lower and not header.endswith("[Score]") and not header.endswith("[Feedback]"):
                discord_col = idx
            elif "total score" in h_lower:
                score_col = idx

        applications = []
        preserved_votes = 0
        valid_app_index = 0
        
        for row in reader:
            discord_username = row[discord_col].strip() if len(row) > discord_col else ""
            total_score = row[score_col].strip() if len(row) > score_col else ""
            
            col_map = {}
            for idx, header in enumerate(headers):
                if header.lower() in ["username", "email", "email address"]:
                    continue 
                    
                val = row[idx].strip() if idx < len(row) else ""
                
                is_score = header.endswith("[Score]")
                is_feedback = header.endswith("[Feedback]")
                
                if is_score:
                    base_q = header[:header.rfind("[Score]")].strip()
                elif is_feedback:
                    base_q = header[:header.rfind("[Feedback]")].strip()
                else:
                    base_q = header.strip()
                    
                if base_q not in col_map:
                    col_map[base_q] = {"question": base_q, "answer": None, "score": None, "feedback": None}
                    
                if is_score:
                    if val and val not in ["-- / 0", "-"]:
                        col_map[base_q]["score"] = val
                elif is_feedback:
                    if val:
                        col_map[base_q]["feedback"] = val
                else:
                    if val:
                        col_map[base_q]["answer"] = val
                        
            app_data = list(col_map.values())
            if any(item["answer"] for item in app_data):
                transferred_votes = []
                if valid_app_index < len(old_apps):
                    transferred_votes = old_apps[valid_app_index].get("votes", [])
                    preserved_votes += len(transferred_votes)
                    
                applications.append({
                    "discord_username": discord_username,
                    "total_score": total_score,
                    "q_and_a": app_data,
                    "votes": transferred_votes 
                })
                valid_app_index += 1
                
        if not applications:
            return await ctx.send("No valid applications found in the CSV.")

        await self.config.guild(ctx.guild).apps.set(applications)
        await self.config.guild(ctx.guild).csv_text.set(text)
        
        msg = f"✅ Successfully replaced **{len(applications)}** applications while preserving **{preserved_votes}** votes based on their row order."
        new_apps_count = max(0, len(applications) - len(old_apps))
        if new_apps_count > 0:
            msg += f"\n➕ Added **{new_apps_count}** new applications from the bottom rows."
            
        await ctx.send(msg)

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def readapps(self, ctx, sort: str = None):
        apps = await self.config.guild(ctx.guild).apps()
        if not apps:
            return await ctx.send("No applications have been uploaded for this server yet.")

        apps_to_read = list(apps)

        if sort and sort.lower() in ["score", "highest", "best"]:
            def get_sort_score(app):
                val = app["total_score"]
                if not val:
                    return -9999.0
                try:
                    if "/" in str(val):
                        return float(str(val).split("/")[0].strip())
                    return float(str(val).strip())
                except ValueError:
                    return -9999.0

            apps_to_read.sort(key=get_sort_score, reverse=True)

        view = AppReaderView(apps_to_read, ctx, self)
        try:
            msg = await ctx.author.send(embed=view.get_embed(), view=view)
            view.message = msg
            await ctx.message.add_reaction("✅")
        except discord.Forbidden:
            await ctx.send("I cannot DM you. Please make sure your server DMs are turned on.")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def rankcandidates(self, ctx):
        apps = await self.config.guild(ctx.guild).apps()
        if not apps:
            return await ctx.send("No applications have been uploaded for this server yet.")

        ranked_apps = [app for app in apps if len(app["votes"]) > 0]
        
        if not ranked_apps:
            return await ctx.send("No votes have been cast yet.")
            
        ranked_apps.sort(key=lambda x: len(x["votes"]), reverse=True)
        
        lines = ["### 🏆 **Candidate Rankings (Voted to Proceed)**"]
        for i, app in enumerate(ranked_apps, 1):
            username = app["discord_username"] or "Unknown User"
            votes = len(app["votes"])
            
            member = ctx.guild.get_member_named(username)
            if member:
                status = f"✅ `ID: {member.id}`"
            else:
                status = "❌ `Not found in server`"
                
            lines.append(f"**{i}.** {username} — **{votes}** vote(s) | {status}")
            
        text = "\n".join(lines)
        for page in pagify(text):
            await ctx.send(page)

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def addsuccess(self, ctx, user: discord.Member):
        apps = await self.config.guild(ctx.guild).apps()
        if not apps:
            return await ctx.send("No applications have been uploaded for this server yet.")
            
        async with self.config.guild(ctx.guild).manual_success() as manual:
            if user.id not in manual:
                manual.append(user.id)
                
        await ctx.send(f"✅ **{user.display_name}** (`{user.id}`) has been manually added to the successful candidates list.")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def removesuccess(self, ctx, user: discord.Member):
        apps = await self.config.guild(ctx.guild).apps()
        if not apps:
            return await ctx.send("No applications have been uploaded for this server yet.")
            
        async with self.config.guild(ctx.guild).manual_success() as manual:
            if user.id in manual:
                manual.remove(user.id)
                await ctx.send(f"✅ **{user.display_name}** (`{user.id}`) has been removed from the manual successful candidates list.")
            else:
                await ctx.send(f"❌ **{user.display_name}** is not in the manual successful candidates list.")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def mailresults(self, ctx):
        apps = await self.config.guild(ctx.guild).apps()
        if not apps:
            return await ctx.send("No applications have been uploaded for this server yet.")

        role_id = await self.config.guild(ctx.guild).allowed_role_id()
        if not role_id:
            return await ctx.send("The application reader role hasn't been set up yet. Use `setapprole`.")
            
        role = ctx.guild.get_role(role_id)
        if not role:
            return await ctx.send("The configured reader role no longer exists in this server.")

        readers = [m for m in role.members if not m.bot]
        reader_count = len(readers)
        
        if reader_count == 0:
            await ctx.send("⚠️ Warning: Nobody currently has the application reader role. Only manually added users will pass.")

        manual_success = await self.config.guild(ctx.guild).manual_success()
        
        successful_dms = []
        failed_dms = []
        not_found = []

        for app in apps:
            username = app["discord_username"].strip()
            if not username or username.lower() in ["username", "user", "name"]:
                continue
                
            member = ctx.guild.get_member_named(username)
            if not member:
                not_found.append(username)
                continue
                
            is_successful = False
            
            # Check if they have enough votes
            if reader_count > 0 and len(app["votes"]) >= reader_count:
                is_successful = True
                
            # Check if they were manually added (Supports new ID method and old username method)
            if member.id in manual_success or str(member.id) in manual_success or username.lower() in manual_success:
                is_successful = True
                
            if is_successful and member not in successful_dms:
                successful_dms.append(member)
            elif not is_successful and member not in failed_dms:
                failed_dms.append(member)
                
        failed_dms = [m for m in failed_dms if m not in successful_dms]

        if not successful_dms and not failed_dms:
            return await ctx.send("Could not find any matching users in this server to send results to.")

        preview_lines = []
        if successful_dms:
            preview_lines.append("### 🟢 **Successful Candidates (Accepted):**")
            for m in successful_dms:
                preview_lines.append(f"• **{m.display_name}** (`{m.name}`)")
                
        if failed_dms:
            preview_lines.append("\n### 🔴 **Unsuccessful Candidates (Rejected):**")
            for m in failed_dms:
                preview_lines.append(f"• **{m.display_name}** (`{m.name}`)")
                
        if not_found:
            preview_lines.append("\n### ⚠️ **Users NOT found (Skipping):**")
            for un in not_found:
                preview_lines.append(f"• `{un}`")

        preview_text = "\n".join(preview_lines)
        for page in pagify(preview_text):
            await ctx.send(page)

        await ctx.send(f"\n**Do you want to proceed with sending these result DMs?** (Type `yes` to send, `no` to cancel)\n*Success message count:* **{len(successful_dms)}** | *Fail message count:* **{len(failed_dms)}**")

        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=60.0)
        except asyncio.TimeoutError:
            return await ctx.send("You took too long to respond. Action cancelled.")
            
        if not pred.result:
            return await ctx.send("Action cancelled. No DMs were sent.")

        msg = await ctx.send("Sending Result DMs... Please wait. ⏳")
        successful_sent = 0
        failed_sent = 0
        dm_errors = 0
        
        success_msg_text = await self.config.guild(ctx.guild).custom_success_message()
        fail_msg_text = await self.config.guild(ctx.guild).custom_fail_message()

        for member in successful_dms:
            try:
                embed = discord.Embed(
                    title="🎉 Application Successful",
                    description=f"Hello **{member.display_name}**,\n\n{success_msg_text}",
                    color=discord.Color.green()
                )
                await member.send(embed=embed)
                successful_sent += 1
                await asyncio.sleep(1.5)
            except discord.HTTPException:
                dm_errors += 1

        for member in failed_dms:
            try:
                embed = discord.Embed(
                    title="📝 Application Status",
                    description=f"Hello **{member.display_name}**,\n\n{fail_msg_text}",
                    color=discord.Color.red()
                )
                await member.send(embed=embed)
                failed_sent += 1
                await asyncio.sleep(1.5)
            except discord.HTTPException:
                dm_errors += 1

        await msg.edit(content=f"✅ **Done!**\nSuccessfully sent **{successful_sent}** acceptance DMs and **{failed_sent}** rejection DMs.\nFailed to send **{dm_errors}** DMs (users likely have DMs disabled).")
    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def mailscores(self, ctx):
        csv_text = await self.config.guild(ctx.guild).csv_text()
        if not csv_text:
            return await ctx.send("No applications have been uploaded for this server yet.")

        reader = csv.reader(io.StringIO(csv_text))
        
        try:
            headers = next(reader)
        except StopIteration:
            return await ctx.send("The CSV file is empty.")
            
        discord_col = 0
        score_col = 1
        
        for idx, header in enumerate(headers):
            h_lower = header.lower()
            if "discord username" in h_lower and not header.endswith("[Score]") and not header.endswith("[Feedback]"):
                discord_col = idx
            elif "total score" in h_lower:
                score_col = idx
                
        pending_dms = []
        not_found = []
        
        for row in reader:
            if len(row) <= max(discord_col, score_col):
                continue
                
            username = row[discord_col].strip()
            score = round_score(row[score_col].strip())
            
            if not username or not score or username.lower() in ["username", "user", "name"] or score.lower() in ["score", "result"]:
                continue
            
            member = ctx.guild.get_member_named(username)
            if not member:
                not_found.append((username, score))
            else:
                pending_dms.append((member, score))
                
        if not pending_dms:
            return await ctx.send("Could not find any matching users in this server from the provided CSV.")
            
        preview_lines = ["### 📨 **Users to DM:**"]
        for member, score in pending_dms:
            preview_lines.append(f"• **{member.display_name}** (`{member.name}`) - Score: {score}")
            
        if not_found:
            preview_lines.append("\n### ⚠️ **Users NOT found (Will be skipped):**")
            for un, sc in not_found:
                preview_lines.append(f"• `{un}` - Score: {sc}")
                
        preview_text = "\n".join(preview_lines)
        
        for page in pagify(preview_text):
            await ctx.send(page)
            
        await ctx.send("\n**Do you want to proceed with sending these DMs?** (Type `yes` to send, `no` to cancel)")
        
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=60.0)
        except asyncio.TimeoutError:
            return await ctx.send("You took too long to respond. Action cancelled.")
            
        if not pred.result:
            return await ctx.send("Action cancelled. No DMs were sent.")
            
        msg = await ctx.send("Sending DMs... Please wait. ⏳")
        successful = 0
        failed = 0
        
        custom_msg = await self.config.guild(ctx.guild).custom_dm_message()
        
        for member, score in pending_dms:
            try:
                embed = discord.Embed(
                    title="🎉 Assessment Score Release",
                    description=f"Congratulations **{member.display_name}**!\n\n{custom_msg}\n\n**Your Score:** `{score}`",
                    color=discord.Color.green()
                )
                await member.send(embed=embed)
                successful += 1
                await asyncio.sleep(1)
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException:
                failed += 1
                
        await msg.edit(content=f"✅ **Done!**\nSuccessfully sent **{successful}** DMs.\nFailed to send **{failed}** DMs (users likely have DMs disabled).")
