import discord
from redbot.core import commands

class MMWelcome(commands.Cog):
    """Sends the exact MM Tech Studios Welcome Board using Layout Components V2."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="sendwelcome")
    @commands.admin_or_permissions(manage_guild=True)
    async def send_welcome_board(self, ctx, channel: discord.TextChannel = None):
        """Sends the updated raw layout v2 message payload to the specified channel."""
        target_channel = channel or ctx.channel

        # Your updated message data payload
        message_data = {
            "flags": 36864,
            "allowed_mentions": {
                "parse": []
            },
            "components": [
                {
                    "type": 12,
                    "items": [
                        {
                            "media": {
                                "url": "https://cdn.discordapp.com/attachments/1188935389440913500/1516545432464134246/Your_paragraph_text_1.png?ex=6a33087f&is=6a31b6ff&hm=441c6b10294e9e77bb5cd395b08a289d21587cc1092bf4cf6af0199d901a3747"
                            }
                        }
                    ]
                },
                {
                    "type": 17,
                    "accent_color": 15702551,
                    "components": [
                        {
                            "type": 10,
                            "content": "# 👋 Welcome to MM Tech Studios!"
                        },
                        {
                            "type": 10,
                            "content": "🛤️ Welcome to the official home of our development team! MM Tech Studios is a dedicated game studio focused on crafting high-fidelity railway simulation experiences on Roblox. Our core project is a realistic recreation of the London Underground network, specifically the **Jubilee** and **Metropolitan** lines, where players can take control as train drivers, manage station operations as dispatchers, or simply relax and travel as passengers!"
                        },
                        {
                            "type": 14,
                            "spacing": 1,
                            "divider": True
                        },
                        {
                            "type": 10,
                            "content": "## Navigating the Server\n- <#1331299049097400393>: Stay updated on our latest development progress, updates to the server, and major project news.\n\n- <#1331299112695632023>: See our latest sneak peaks and future updates for our upcoming games.\n\n- <#1493306264300814496>: Find all our official social media, our Roblox group, and community pages in one place.\n\n- <#1507469512218378341>: Keep track of upcoming community activities, development Q&As, and other events.\n\n- <#1184227194583654540>: Need assistance or have questions about our upcoming projects? Open a ticket here and our team will help you.\n\n**Most importantly,** read our community guidelines in <#1180039332288016415> to keep yourself up-to-date on our expectations!"
                        },
                        {
                            "type": 14,
                            "spacing": 1,
                            "divider": True
                        },
                        {
                            "type": 10,
                            "content": "## Our Roles\n- <@&1505601180276097084>: The high-level leadership team responsible for the strategic decisions, final approvals, and overall direction of the studio.\n\n- <@&1516556336811348158>: The management team that handles daily logistics, coordinates staff teams, and ensures everything runs smoothly.\n\n- <@&1374807363093270626>: The technical and creative team who are actively constructing our upcoming experiences.\n\n- <@&1341181728462475315>: The dedicated team responsible for keeping the community safe, answering support questions, and enforcing server rules.\n\n- <@&1498003777620545729>: The creative team responsible for running events, hosting activities, and keeping the server active and fun.\n\n- <@&1181635931413954683>: The core of our community. This role belongs to all of our group members!"
                        },
                        {
                            "type": 14,
                            "spacing": 1,
                            "divider": True
                        },
                        {
                            "type": 10,
                            "content": "## Quick Links"
                        },
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 5,
                                    "label": "👥 Roblox Group",
                                    "url": "https://www.roblox.com/communities/33469792/MM-TECH-STUDIOS#!/about"
                                },
                                {
                                    "type": 2,
                                    "style": 5,
                                    "label": "👾 Preview Game",
                                    "url": "https://www.roblox.com/games/110934602602000/Jubilee-line-Showcase-game"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        # Setup custom route bypass for channel messages endpoint
        route = discord.http.Route("POST", f"/channels/{target_channel.id}/messages")
        
        try:
            await self.bot.http.request(route, json=message_data)
            if target_channel != ctx.channel:
                await ctx.send(f"✅ Updated welcome board successfully pushed to {target_channel.mention}!")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Failed to send layout components. Error: `{e.text}`")

async def setup(bot):
    await bot.add_cog(MMWelcome(bot))
