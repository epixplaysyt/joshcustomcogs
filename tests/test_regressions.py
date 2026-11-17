import asyncio
import datetime
import importlib
import io
import sys
import uuid
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord.ext import tasks
from redbot.core._drivers.json import JsonDriver

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COGS = {
    'AdvancedMod.advmod': 'AdvancedMod', 'appreader.appreader': 'ScoreMailer',
    'autorole.roleautomation': 'RoleAutomation', 'components.compsender': 'JsonEmbeds',
    'dmutils.dmutils': 'DMUtils', 'dynaboard.dynaboard': 'InfoBoard',
    'eventboard.eventboard': 'EventBoard', 'guesses.guesses': 'Guesses',
    'ltl.ltl': 'LastToLeave', 'prizelogger.prizelogger': 'PayoutTracker',
    'quotatracker.quotatracker': 'QuotaTracker', 'rblxaudit.audit_logger': 'AuditLogger',
    'reporter.reporter': 'MessageReporter', 'serverguard.serverguard': 'ServerGuard',
    'textpurge.textpurge': 'TextPurge', 'ticketmail.ticketmail': 'Modmail',
    'wordle.wordle': 'TransportWordle',
}


@pytest.fixture
def make_cog(monkeypatch, tmp_path):
    config_module = importlib.import_module('redbot.core.config')
    monkeypatch.setattr(config_module, '_config_cache', weakref.WeakValueDictionary())
    def driver(name, identifier, **kwargs):
        unique = name + uuid.uuid4().hex
        return JsonDriver(unique, identifier, data_path_override=tmp_path / unique)
    monkeypatch.setattr(config_module, 'get_driver', driver)
    monkeypatch.setattr(tasks.Loop, 'start', lambda *args, **kwargs: None)
    def create(module):
        bot = SimpleNamespace(
            get_user=Mock(return_value=None), fetch_user=AsyncMock(), get_guild=Mock(),
            get_channel=Mock(return_value=None), guilds=[], users=[], owner_ids=set(),
            is_owner=AsyncMock(return_value=False), is_admin=AsyncMock(return_value=False),
            add_view=Mock(), user=SimpleNamespace(id=999, name='Bot', display_avatar=SimpleNamespace(url='https://example.com/avatar.png')),
        )
        return getattr(importlib.import_module(module), COGS[module])(bot)
    return create


def guild(guild_id=1):
    return SimpleNamespace(id=guild_id, name='Test', icon=None, me=Mock(), default_role=Mock(), get_role=Mock(return_value=None), get_member=Mock(return_value=None), get_channel=Mock(return_value=None))


def interaction(g=None, allowed=False):
    return SimpleNamespace(guild=g, guild_id=g.id if g else None, permissions=discord.Permissions(manage_messages=allowed), user=SimpleNamespace(id=42), response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), edit_message=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()), message=SimpleNamespace(id=123, edit=AsyncMock()))


@pytest.mark.asyncio
@pytest.mark.parametrize('module', COGS)
async def test_cog_import_and_construction(make_cog, module):
    cog = make_cog(module)
    assert cog.qualified_name
    if hasattr(cog, 'session'):
        await cog.session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('allowed,expected', [(False, False), (True, True)])
async def test_ticket_staff_permissions(make_cog, allowed, expected):
    cog = make_cog('ticketmail.ticketmail')
    await cog.config.default_guild_id.set(1)
    assert await cog._check_staff_interaction(interaction(guild(), allowed)) is expected
    assert not await cog._check_staff_interaction(interaction(guild(2), True))
    assert not await cog._check_staff_interaction(interaction(None, True))
    assert cog.ticket_group.default_permissions.view_channel


@pytest.mark.asyncio
async def test_ticket_overwrites_deny_public_access(make_cog):
    cog = make_cog('ticketmail.ticketmail')
    g = guild()
    overwrites = cog._ticket_overwrites(g, None)
    assert overwrites[g.default_role].view_channel is False
    assert overwrites[g.me].view_channel is True


@pytest.mark.asyncio
async def test_transcript_escapes_message_and_metadata(make_cog):
    cog = make_cog('ticketmail.ticketmail')
    g = guild()
    async def history(**kwargs):
        yield SimpleNamespace(author=SimpleNamespace(id=42, name='<b>User</b>', bot=False, display_avatar=SimpleNamespace(url='https://example.com/avatar.png')), clean_content='<script>alert(1)</script>', created_at=discord.utils.utcnow(), attachments=[], embeds=[])
    channel = SimpleNamespace(id=10, guild=g, name='<b>Channel</b>', history=history)
    file = await cog._generate_html_transcript(channel, '<b>User</b>', 'Staff', '<img src=x onerror=alert(1)>', 'G1001')
    html = file.fp.getvalue().decode()
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '<b>Channel</b>' not in html
    assert '&lt;img src=x onerror=alert(1)&gt;' in html


@pytest.mark.asyncio
@pytest.mark.parametrize('private', [False, True])
async def test_failed_archive_preserves_ticket(make_cog, private):
    cog = make_cog('ticketmail.ticketmail')
    async def history(**kwargs):
        if False:
            yield None
    channel = SimpleNamespace(id=10, name='ticket', guild=guild(), created_at=discord.utils.utcnow(), send=AsyncMock(), delete=AsyncMock(), history=history)
    await cog.config.channel(channel).owner_ids.set([42])
    cog._generate_html_transcript = AsyncMock(return_value=discord.File(io.BytesIO(b'test'), filename='transcript.html'))
    assert not await cog._execute_close(channel, 'test', False, 42, private)
    channel.delete.assert_not_awaited()
    assert await cog.config.channel(channel).owner_ids() == [42]


@pytest.mark.asyncio
@pytest.mark.parametrize('duration,appealable', [(3600, True), (14 * 86400, True), (3600, False)])
async def test_tempban_expires_without_appeal_link(make_cog, duration, appealable):
    cog = make_cog('AdvancedMod.advmod')
    g = guild()
    g.unban = AsyncMock()
    cog.bot.get_guild.return_value = g
    cog.bot.get_user.return_value = SimpleNamespace(id=42)
    await cog.config.guild(g).pending_appeals.set([dict(user_id=42, timestamp=0, hold_seconds=duration, hold_days=14, appealable=appealable)])
    await cog.appeal_notifier.coro(cog)
    g.unban.assert_awaited_once()
    assert await cog.config.guild(g).pending_appeals() == []


@pytest.mark.asyncio
async def test_permanent_ban_is_not_expired(make_cog):
    cog = make_cog('AdvancedMod.advmod')
    g = guild()
    g.unban = AsyncMock()
    cog.bot.get_guild.return_value = g
    cog.bot.get_user.return_value = SimpleNamespace(id=42)
    await cog.config.guild(g).pending_appeals.set([dict(user_id=42, timestamp=0, hold_seconds=0, hold_days=14)])
    await cog.appeal_notifier.coro(cog)
    g.unban.assert_not_awaited()


@pytest.mark.asyncio
async def test_sorted_application_vote_targets_displayed_candidate(make_cog):
    from appreader.appreader import AppReaderView
    cog = make_cog('appreader.appreader')
    apps = [dict(application_id=str(i), discord_username=name, total_score=str(i), votes=[], q_and_a=[]) for i, name in enumerate(['Low', 'High'])]
    g = guild()
    await cog.config.guild(g).departments.set({'test': {'apps': apps, 'max_candidates': 1}})
    ctx = SimpleNamespace(guild=g, author=SimpleNamespace(id=42))
    view = AppReaderView('test', list(reversed(apps)), ctx, cog)
    i = interaction(g)
    i.user = ctx.author
    await view.vote_button(i)
    stored = (await cog.config.guild(g).departments())['test']['apps']
    assert stored[0]['votes'] == []
    assert stored[1]['votes'] == [42]
    assert view.applications[0]['discord_username'] == 'High'


@pytest.mark.asyncio
async def test_long_application_pages_fit_embeds(make_cog):
    from appreader.appreader import AppReaderView
    cog = make_cog('appreader.appreader')
    apps = [dict(discord_username='User', votes=[], q_and_a=[dict(question='Q', answer='x' * 13000)])]
    view = AppReaderView('test', apps, SimpleNamespace(author=SimpleNamespace(id=42)), cog)
    pages = view.get_app_pages()
    assert all(len(page) <= 3900 for page in pages)
    assert ''.join(pages).count('x') == 13000


@pytest.mark.asyncio
async def test_payout_replacement_has_no_nested_lock(make_cog):
    cog = make_cog('prizelogger.prizelogger')
    user = SimpleNamespace(id=42, create_dm=AsyncMock(), send=AsyncMock(return_value=SimpleNamespace(id=12, channel=SimpleNamespace(id=13))))
    cog.bot.get_user.return_value = user
    record = dict(user_id=42, message_id=None, channel_id=None)
    async with cog.config.tracked_tasks() as tracked:
        updated = await asyncio.wait_for(cog.update_user_embed(record, 'Logged', None), 1)
        tracked['task'] = updated
    assert (await cog.config.tracked_tasks())['task']['message_id'] == 12
    assert cog.determine_display_status('PAID OUT', '1794902400000') == 'Paid out'
    assert '<t:' in cog.build_embed('Scheduled', 'User', '100', 'Gift', '1794902400000').fields[1].value


@pytest.mark.asyncio
async def test_dynamic_board_persistence_and_builder_owner(make_cog):
    from dynaboard.dynaboard import DynamicBoardView, BuilderActionView
    cog = make_cog('dynaboard.dynaboard')
    assert DynamicBoardView({'Test': {'description': 'Test'}}, cog).is_persistent()
    view = BuilderActionView(cog, SimpleNamespace(author=SimpleNamespace(id=99)))
    assert not await view.interaction_check(interaction(guild(), True))


@pytest.mark.asyncio
async def test_guess_approval_timeout_releases_pending_request(make_cog):
    from guesses.guesses import ManagerApprovalView
    cog = make_cog('guesses.guesses')
    g = guild()
    cog.pending_requests.add(g.id)
    view = ManagerApprovalView(cog, interaction(g), Mock(), 'answer', True, 120, 30)
    await view.on_timeout()
    assert g.id not in cog.pending_requests


@pytest.mark.asyncio
async def test_guess_restart_restores_active_session(make_cog):
    cog = make_cog('guesses.guesses')
    await cog.config.guild(guild()).active_session.set(dict(answer='answer', auto_mark=True, regular_cd=120, winner_cd=30))
    await cog.cog_load()
    assert cog.is_active and cog.session_answer == 'answer'
