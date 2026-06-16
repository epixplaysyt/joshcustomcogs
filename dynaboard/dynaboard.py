import discord
from redbot.core import commands, Config
from discord import app_commands

class EmbedBuilderModal(discord.ui.Modal):
    def __init__(self, view, title="Edit Board Info"):
        super().__init__(title=title)
        self.view = view
        
        self.b_name = discord.ui.TextInput(
            label="Menu Label (Board Name)", 
            default=view.board_data.get("name", ""),
            max_length=50
        )
        self.b_desc = discord.ui.TextInput(
            label="Menu Description", 
            default=view.board_data.get("description", ""), 
            required=False,
            max_length=100
        )
        self.e_title = discord.ui.TextInput(
            label="Embed Title", 
            default=view.board_data.get("title", ""),
            max_length=256
        )
        self.e_desc = discord.ui.TextInput(
            label="Embed Description", 
            style=discord.TextStyle.paragraph, 
            default=view.board_data.get("embed_description", ""),
            required=False,
            max_length=4000
        )
        
        self.add_item(self.b_name)
        self.add_item(self.b_desc)
        self.add_item(self.e_title)
        self.add_item(self.e_desc)

    async def on_submit(self, interaction: discord.Interaction):
        self.view.board_data["name"] = self.b_name.value
        self.view.board_data["description"] = self.b_desc.value
        self.view.board_data["title"] = self.e_title.value
        self.view.board_data["embed_description"] = self.e_desc.value
        await self.view.update_message(interaction)

class FieldBuilderModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Add Embed Field")
        self.view = view
        
        self.f_name = discord.ui.TextInput(
            label="Field Name", 
            max_length=256
        )
        self.f_value = discord.ui.TextInput(
            label="Field Value", 
            style=discord.TextStyle.paragraph,
            max_length=1024
        )
        
        self.add_item(self.f_name)
        self.add_item(self.f_value)

    async def on_submit(self, interaction: discord.Interaction):
        if "fields" not in self.view.board_data:
            self.view.board_data["fields"] = []
            
        self.view.board_data["fields"].append({
            "name": self.f_name.value,
            "value": self.f_value.value,
            "inline": False
        })
        await self.view.update_message(interaction)

class BuilderActionView(discord.ui.View):
    def __init__(self, cog, ctx, existing_data=None):
        super().__init__(timeout=300)
        self.cog = cog
        self.ctx = ctx
        self.message = None
        
        if existing_data:
            self.board_data = existing_data
            self.original_name = existing_data.get("name")
        else:
            self.original_name = None
            self.board_data = {
                "name": "New Board",
                "description": "Select this from the menu to read more.",
                "title": "Embed Title",
                "embed_description": "Embed Description",
                "color": discord.Color.blue().value,
                "fields": []
            }

    def generate_embed(self):
        embed = discord.Embed(
            title=self.board_data["title"],
            description=self.board_data["embed_description"],
            color=self.board_data["color"]
        )
        for field in self.board_data.get("fields", []):
            embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
        return embed

    async def update_message(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    @discord.ui.button(label="Edit Basics", style=discord.ButtonStyle.primary, custom_id="ib_edit")
    async def edit_basics(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedBuilderModal(self))

    @discord.ui.button(label="Add Field", style=discord.ButtonStyle.secondary, custom_id="ib_add_f")
    async def add_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.board_data.get("fields", [])) >= 25:
            return await interaction.response.send_message("❌ You cannot add more than 25 fields.", ephemeral=True)
        await interaction.response.send_modal(FieldBuilderModal(self))

    @discord.ui.button(label="Clear Fields", style=discord.ButtonStyle.danger, custom_id="ib_clear_f")
    async def clear_fields(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.board_data["fields"] = []
        await self.update_message(interaction)

    @discord.ui.button(label="Save Board", style=discord.ButtonStyle.success, custom_id="ib_save")
    async def save_board(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.cog.config.guild(self.ctx.guild).boards() as boards:
            # If renamed, delete the old entry
            if self.original_name and self.original_name != self.board_data["name"]:
                if self.original_name in boards:
                    del boards[self.original_name]
                    
            boards[self.board_data["name"]] = self.board_data
            
        for child in self.children:
            child.disabled = True
            
        await interaction.response.edit_message(content="✅ **Board saved successfully!**", embed=self.generate_embed(), view=self)
        self.stop()

class DynamicBoardSelect(discord.ui.Select):
    def __init__(self, boards: dict):
        options = []
        for name, data in list(boards.items())[:25]: # Hard limit 25 options
            desc = data.get("description", "")[:100]
            options.append(discord.SelectOption(label=name, description=desc, value=name))
            
        super().__init__(placeholder="Select a topic to view...", min_values=1, max_values=1, options=options)
        self.boards = boards

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        data = self.boards.get(selected)
        
        if not data:
            return await interaction.response.send_message("❌ This board data could not be found.", ephemeral=True)
        
        embed = discord.Embed(
            title=data.get("title", ""),
            description=data.get("embed_description", ""),
            color=data.get("color", discord.Color.blue().value)
        )
        for field in data.get("fields", []):
            embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
            
        # Respond ephemerally so only the user sees it
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DynamicBoardView(discord.ui.View):
    def __init__(self, boards: dict):
        super().__init__(timeout=None)
        self.add_item(DynamicBoardSelect(boards))

class InfoBoard(commands.Cog):
    """Dynamic Information Board System"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8374928374, force_registration=True)
        self.config.register_guild(boards={})

    @commands.group(name="infoboard", aliases=["ib"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def infoboard(self, ctx):
        """Commands for building and managing the dynamic info board."""
        pass

    @infoboard.command(name="build")
    async def ib_build(self, ctx, *, board_name: str = None):
        """
        Open the interactive embed builder.
        Provide a board name to edit an existing board, or leave blank to create a new one.
        """
        existing_data = None
        if board_name:
            boards = await self.config.guild(ctx.guild).boards()
            if board_name in boards:
                existing_data = boards[board_name]
            else:
                await ctx.send(f"⚠️ Board `{board_name}` not found. Creating a new one.")

        view = BuilderActionView(self, ctx, existing_data)
        embed = view.generate_embed()
        msg = await ctx.send("🛠️ **Info Board Builder**\nUse the buttons below to configure your board, then hit Save.", embed=embed, view=view)
        view.message = msg

    @infoboard.command(name="list")
    async def ib_list(self, ctx):
        """List all saved information boards."""
        boards = await self.config.guild(ctx.guild).boards()
        if not boards:
            return await ctx.send("❌ No boards have been created yet. Use `[p]infoboard build` to make one.")
            
        desc = "\n".join([f"• **{name}** - {data.get('description', 'No description')}" for name, data in boards.items()])
        embed = discord.Embed(title="Saved Info Boards", description=desc, color=discord.Color.green())
        await ctx.send(embed=embed)

    @infoboard.command(name="delete")
    async def ib_delete(self, ctx, *, board_name: str):
        """Delete an existing information board."""
        async with self.config.guild(ctx.guild).boards() as boards:
            if board_name in boards:
                del boards[board_name]
                await ctx.send(f"✅ Board `{board_name}` has been deleted.")
            else:
                await ctx.send(f"❌ Board `{board_name}` not found.")

    @infoboard.command(name="spawn")
    async def ib_spawn(self, ctx, *, starting_board: str):
        """
        Spawn the dynamic board in the current channel.
        Provides the starting embed and attaches the interactive dropdown for users.
        """
        boards = await self.config.guild(ctx.guild).boards()
        
        if not boards:
            return await ctx.send("❌ You haven't built any boards yet!")
            
        if starting_board not in boards:
            options = ", ".join([f"`{n}`" for n in boards.keys()])
            return await ctx.send(f"❌ Starting board not found. Available options: {options}")

        data = boards[starting_board]
        
        embed = discord.Embed(
            title=data.get("title", ""),
            description=data.get("embed_description", ""),
            color=data.get("color", discord.Color.blue().value)
        )
        for field in data.get("fields", []):
            embed.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))

        view = DynamicBoardView(boards)
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(InfoBoard(bot))
