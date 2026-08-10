import json
import discord
from redbot.core import commands
from redbot.core.bot import Red

class JsonEmbeds(commands.Cog):
    """Send raw JSON payloads directly to Discord."""

    def __init__(self, bot: Red):
        self.bot = bot

    @commands.command()
    @commands.mod_or_permissions(manage_messages=True)
    async def sendjson(self, ctx: commands.Context, *, json_data: str = None):
        if json_data is None:
            if ctx.message.attachments:
                attachment = ctx.message.attachments[0]
                if attachment.filename.endswith(".json"):
                    try:
                        json_data = (await attachment.read()).decode("utf-8")
                    except Exception as e:
                        return await ctx.send(f"❌ Failed to read the file: {e}")
                else:
                    return await ctx.send("❌ Please attach a valid `.json` file.")
            else:
                return await ctx.send_help()

        # Clean up Markdown code blocks
        json_data = json_data.strip()
        if json_data.startswith("```json"):
            json_data = json_data[7:]
        elif json_data.startswith("```"):
            json_data = json_data[3:]
        
        if json_data.endswith("```"):
            json_data = json_data[:-3]

        json_data = json_data.strip()

        try:
            payload = json.loads(json_data)
        except json.JSONDecodeError as e:
            return await ctx.send(f"❌ **Invalid JSON format:**\n```py\n{e}\n```")

        route = discord.http.Route(
            "POST", 
            "/channels/{channel_id}/messages", 
            channel_id=ctx.channel.id
        )

        try:
            await self.bot.http.request(route, json=payload)
            
            try:
                await ctx.message.add_reaction("✅")
            except discord.HTTPException:
                pass 
                
        except discord.HTTPException as e:
            await ctx.send(f"❌ **Discord API rejected the payload:**\n```py\n{e}\n```")
