import aiohttp
import discord
from redbot.core import commands, Config
from discord.ext import tasks

class PayoutTracker(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9384759283, force_registration=True)
        
        default_global = {
            "api_key": None,
            "list_id": None,
            "cf_roblox": None,
            "cf_prize": None,
            "cf_category": None,
            "cf_authoriser": None,
            "tracked_tasks": {}
        }
        default_guild = {
            "payout_role": None
        }
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        self.check_tasks_loop.start()

    def cog_unload(self):
        self.check_tasks_loop.cancel()

    @commands.group()
    @commands.is_owner()
    async def clickupset(self, ctx):
        pass

    @clickupset.command(name="key")
    async def set_api_key(self, ctx, key: str):
        await self.config.api_key.set(key)
        await ctx.send("ClickUp API Key has been saved.")

    @clickupset.command(name="list")
    async def set_list_id(self, ctx, list_id: str):
        await self.config.list_id.set(list_id)
        await ctx.send("ClickUp List ID has been saved.")

    @clickupset.command(name="fields")
    async def set_fields(self, ctx, roblox_id: str, prize_id: str, category_id: str, authoriser_id: str):
        await self.config.cf_roblox.set(roblox_id)
        await self.config.cf_prize.set(prize_id)
        await self.config.cf_category.set(category_id)
        await self.config.cf_authoriser.set(authoriser_id)
        await ctx.send("Custom field IDs saved successfully.")

    @clickupset.command(name="role")
    async def set_role(self, ctx, role: discord.Role):
        await self.config.guild(ctx.guild).payout_role.set(role.id)
        await ctx.send(f"Payout role has been set to `{role.name}`.")

    @commands.command()
    async def logpayout(self, ctx, user: discord.Member, roblox_username: str, prize: str, *, prize_category: str):
        role_id = await self.config.guild(ctx.guild).payout_role()
        if not role_id:
            return await ctx.send("The payout role has not been configured. Use `[p]clickupset role` first.")
            
        has_role = any(role.id == role_id for role in ctx.author.roles)
        if not has_role and ctx.author.id not in self.bot.owner_ids:
            return await ctx.send("You do not have the required role to log payouts.")

        config = await self.config.all()
        
        if not all([config["api_key"], config["list_id"], config["cf_roblox"], config["cf_prize"], config["cf_category"], config["cf_authoriser"]]):
            return await ctx.send("ClickUp configuration is incomplete. Use `[p]clickupset` first.")

        url = f"https://api.clickup.com/api/v2/list/{config['list_id']}/task"
        headers = {
            "Authorization": config["api_key"],
            "Content-Type": "application/json"
        }

        payload = {
            "name": user.name,
            "status": "LOGGED",
            "custom_fields": [
                {"id": config["cf_roblox"], "value": roblox_username},
                {"id": config["cf_prize"], "value": prize},
                {"id": config["cf_category"], "value": prize_category},
                {"id": config["cf_authoriser"], "value": ctx.author.name}
            ]
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    task_id = data.get("id")
                    due_date = data.get("due_date")
                    
                    display_status = self.determine_display_status("LOGGED", due_date)
                    embed = self.build_embed(display_status, roblox_username, prize, prize_category, due_date)
                    
                    msg_id = None
                    channel_id = None
                    try:
                        msg = await user.send(content="👋 Hey there! Your payout has been officially logged in our system.", embed=embed)
                        msg_id = msg.id
                        channel_id = msg.channel.id
                    except discord.Forbidden:
                        await ctx.send(f"⚠️ Task created, but could not DM {user.mention}.")

                    async with self.config.tracked_tasks() as tasks_dict:
                        tasks_dict[task_id] = {
                            "message_id": msg_id,
                            "channel_id": channel_id,
                            "user_id": user.id,
                            "status": "LOGGED",
                            "due_date": due_date,
                            "roblox_username": roblox_username,
                            "prize": prize,
                            "category": prize_category
                        }
                        
                    await ctx.send(f"✅ Payout logged successfully for `{user.name}`!")
                else:
                    error_data = await response.text()
                    await ctx.send(f"❌ Failed to create task in ClickUp. Status: {response.status}\nError: {error_data}")

    def build_embed(self, display_status, roblox_username, prize, category, due_date=None):
        color_map = {
            "Logged": discord.Color.purple(),
            "Scheduled": discord.Color.gold(),
            "Paid out": discord.Color.green()
        }
        emoji_map = {
            "Logged": "📝",
            "Scheduled": "⏳",
            "Paid out": "✅"
        }
        
        status_emoji = emoji_map.get(display_status, "🔍")
        
        embed = discord.Embed(
            title="💸 Payout Status",
            color=color_map.get(display_status, discord.Color.blue())
        )
        embed.add_field(name="📊 Current Status", value=f"{status_emoji} **{display_status}**", inline=False)
        
        if display_status == "Scheduled" and due_date:
            try:
                timestamp = int(int(due_date) / 1000)
                embed.add_field(name="🕒 Scheduled Date", value=f" ()", inline=False)
            except (ValueError, TypeError):
                pass
                
        embed.add_field(name="🎮 Roblox Username", value=f"`{roblox_username}`", inline=True)
        embed.add_field(name="🎁 Prize", value=f"`{prize}`", inline=True)
        embed.add_field(name="📁 Category", value=f"`{category}`", inline=True)
        
        return embed

    def determine_display_status(self, raw_status, due_date):
        if due_date:
            return "Scheduled"
        if raw_status in ["PAID OUT", "PAID"]:
            return "Paid out"
        return "Logged"

    @tasks.loop(minutes=5)
    async def check_tasks_loop(self):
        config = await self.config.all()
        if not config["api_key"] or not config["list_id"]:
            return
            
        tracked_tasks = config["tracked_tasks"]
        if not tracked_tasks:
            return

        url = f"https://api.clickup.com/api/v2/list/{config['list_id']}/task?include_closed=true"
        headers = {
            "Authorization": config["api_key"],
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return
                
                data = await response.json()
                api_tasks = data.get("tasks", [])

                for task in api_tasks:
                    task_id = task.get("id")
                    if task_id in tracked_tasks:
                        raw_status = task.get("status", {}).get("status", "").upper()
                        due_date = task.get("due_date")
                        
                        if raw_status == "UNLOGGED":
                            continue

                        task_record = tracked_tasks[task_id]
                        stored_status = task_record.get("status", "")
                        stored_due = task_record.get("due_date")
                        
                        display_status = self.determine_display_status(raw_status, due_date)
                        
                        if raw_status != stored_status or due_date != stored_due:
                            await self.update_user_embed(task_record, display_status, due_date)
                            
                            async with self.config.tracked_tasks() as t_tasks:
                                t_tasks[task_id]["status"] = raw_status
                                t_tasks[task_id]["due_date"] = due_date

    async def update_user_embed(self, task_record, display_status, due_date):
        try:
            channel = None
            if task_record.get("channel_id"):
                channel = self.bot.get_channel(task_record["channel_id"])
            if not channel:
                user = self.bot.get_user(task_record["user_id"]) or await self.bot.fetch_user(task_record["user_id"])
                if user:
                    channel = await user.create_dm()
            
            if not channel:
                return

            embed = self.build_embed(
                display_status,
                task_record.get("roblox_username", "N/A"),
                task_record.get("prize", "N/A"),
                task_record.get("category", "N/A"),
                due_date
            )
            
            content = "🔔 Hey there! The status of your payout has been updated."

            if task_record.get("message_id"):
                try:
                    msg = await channel.fetch_message(task_record["message_id"])
                    await msg.edit(content=content, embed=embed)
                    return
                except discord.NotFound:
                    pass

            user = self.bot.get_user(task_record["user_id"]) or await self.bot.fetch_user(task_record["user_id"])
            if user:
                msg = await user.send(content=content, embed=embed)
                async with self.config.tracked_tasks() as t_tasks:
                    for tid, tdata in t_tasks.items():
                        if tdata.get("user_id") == task_record["user_id"]:
                            t_tasks[tid]["message_id"] = msg.id
                            t_tasks[tid]["channel_id"] = msg.channel.id
                            break
            
        except discord.Forbidden:
            pass
        except Exception:
            pass

    @check_tasks_loop.before_loop
    async def before_check_tasks(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(PayoutTracker(bot))
