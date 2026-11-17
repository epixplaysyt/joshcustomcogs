import asyncio
import base64
import datetime
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from test_regressions import guild, interaction, make_cog


@pytest.mark.parametrize('value,seconds', [('30m', 1800), ('30 minutes', 1800), ('12h', 43200), ('12 hours', 43200), ('14d', 1209600), ('14 days', 1209600), ('1h30m', 5400), ('1 hour and 30 minutes', 5400), ('6mo', 181 * 86400), ('6 months', 181 * 86400)])
def test_custom_durations(value, seconds):
    from AdvancedMod.durations import parse_duration
    assert parse_duration(value, datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)) == seconds


@pytest.mark.parametrize('value', ['-1d', '3 elephants', '14d garbage', '0h', '1.5h', '99999999999999y', ''])
def test_invalid_durations(value):
    from AdvancedMod.durations import parse_duration
    with pytest.raises(ValueError):
        parse_duration(value)


@pytest.mark.asyncio
async def test_ban_has_free_text_duration_and_no_strictban(make_cog):
    cog = make_cog('AdvancedMod.advmod')
    assert 'strictban' not in {command.name for command in cog.get_commands()}
    parameter = next(p for p in cog.ban.app_command.parameters if p.name == 'duration')
    assert not parameter.choices


async def appeal_case(make_cog, kind='ban', **details):
    cog = make_cog('AdvancedMod.advmod')
    g = guild()
    user = SimpleNamespace(id=42, send=AsyncMock(return_value=SimpleNamespace(id=501)))
    reviewer = SimpleNamespace(id=56)
    cog.bot.get_user.return_value = user
    cog.bot.get_guild.return_value = g
    channel = SimpleNamespace(id=10, send=AsyncMock(return_value=SimpleNamespace(id=502)))
    g.get_channel.return_value = channel
    await cog.config.guild(g).appeal_channel.set(channel.id)
    cog._has_level_member = AsyncMock(return_value=True)
    punishment_id = await cog.record_punishment(g, user, kind, reviewer, 'Test reason', **details)
    return cog, g, user, reviewer, channel, punishment_id


@pytest.mark.asyncio
async def test_appeal_form_is_persistent_and_bound_to_user(make_cog):
    cog, g, user, _, _, case = await appeal_case(make_cog)
    await cog.offer_appeal(g, user, case)
    assert user.send.call_args.kwargs['view'].is_persistent()
    assert (await cog.config.appeal_dm_index())['501']['punishment_id'] == case
    with pytest.raises(ValueError):
        await cog.get_appealable_record(g.id, case, 99)


@pytest.mark.asyncio
async def test_submit_appeal_once_and_send_answers_to_staff(make_cog):
    cog, g, user, _, channel, case = await appeal_case(make_cog)
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'My answer')])
    embed = channel.send.call_args.kwargs['embed']
    assert embed.fields[0].value == 'My answer'
    assert channel.send.call_args.kwargs['view'].is_persistent()
    with pytest.raises(ValueError):
        await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Duplicate')])
    assert channel.send.await_count == 1


@pytest.mark.asyncio
async def test_accepted_ban_appeal_unbans_and_cancels_expiry(make_cog):
    cog, g, user, reviewer, channel, case = await appeal_case(make_cog, ban_reason='Original reason [case:123]')
    g.fetch_ban = AsyncMock(return_value=SimpleNamespace(reason='Original reason [case:123]'))
    g.unban = AsyncMock()
    await cog.config.guild(g).pending_appeals.set([dict(user_id=user.id, hold_seconds=3600)])
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    await cog.review_appeal(g, 502, reviewer, True)
    g.unban.assert_awaited_once()
    assert await cog.config.guild(g).pending_appeals() == []
    assert (await cog.config.guild(g).punishment_records())[case]['status'] == 'reverted'
    assert 'accepted' in user.send.call_args.args[0]
    with pytest.raises(ValueError):
        await cog.review_appeal(g, 502, reviewer, True)


@pytest.mark.asyncio
async def test_denied_appeal_notifies_without_reverting(make_cog):
    cog, g, user, reviewer, _, case = await appeal_case(make_cog)
    g.unban = AsyncMock()
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    await cog.review_appeal(g, 502, reviewer, False)
    g.unban.assert_not_awaited()
    assert 'denied' in user.send.call_args.args[0]
    assert (await cog.config.guild(g).punishment_records())[case]['status'] == 'active'


@pytest.mark.asyncio
async def test_old_appeal_cannot_remove_new_punishment(make_cog):
    cog, g, user, reviewer, _, case = await appeal_case(make_cog)
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    await cog.record_punishment(g, user, 'ban', reviewer, 'New reason')
    g.unban = AsyncMock()
    with pytest.raises(ValueError):
        await cog.review_appeal(g, 502, reviewer, True)
    g.unban.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_external_ban_cannot_be_removed_by_appeal(make_cog):
    cog, g, user, reviewer, _, case = await appeal_case(make_cog, ban_reason='Original')
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    g.fetch_ban = AsyncMock(return_value=SimpleNamespace(reason='Different ban'))
    g.unban = AsyncMock()
    with pytest.raises(ValueError):
        await cog.review_appeal(g, 502, reviewer, True)
    g.unban.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_warning_appeal_removes_only_matching_warning(make_cog):
    cog, g, user, reviewer, _, case = await appeal_case(make_cog, kind='warning', warning_id='first')
    await cog.config.member_from_ids(g.id, user.id).warnings.set([dict(id='first'), dict(id='second')])
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    await cog.review_appeal(g, 502, reviewer, True)
    assert await cog.config.member_from_ids(g.id, user.id).warnings() == [dict(id='second')]


@pytest.mark.asyncio
async def test_timeout_acceptance_clears_only_original_timeout(make_cog):
    until = discord.utils.utcnow() + datetime.timedelta(hours=12)
    cog, g, user, reviewer, _, case = await appeal_case(make_cog, kind='timeout', until=until.timestamp())
    member = SimpleNamespace(timed_out_until=until, timeout=AsyncMock())
    g.get_member.return_value = member
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    await cog.review_appeal(g, 502, reviewer, True)
    assert member.timeout.call_args.args == (None,)


def staff(user_id, admin=False):
    return SimpleNamespace(id=user_id, display_name=f'Staff {user_id}', mention=f'<@{user_id}>', bot=False, guild_permissions=discord.Permissions(manage_messages=True, administrator=admin))


async def claimed_ticket(make_cog):
    cog = make_cog('ticketmail.ticketmail')
    g = guild()
    members = {uid: staff(uid, admin=uid == 3) for uid in (1, 2, 3, 4)}
    for member in members.values():
        member.guild = g
        member.send = AsyncMock(return_value=SimpleNamespace(id=501))
    g.get_member.side_effect = members.get
    channel = SimpleNamespace(id=10, name='ticket', guild=g, permissions_for=lambda member: discord.Permissions.all(), send=AsyncMock(), overwrites_for=lambda member: discord.PermissionOverwrite(), set_permissions=AsyncMock())
    cog.bot.get_channel.return_value = channel
    await cog.config.channel(channel).owner_ids.set([42])
    await cog.claim_ticket(channel, members[1], True)
    return cog, channel, members


@pytest.mark.asyncio
async def test_restricted_claim_blocks_other_staff_and_admin_until_bypass(make_cog):
    cog, channel, members = await claimed_ticket(make_cog)
    assert await cog.can_reply_to_ticket(channel, members[1])
    assert not await cog.can_reply_to_ticket(channel, members[2])
    assert not await cog.can_reply_to_ticket(channel, members[3])
    await cog.bypass_claim(channel, members[3])
    assert await cog.can_reply_to_ticket(channel, members[3])
    with pytest.raises(ValueError):
        await cog.bypass_claim(channel, members[2])


@pytest.mark.asyncio
async def test_invited_staff_must_accept_before_replying(make_cog):
    cog, channel, members = await claimed_ticket(make_cog)
    await cog.invite_assignee(channel, members[1], members[2])
    assert not await cog.can_reply_to_ticket(channel, members[2])
    assert members[2].send.call_args.kwargs['view'].is_persistent()
    await cog.accept_assignee_invite(channel, 2)
    assert await cog.can_reply_to_ticket(channel, members[2])
    with pytest.raises(ValueError):
        await cog.invite_assignee(channel, members[2], members[4])


@pytest.mark.asyncio
async def test_restricted_claim_is_enforced_at_final_delivery(make_cog):
    cog, channel, members = await claimed_ticket(make_cog)
    cog.bot.get_user.return_value = SimpleNamespace(send=AsyncMock())
    assert not await cog._execute_staff_reply_action(channel, members[2], 'Not allowed', False, [])
    cog.bot.get_user.return_value.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_claims_and_invites_survive_reload(make_cog):
    cog, channel, members = await claimed_ticket(make_cog)
    await cog.invite_assignee(channel, members[1], members[2])
    await cog.restore_claim_views()
    cog.bot.add_view.assert_called_once()
    assert (await cog.config.channel(channel).all())['claimed_by'] == 1


@pytest.mark.asyncio
async def test_transcript_includes_downloadable_attachment_bytes(make_cog):
    cog = make_cog('ticketmail.ticketmail')
    g = guild()
    payload = b'Important support attachment'
    attachment = SimpleNamespace(filename='report.txt', content_type='text/plain', url='https://cdn.discordapp.com/expired', read=AsyncMock(return_value=payload))
    async def history(**kwargs):
        yield SimpleNamespace(author=SimpleNamespace(id=42, name='User', bot=False), clean_content='Attached report', created_at=discord.utils.utcnow(), attachments=[attachment], embeds=[])
    channel = SimpleNamespace(id=10, name='ticket', guild=g, history=history)
    file = await cog._generate_html_transcript(channel, 'User', 'Moderator', 'Resolved', 'G1001')
    html = file.fp.getvalue().decode()
    assert base64.b64encode(payload).decode() in html
    assert 'download="report.txt"' in html
    assert 'https://cdn.discordapp.com/expired' not in html


@pytest.mark.asyncio
async def test_unreadable_attachment_prevents_incomplete_archive(make_cog):
    from ticketmail.transcripts import TranscriptAttachmentError
    cog = make_cog('ticketmail.ticketmail')
    attachment = SimpleNamespace(filename='lost.png', read=AsyncMock(side_effect=RuntimeError('not found')))
    async def history(**kwargs):
        yield SimpleNamespace(author=SimpleNamespace(id=42, name='User', bot=False), clean_content='', created_at=discord.utils.utcnow(), attachments=[attachment], embeds=[])
    channel = SimpleNamespace(id=10, name='ticket', guild=guild(), history=history)
    with pytest.raises(TranscriptAttachmentError):
        await cog._generate_html_transcript(channel, 'User', 'Moderator', 'Resolved', 'G1001')


@pytest.mark.asyncio
async def test_invitation_revocation_restores_previous_overwrite(make_cog):
    cog, channel, members = await claimed_ticket(make_cog)
    previous = discord.PermissionOverwrite(view_channel=False, send_messages=False)
    channel.overwrites_for = lambda member: previous
    await cog.invite_assignee(channel, members[1], members[2])
    await cog.accept_assignee_invite(channel, 2)
    assert channel.set_permissions.call_args.kwargs['overwrite'].view_channel is True
    await cog.remove_assignee(channel, members[1], members[2])
    restored = channel.set_permissions.call_args.kwargs['overwrite']
    assert restored.view_channel is False and restored.send_messages is False
    assert not await cog.can_reply_to_ticket(channel, members[2])


@pytest.mark.asyncio
async def test_claimant_can_reopen_staff_replies(make_cog):
    cog, channel, members = await claimed_ticket(make_cog)
    with pytest.raises(ValueError):
        await cog.claim_ticket(channel, members[2], False)
    await cog.claim_ticket(channel, members[1], False)
    assert await cog.can_reply_to_ticket(channel, members[2])


@pytest.mark.asyncio
async def test_failed_reversal_leaves_appeal_pending(make_cog):
    cog, g, user, reviewer, _, case = await appeal_case(make_cog, ban_reason='Original')
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    g.fetch_ban = AsyncMock(return_value=SimpleNamespace(reason='Original'))
    g.unban = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'denied'))
    with pytest.raises(discord.Forbidden):
        await cog.review_appeal(g, 502, reviewer, True)
    assert (await cog.config.guild(g).appeal_requests())[case]['status'] == 'pending'
    assert (await cog.config.guild(g).punishment_records())[case]['status'] == 'active'


@pytest.mark.asyncio
async def test_simultaneous_review_only_reverses_once(make_cog):
    cog, g, user, reviewer, _, case = await appeal_case(make_cog, ban_reason='Original')
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    g.fetch_ban = AsyncMock(return_value=SimpleNamespace(reason='Original'))
    g.unban = AsyncMock()
    results = await asyncio.gather(cog.review_appeal(g, 502, reviewer, True), cog.review_appeal(g, 502, reviewer, True), return_exceptions=True)
    assert sum(isinstance(value, ValueError) for value in results) == 1
    g.unban.assert_awaited_once()


@pytest.mark.asyncio
async def test_changed_timeout_is_not_cleared(make_cog):
    until = discord.utils.utcnow() + datetime.timedelta(hours=12)
    cog, g, user, reviewer, _, case = await appeal_case(make_cog, kind='timeout', until=until.timestamp())
    member = SimpleNamespace(timed_out_until=until + datetime.timedelta(hours=1), timeout=AsyncMock())
    g.get_member.return_value = member
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    with pytest.raises(ValueError):
        await cog.review_appeal(g, 502, reviewer, True)
    member.timeout.assert_not_awaited()


@pytest.mark.asyncio
async def test_kick_acceptance_sends_single_use_rejoin_invite(make_cog):
    cog, g, user, reviewer, channel, case = await appeal_case(make_cog, kind='kick')
    g.fetch_ban = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason='Not found'), 'not banned'))
    channel.create_invite = AsyncMock(return_value=SimpleNamespace(url='https://discord.gg/example'))
    await cog.config.guild(g).appeal_rejoin_channel.set(channel.id)
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    await cog.review_appeal(g, 502, reviewer, True)
    assert channel.create_invite.call_args.kwargs['max_uses'] == 1
    assert 'https://discord.gg/example' in user.send.call_args.args[0]


@pytest.mark.asyncio
async def test_non_staff_cannot_review_appeals(make_cog):
    from AdvancedMod.appeals import AppealReviewView
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level_member = AsyncMock(return_value=False)
    cog.review_appeal = AsyncMock()
    view = AppealReviewView(cog)
    await view.decide(interaction(guild()), True)
    cog.review_appeal.assert_not_awaited()


@pytest.mark.asyncio
async def test_mislabeled_image_is_a_download_instead_of_broken_preview():
    from ticketmail.transcripts import attachment_card
    attachment = SimpleNamespace(filename='example.png', content_type='image/png', read=AsyncMock(return_value=b'Not an image'))
    html = await attachment_card(attachment)
    assert '<img' not in html and 'download="example.png"' in html


@pytest.mark.asyncio
async def test_unappealable_ban_still_requires_manager(make_cog):
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level = AsyncMock(side_effect=lambda ctx, level: level <= 3)
    cog._is_allowed_to_moderate = AsyncMock(return_value=(True, ''))
    cog._process_ban = AsyncMock()
    ctx = SimpleNamespace(send=AsyncMock())
    await cog.ban.callback(cog, ctx, SimpleNamespace(id=42), 'Reason', '6mo', False, 'https://example.com/proof')
    cog._process_ban.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_ban_accepts_custom_minutes(make_cog):
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level = AsyncMock(return_value=True)
    cog._is_allowed_to_moderate = AsyncMock(return_value=(True, ''))
    cog._process_ban = AsyncMock()
    ctx = SimpleNamespace(guild=guild(), author=staff(1), send=AsyncMock())
    await cog.ban.callback(cog, ctx, SimpleNamespace(id=42), 'Reason', '30 minutes', True, 'https://example.com/proof')
    assert cog._process_ban.call_args.kwargs['temp_duration'] == 1800


@pytest.mark.asyncio
async def test_modlog_uses_exact_custom_duration(make_cog, monkeypatch):
    import importlib
    module = importlib.import_module('AdvancedMod.advmod')
    create_case = AsyncMock()
    monkeypatch.setattr(module.modlog, 'create_case', create_case)
    cog = make_cog('AdvancedMod.advmod')
    before = discord.utils.utcnow()
    await cog.log_immediate_action(guild(), 'Tempban', SimpleNamespace(id=42), staff(1), 'Reason', 'None Provided', duration_seconds=1800)
    difference = (create_case.call_args.kwargs['until'] - before).total_seconds()
    assert 1799 <= difference <= 1802


@pytest.mark.asyncio
@pytest.mark.parametrize('accepted,level,allowed', [(True, 3, False), (True, 4, True), (True, 5, True), (False, 3, True), (False, 2, False)])
async def test_manager_clearance_for_appeal_acceptance(make_cog, accepted, level, allowed):
    from AdvancedMod.appeals import AppealReviewView
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level_member = AsyncMock(side_effect=lambda guild, user, required: level >= required)
    cog.review_appeal = AsyncMock(return_value='Saved')
    view = AppealReviewView(cog)
    i = interaction(guild())
    i.user.mention = '<@42>'
    await view.decide(i, accepted)
    assert cog.review_appeal.await_count == int(allowed)


@pytest.mark.asyncio
async def test_service_rejects_class_three_acceptance(make_cog):
    cog, g, user, reviewer, _, case = await appeal_case(make_cog, ban_reason='Original')
    await cog.submit_appeal(g.id, case, user.id, [('Why?', 'Answer')])
    cog._has_level_member = AsyncMock(side_effect=lambda guild, user, required: required <= 3)
    g.unban = AsyncMock()
    with pytest.raises(ValueError, match='Manager'):
        await cog.review_appeal(g, 502, reviewer, True)
    g.unban.assert_not_awaited()
    assert (await cog.config.guild(g).appeal_requests())[case]['status'] == 'pending'
