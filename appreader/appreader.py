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

class AppReaderView(discord.ui.View):
    def __init__(self, applications, ctx, cog):
        super().__init__(timeout=900)
        self.applications = applications
        self.ctx = ctx
        self.cog = cog
        self.current_index = 0
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.current_index == 0)
        self.children[1].disabled = (self.current_index == len(self.applications) - 1)
        
        app = self.applications[self.current_index]
        if self.ctx.author.id in app["votes"]:
            self.children[2].style = discord.ButtonStyle.success
            self.children[2].label = "Voted to Proceed ✅"
        else:
            self.children[2].style = discord.ButtonStyle.secondary
            self.children[2].label = "Vote to Proceed"

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="⬅️", custom_id="prev_app")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
        self.current_index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(style=discord.ButtonStyle.primary, emoji="➡️", custom_id="next_app")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
        self.current_index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Vote to Proceed", emoji="🗳️", custom_id="vote_app")
    async def vote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message("You cannot use these buttons.", ephemeral=True)
            
        app = self.applications[self.current_index]
        guild_data = self.cog.server_data.get(self.ctx.guild.id)
        if not guild_data:
            return await interaction.response.send_message("Data for this server is no longer available.", ephemeral=True)
            
        max_votes = guild_data.get("max_candidates", 0)
        user_id = interaction.user.id
        
        if user_id in app["votes"]:
            app["votes"].remove(user_id)
        else:
            current_votes = sum(1 for a in guild_data["apps"] if user_id in a["votes"])
            if current_votes >= max_votes:
                return await interaction.response.send_message(f"You have already reached your maximum of {max_votes} votes.", ephemeral=True)
            app["votes"].add(user_id)
            
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(style=discord.ButtonStyle.success, label="Release Score", emoji="✉️", custom_id="release_score")
    async def release_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        embed = discord.Embed(
            title=f"Application {self.current_index + 1} of {len(self.applications)}",
            color=discord.Color.blue()
        )
        
        if app["discord_username"]:
            embed.set_author(name=f"User: {app['discord_username']}")
        if app["total_score"]:
            embed.title += f" | Total Score: {round_score(app['total_score'])}"
        
        description = ""
        for item in app["q_and_a"]:
            q = item["question"]
            a = item["answer"]
            s = round_score(item["score"])
            f = item["feedback"]
            
            if not a and not s and not f:
                continue
                
            chunk = f"**{q}**\n"
            if a:
                if len(a) > 1000:
                    a = a[:997] + "..."
                chunk += f"{a}\n"
            if s:
                chunk += f"**Score:** {s}\n"
            if f:
                chunk += f"**Feedback:** {f}\n"
                
            chunk += "\n"
            
            if len(description) + len(chunk) > 4000:
                description += "*... (Application truncated due to Discord length limits)*"
                break
                
            description += chunk
            
        embed.description = description.strip()
        return embed

class ScoreMailer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=823479234823, force_registration=True)
        self.config.register_guild(
            allowed_role_id=None,
            custom_dm_message="Congratulations for completing the tester application! This score is only part of your application."
        )
        self.server_data = {}

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
        await ctx.send(f"✅ The custom DM message has been updated to:\n> {message}")

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
                    "votes": set()
                })
                
        if not applications:
            return await ctx.send("No valid applications found in the CSV.")

        self.server_data[ctx.guild.id] = {
            "apps": applications,
            "csv_text": text,
            "max_candidates": max_candidates
        }
        await ctx.send(f"Successfully loaded {len(applications)} applications. Readers can vote for up to {max_candidates} candidates to proceed.")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def readapps(self, ctx, sort: str = None):
        guild_data = self.server_data.get(ctx.guild.id)
        if not guild_data or not guild_data.get("apps"):
            return await ctx.send("No applications have been uploaded for this server yet.")

        apps_to_read = list(guild_data["apps"])

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
            await ctx.author.send(embed=view.get_embed(), view=view)
            await ctx.message.add_reaction("✅")
        except discord.Forbidden:
            await ctx.send("I cannot DM you. Please make sure your server DMs are turned on.")

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def rankcandidates(self, ctx):
        guild_data = self.server_data.get(ctx.guild.id)
        if not guild_data or not guild_data.get("apps"):
            return await ctx.send("No applications have been uploaded for this server yet.")

        apps = guild_data["apps"]
        ranked_apps = [app for app in apps if len(app["votes"]) > 0]
        
        if not ranked_apps:
            return await ctx.send("No votes have been cast yet.")
            
        ranked_apps.sort(key=lambda x: len(x["votes"]), reverse=True)
        
        lines = ["### 🏆 **Candidate Rankings (Voted to Proceed)**"]
        for i, app in enumerate(ranked_apps, 1):
            username = app["discord_username"] or "Unknown User"
            votes = len(app["votes"])
            lines.append(f"**{i}.** {username} — **{votes}** vote(s)")
            
        text = "\n".join(lines)
        for page in pagify(text):
            await ctx.send(page)

    @commands.command()
    @commands.guild_only()
    @has_app_role()
    async def mailscores(self, ctx):
        guild_data = self.server_data.get(ctx.guild.id)
        if not guild_data or not guild_data.get("csv_text"):
            return await ctx.send("No applications have been uploaded for this server yet.")

        reader = csv.reader(io.StringIO(guild_data["csv_text"]))
        
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
