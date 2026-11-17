import asyncio
import time
import uuid
from functools import wraps

import discord


DEFAULT_QUESTIONS = [
    "Why are you appealing this punishment?",
    "What happened from your point of view?",
    "What would you do differently?",
]


def serialize_appeal_action(function):
    @wraps(function)
    async def wrapped(self, *args, **kwargs):
        async with self._appeal_lock:
            return await function(self, *args, **kwargs)
    return wrapped


class AppealModal(discord.ui.Modal):
    def __init__(self, cog, guild_id, punishment_id, user_id, questions):
        super().__init__(title="Punishment appeal", timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.punishment_id = punishment_id
        self.user_id = user_id
        self.questions = questions
        self.answers = []
        for question in questions:
            field = discord.ui.TextInput(label=question[:45], style=discord.TextStyle.paragraph, max_length=1000, required=True)
            self.add_item(field)
            self.answers.append(field)

    async def on_submit(self, interaction):
        if interaction.user.id != self.user_id or interaction.guild is not None:
            return await interaction.response.send_message("This form belongs to someone else.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await self.cog.submit_appeal(self.guild_id, self.punishment_id, self.user_id, list(zip(self.questions, [answer.value for answer in self.answers])))
        except (ValueError, discord.HTTPException) as exc:
            return await interaction.followup.send(f"The appeal could not be sent: {exc}", ephemeral=True)
        await interaction.followup.send("Your appeal has been sent to staff. The decision will arrive here.", ephemeral=True)


class AppealEntryView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Appeal punishment", style=discord.ButtonStyle.secondary, custom_id="advmod:appeal_form")
    async def appeal(self, interaction, button):
        index = await self.cog.config.appeal_dm_index()
        entry = index.get(str(interaction.message.id))
        if not entry or interaction.guild is not None:
            return await interaction.response.send_message("This appeal link is no longer available.", ephemeral=True)
        try:
            record = await self.cog.get_appealable_record(entry["guild_id"], entry["punishment_id"], interaction.user.id)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        questions = await self.cog.config.guild_from_id(entry["guild_id"]).appeal_questions()
        await interaction.response.send_modal(AppealModal(self.cog, entry["guild_id"], entry["punishment_id"], record["user_id"], questions))


class AppealReviewView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def decide(self, interaction, accepted):
        required_level = 4 if accepted else 3
        if not interaction.guild or not await self.cog._has_level_member(interaction.guild, interaction.user, required_level):
            message = "Manager clearance is required to accept appeals." if accepted else "Class III or higher is required to deny appeals."
            return await interaction.response.send_message(message, ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.cog.review_appeal(interaction.guild, interaction.message.id, interaction.user, accepted)
        except (ValueError, discord.HTTPException) as exc:
            return await interaction.followup.send(f"The decision was not applied: {exc}", ephemeral=True)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Accepted" if accepted else "Denied", style=discord.ButtonStyle.success if accepted else discord.ButtonStyle.danger, disabled=True))
        await interaction.message.edit(content=f"{'Accepted' if accepted else 'Denied'} by {interaction.user.mention}", view=view, allowed_mentions=discord.AllowedMentions.none())
        await interaction.followup.send(result, ephemeral=True)

    @discord.ui.button(label="Accept appeal", style=discord.ButtonStyle.success, custom_id="advmod:appeal_accept")
    async def accept(self, interaction, button):
        await self.decide(interaction, True)

    @discord.ui.button(label="Deny appeal", style=discord.ButtonStyle.danger, custom_id="advmod:appeal_deny")
    async def deny(self, interaction, button):
        await self.decide(interaction, False)


class AppealsMixin:
    def init_appeals(self):
        self._appeal_lock = asyncio.Lock()
        self.config.register_global(appeal_dm_index={})
        self.config.register_guild(appeal_channel=None, appeal_rejoin_channel=None, appeal_questions=DEFAULT_QUESTIONS, appeal_delay_seconds=0, punishment_records={}, appeal_requests={})

    async def record_punishment(self, guild, user, kind, moderator, reason, appealable=True, **details):
        punishment_id = uuid.uuid4().hex
        async with self.config.guild(guild).punishment_records() as records:
            if kind in {"ban", "timeout"}:
                for record in records.values():
                    if record["user_id"] == user.id and record["kind"] == kind and record["status"] == "active":
                        record["status"] = "superseded"
            records[punishment_id] = dict(user_id=user.id, kind=kind, moderator_id=moderator.id, reason=reason, appealable=appealable, created_at=time.time(), status="active", **details)
        return punishment_id

    async def offer_appeal(self, guild, user, punishment_id):
        settings = await self.config.guild(guild).all()
        record = settings["punishment_records"][punishment_id]
        if not settings["appeal_channel"] or not record["appealable"]:
            return
        eligible = int(record["created_at"] + settings["appeal_delay_seconds"])
        embed = discord.Embed(title=f"Appeal your {record['kind']} — {guild.name}", description=f"**Reason:** {record['reason'][:3500]}\n\nUse the button below to send an appeal to staff. Available <t:{eligible}:R>.", color=discord.Color.blurple())
        try:
            message = await user.send(embed=embed, view=AppealEntryView(self))
        except discord.HTTPException:
            return
        async with self.config.appeal_dm_index() as index:
            index[str(message.id)] = dict(guild_id=guild.id, punishment_id=punishment_id)

    async def get_appealable_record(self, guild_id, punishment_id, user_id):
        settings = await self.config.guild_from_id(guild_id).all()
        record = settings["punishment_records"].get(punishment_id)
        if not record or record["user_id"] != user_id or not record["appealable"]:
            raise ValueError("This punishment cannot be appealed.")
        if record["status"] != "active":
            raise ValueError("This punishment is no longer active.")
        if time.time() < record["created_at"] + settings["appeal_delay_seconds"]:
            raise ValueError("Your appeal window has not opened yet.")
        if punishment_id in settings["appeal_requests"]:
            raise ValueError("An appeal has already been submitted for this punishment.")
        return record

    async def submit_appeal(self, guild_id, punishment_id, user_id, answers):
        async with self._appeal_lock:
            record = await self.get_appealable_record(guild_id, punishment_id, user_id)
            guild = self.bot.get_guild(guild_id)
            channel_id = await self.config.guild_from_id(guild_id).appeal_channel()
            channel = guild.get_channel(channel_id) if guild and channel_id else None
            if not channel:
                raise ValueError("The appeal review channel is unavailable. Contact staff.")
            if not 1 <= len(answers) <= 5 or any(not str(answer).strip() or len(str(answer)) > 1000 for _, answer in answers):
                raise ValueError("Complete every answer using no more than 1,000 characters.")
            embed = discord.Embed(title="Punishment appeal", description=f"**User:** <@{user_id}> (`{user_id}`)\n**Punishment:** {record['kind']}\n**Reason:** {record['reason'][:500]}", color=discord.Color.blurple())
            for question, answer in answers:
                embed.add_field(name=str(question)[:45], value=str(answer), inline=False)
            message = await channel.send(embed=embed, view=AppealReviewView(self), allowed_mentions=discord.AllowedMentions.none())
            async with self.config.guild_from_id(guild_id).appeal_requests() as requests:
                requests[punishment_id] = dict(user_id=user_id, message_id=message.id, channel_id=channel.id, answers=answers, status="pending", submitted_at=time.time())

    async def reverse_punishment(self, guild, punishment_id, record, reviewer):
        user = self.bot.get_user(record["user_id"]) or await self.bot.fetch_user(record["user_id"])
        reason = f"Appeal accepted by {reviewer}"
        if record["kind"] == "ban":
            try:
                ban = await guild.fetch_ban(user)
            except discord.NotFound:
                raise ValueError("This user is no longer banned.")
            if ban.reason != record.get("ban_reason"):
                raise ValueError("The ban has changed since this appeal. Review the current punishment separately.")
            await guild.unban(user, reason=reason)
            async with self.config.guild(guild).pending_appeals() as pending:
                pending[:] = [item for item in pending if item["user_id"] != user.id]
        elif record["kind"] == "timeout":
            member = guild.get_member(user.id) or await guild.fetch_member(user.id)
            current = member.timed_out_until.timestamp() if member.timed_out_until else None
            if current is None or abs(current - record["until"]) > 2:
                raise ValueError("This timeout has expired or been changed.")
            await member.timeout(None, reason=reason)
        elif record["kind"] == "warning":
            async with self.config.member_from_ids(guild.id, user.id).warnings() as warnings:
                match = next((item for item in warnings if item.get("id") == record["warning_id"]), None)
                if match is None:
                    raise ValueError("This warning has already been removed.")
                warnings.remove(match)
        elif record["kind"] == "kick":
            try:
                await guild.fetch_ban(user)
            except discord.NotFound:
                pass
            else:
                raise ValueError("This user is now banned. A kick appeal cannot remove a ban.")
            channel_id = await self.config.guild(guild).appeal_rejoin_channel()
            channel = guild.get_channel(channel_id) if channel_id else guild.system_channel
            if not channel:
                raise ValueError("Configure a rejoin invite channel before accepting a kick appeal.")
            invite = await channel.create_invite(max_age=86400, max_uses=1, unique=True, reason=reason)
            return user, f"Your kick appeal was accepted. You can rejoin using this invitation: {invite.url}"
        else:
            raise ValueError("Unsupported punishment type.")
        return user, f"Your {record['kind']} appeal in **{guild.name}** was accepted. The punishment has been removed."

    async def review_appeal(self, guild, message_id, reviewer, accepted):
        required_level = 4 if accepted else 3
        if not await self._has_level_member(guild, reviewer, required_level):
            raise ValueError("Manager clearance is required to accept appeals." if accepted else "Class III or higher is required to deny appeals.")
        async with self._appeal_lock:
            requests = await self.config.guild(guild).appeal_requests()
            punishment_id = next((key for key, item in requests.items() if item["message_id"] == message_id), None)
            if punishment_id is None or requests[punishment_id]["status"] != "pending":
                raise ValueError("This appeal has already been handled or is unavailable.")
            records = await self.config.guild(guild).punishment_records()
            record = records[punishment_id]
            if accepted:
                if record["status"] != "active":
                    raise ValueError("This punishment has been replaced or removed. It cannot be reverted by this appeal.")
                user, notification = await self.reverse_punishment(guild, punishment_id, record, reviewer)
                async with self.config.guild(guild).punishment_records() as stored:
                    stored[punishment_id]["status"] = "reverted"
            else:
                user = self.bot.get_user(record["user_id"]) or await self.bot.fetch_user(record["user_id"])
                notification = f"Your {record['kind']} appeal in **{guild.name}** was denied. The punishment remains in place."
            async with self.config.guild(guild).appeal_requests() as stored:
                stored[punishment_id].update(status="accepted" if accepted else "denied", reviewer_id=reviewer.id, reviewed_at=time.time())
            try:
                await user.send(notification, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                return "Decision saved, but the user could not be notified because their DMs are unavailable."
            return "Decision saved and the user has been notified."
