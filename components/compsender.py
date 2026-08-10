import json
import discord
from redbot.core import commands
from redbot.core.bot import Red

class JsonEmbeds(commands.Cog):
    """Send custom embeds from JSON data."""

    def __init__(self, bot: Red):
        self.bot = bot

    @commands.command()
    @commands.mod_or_permissions(manage_messages=True)
    async def sendjson(self, ctx: commands.Context, *, json_data: str = None):
        """
        Send an embed built from JSON data.

        You can either provide the JSON as a text argument (inside a code block)
        or attach a `.json` file to your command message.
        """
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

        json_data = json_data.strip()
        if json_data.startswith("```json"):
            json_data = json_data[7:]
        elif json_data.startswith("```"):
            json_data = json_data[3:]
        
        if json_data.endswith("```"):
            json_data = json_data[:-3]

        json_data = json_data.strip()

        try:
            data = json.loads(json_data)
        except json.JSONDecodeError as e:
            return await ctx.send(f"❌ **Invalid JSON format:**\n```py\n{e}\n```")

        embed_dicts = []
        if "embeds" in data:
            embed_dicts = data["embeds"]
        elif "embed" in data:
            embed_dicts = [data["embed"]]
        else:
            embed_dicts = [data]

        embeds = []
        for edict in embed_dicts:
            try:
                embeds.append(discord.Embed.from_dict(edict))
            except Exception as e:
                return await ctx.send(f"❌ **Failed to parse embed data:**\n```py\n{e}\n```")

        if not embeds:
            return await ctx.send("❌ No valid embed data found in the JSON.")
        try:
            await ctx.send(embeds=embeds[:10])
        except discord.HTTPException as e:
            await ctx.send(f"❌ **Discord rejected the embed.** Ensure you haven't exceeded character limits (e.g., descriptions over 4096 chars).\n```py\n{e}\n```")
