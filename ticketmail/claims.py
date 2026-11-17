import asyncio
import time

import discord


class AssigneeInviteView(discord.ui.View):
    def __init__(self, cog, channel_id, user_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel_id = channel_id
        self.user_id = user_id
        button = discord.ui.Button(label="Join ticket", style=discord.ButtonStyle.primary, custom_id=f"ticketmail:join:{channel_id}:{user_id}")
        button.callback = self.accept
        self.add_item(button)

    async def accept(self, interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This invitation belongs to someone else.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        channel = self.cog.bot.get_channel(self.channel_id)
        try:
            await self.cog.accept_assignee_invite(channel, self.user_id)
        except ValueError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        self.children[0].disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send(f"You are now a co-assignee in {channel.mention}.", ephemeral=True)


class ClaimsMixin:
    def init_claims(self):
        self._claim_lock = asyncio.Lock()
        self.config.register_channel(co_assignees=[], restricted_reply=False, assignee_invites={}, assignee_access_grants={})

    async def restore_claim_views(self):
        for channel_id, data in (await self.config.all_channels()).items():
            for user_id, invite in data.get("assignee_invites", {}).items():
                if invite["expires"] > time.time():
                    self.bot.add_view(AssigneeInviteView(self, int(channel_id), int(user_id)), message_id=invite["message_id"])

    async def can_reply_to_ticket(self, channel, user):
        member = channel.guild.get_member(user.id)
        if not member:
            return False
        permissions = channel.permissions_for(member)
        if not permissions.view_channel or not permissions.send_messages:
            return False
        data = await self.config.channel(channel).all()
        assigned = user.id == data.get("claimed_by") or user.id in data.get("co_assignees", [])
        if data.get("restricted_reply") and data.get("claimed_by"):
            return assigned
        return assigned or member.guild_permissions.manage_messages or await self.bot.is_owner(user)

    async def claim_ticket(self, channel, user, restrict):
        async with self._claim_lock:
            data = await self.config.channel(channel).all()
            if not data.get("owner_ids") and not data.get("owner_id"):
                raise ValueError("This channel is not an active ticket.")
            if data.get("claimed_by") not in (None, user.id):
                raise ValueError("This ticket is already claimed. Ask the claimant for an invitation.")
            async with self.config.channel(channel).all() as stored:
                stored["claimed_by"] = user.id
                stored["restricted_reply"] = restrict
            return data.get("claimed_by") is None

    async def invite_assignee(self, channel, claimant, member):
        async with self._claim_lock:
            data = await self.config.channel(channel).all()
            if data.get("claimed_by") != claimant.id:
                raise ValueError("Only the claimant can invite co-assignees.")
            if member.guild.id != channel.guild.id or member.bot:
                raise ValueError("Choose a staff-server member who is not a bot.")
            if not member.guild_permissions.manage_messages and not await self.bot.is_owner(member):
                raise ValueError("Co-assignees must have Manage Messages permission or be a bot owner.")
            if member.id == claimant.id or member.id in data.get("co_assignees", []):
                raise ValueError("That member is already assigned.")
            view = AssigneeInviteView(self, channel.id, member.id)
            message = await member.send(f"{claimant.display_name} invited you to help with ticket **{data.get('ticket_id') or channel.name}** in **{channel.guild.name}**.", view=view)
            async with self.config.channel(channel).assignee_invites() as invites:
                invites[str(member.id)] = dict(inviter_id=claimant.id, message_id=message.id, expires=time.time() + 86400)

    async def accept_assignee_invite(self, channel, user_id):
        if not channel:
            raise ValueError("This ticket no longer exists.")
        async with self._claim_lock:
            data = await self.config.channel(channel).all()
            invitation = data.get("assignee_invites", {}).get(str(user_id))
            if not invitation or invitation["expires"] <= time.time():
                raise ValueError("This invitation has expired or been revoked.")
            if not data.get("owner_ids") and not data.get("owner_id"):
                raise ValueError("This ticket has been closed.")
            if data.get("claimed_by") != invitation["inviter_id"]:
                raise ValueError("The claimant has changed. Request a new invitation.")
            member = channel.guild.get_member(user_id)
            if not member or member.bot:
                raise ValueError("You are no longer a member of the staff server.")
            if not member.guild_permissions.manage_messages and not await self.bot.is_owner(member):
                raise ValueError("You no longer have staff permissions to join this ticket.")
            previous = channel.overwrites_for(member)
            allow, deny = previous.pair()
            overwrite = discord.PermissionOverwrite.from_pair(allow, deny)
            overwrite.update(view_channel=True, send_messages=True, read_message_history=True)
            await channel.set_permissions(member, overwrite=overwrite, reason="Accepted co-assignee invitation")
            async with self.config.channel(channel).all() as stored:
                stored["assignee_access_grants"].setdefault(str(user_id), [allow.value, deny.value])
                if user_id not in stored["co_assignees"]:
                    stored["co_assignees"].append(user_id)
                stored["assignee_invites"].pop(str(user_id), None)

    async def remove_assignee(self, channel, claimant, member):
        async with self._claim_lock:
            data = await self.config.channel(channel).all()
            if data.get("claimed_by") != claimant.id:
                raise ValueError("Only the claimant can remove co-assignees.")
            previous = data.get("assignee_access_grants", {}).get(str(member.id))
            if previous is not None:
                overwrite = discord.PermissionOverwrite.from_pair(discord.Permissions(previous[0]), discord.Permissions(previous[1]))
                await channel.set_permissions(member, overwrite=None if overwrite.is_empty() else overwrite, reason="Removed ticket co-assignee")
            async with self.config.channel(channel).all() as stored:
                stored["co_assignees"] = [uid for uid in stored["co_assignees"] if uid != member.id]
                stored["assignee_invites"].pop(str(member.id), None)
                stored["assignee_access_grants"].pop(str(member.id), None)

    async def bypass_claim(self, channel, member):
        if not member.guild_permissions.administrator:
            raise ValueError("Administrator permission is required to bypass a claim.")
        async with self._claim_lock:
            data = await self.config.channel(channel).all()
            if not data.get("claimed_by") or (not data.get("owner_ids") and not data.get("owner_id")):
                raise ValueError("This ticket must have a claimant first.")
            async with self.config.channel(channel).co_assignees() as assignees:
                if member.id not in assignees:
                    assignees.append(member.id)
