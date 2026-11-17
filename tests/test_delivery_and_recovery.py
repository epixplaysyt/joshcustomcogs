import asyncio
import datetime
import importlib
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from test_regressions import COGS, guild, interaction, make_cog


@pytest.mark.asyncio
async def test_all_extensions_load_in_red(make_cog, monkeypatch, tmp_path):
    from redbot.core.bot import Red
    from redbot.core._cli import parse_cli_flags
    from redbot.core import data_manager
    monkeypatch.setattr(data_manager, 'basic_config', {'DATA_PATH': str(tmp_path), 'COG_PATH_APPEND': 'cogs', 'CORE_PATH_APPEND': 'core', 'STORAGE_TYPE': 'JSON', 'STORAGE_DETAILS': {}})
    bot = Red(cli_flags=parse_cli_flags([]))
    await bot._async_setup_hook()
    try:
        for module in COGS:
            await bot.load_extension(importlib.util.find_spec(module.split('.')[0]))
        assert len(bot.cogs) == len(COGS)
        assert 'modmail' in bot.tree._disabled_global_commands
        assert 'guessopen' in bot.tree._disabled_global_commands
    finally:
        for module in reversed(COGS):
            if module.split('.')[0] in bot.extensions:
                await bot.unload_extension(module.split('.')[0])
        await bot.http.close()


@pytest.mark.asyncio
async def test_event_schedule_fits_discord_limits(make_cog, monkeypatch):
    cog = make_cog('eventboard.eventboard')
    events = [dict(name='An ordinary event', date='2030-01-01T12:00:00Z', type=dict(category='events', description='A community event with enough description to fill a realistic schedule.')) for _ in range(8)]
    class Response:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def json(self): return {'sessions': events}
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr(importlib.import_module('eventboard.eventboard').aiohttp, 'ClientSession', Session)
    g = guild()
    channel = SimpleNamespace(permissions_for=lambda m: discord.Permissions.all(), send=AsyncMock(return_value=SimpleNamespace(id=2)))
    g.get_channel.return_value = channel
    await cog.config.guild(g).channel_id.set(10)
    await cog.config.guild(g).api_url.set('https://example.com/events')
    success, _ = await cog._run_board_update(g)
    assert success
    embed = channel.send.call_args.kwargs['embed']
    assert all(len(field.value) <= 1024 for field in embed.fields)
    assert len(embed) <= 6000


@pytest.mark.asyncio
async def test_ticket_migration_copies_more_than_fifty_messages(make_cog):
    cog = make_cog('ticketmail.ticketmail')
    old, new = guild(), guild(2)
    async def history(**kwargs):
        assert kwargs['limit'] is None
        for index in range(150):
            yield SimpleNamespace(author=cog.bot.user, content=str(index), embeds=[], attachments=[])
    source = SimpleNamespace(id=10, name='ticket', history=history, delete=AsyncMock())
    destination = SimpleNamespace(id=11, send=AsyncMock(), delete=AsyncMock())
    old.text_channels = [source]
    new.create_text_channel = AsyncMock(return_value=destination)
    await cog.config.channel(source).owner_ids.set([42])
    cog._generate_html_transcript = AsyncMock(return_value=discord.File(io.BytesIO(b'test'), filename='transcript.html'))
    await cog._migrate_tickets_to_new_guild(old, new)
    assert destination.send.await_count == 151
    source.delete.assert_awaited_once()
    assert await cog.config.user_from_id(42).active_channel_id() == destination.id


@pytest.mark.asyncio
async def test_ticket_migration_preserves_source_on_copy_failure(make_cog):
    cog = make_cog('ticketmail.ticketmail')
    old, new = guild(), guild(2)
    async def history(**kwargs):
        yield SimpleNamespace(author=cog.bot.user, content='test', embeds=[], attachments=[])
    source = SimpleNamespace(id=10, name='ticket', history=history, delete=AsyncMock())
    destination = SimpleNamespace(id=11, send=AsyncMock(side_effect=RuntimeError('delivery failed')), delete=AsyncMock())
    old.text_channels = [source]
    new.create_text_channel = AsyncMock(return_value=destination)
    await cog.config.channel(source).owner_ids.set([42])
    await cog.config.user_from_id(42).active_channel_id.set(source.id)
    with pytest.raises(RuntimeError):
        await cog._migrate_tickets_to_new_guild(old, new)
    source.delete.assert_not_awaited()
    assert await cog.config.user_from_id(42).active_channel_id() == source.id


@pytest.mark.asyncio
async def test_anonymous_ticket_reply_has_no_staff_profile_link(make_cog):
    cog = make_cog('ticketmail.ticketmail')
    g = guild()
    channel = SimpleNamespace(id=10, guild=g, send=AsyncMock(), permissions_for=lambda member: discord.Permissions.all())
    await cog.config.channel(channel).owner_ids.set([42])
    user = SimpleNamespace(send=AsyncMock())
    cog.bot.get_user.return_value = user
    author = SimpleNamespace(id=56, display_name='Moderator', display_avatar=SimpleNamespace(url='https://example.com/avatar.png'))
    g.get_member.return_value = SimpleNamespace(id=56, display_name='Moderator', top_role=SimpleNamespace(name='Staff'), guild_permissions=discord.Permissions(manage_messages=True))
    await cog._execute_staff_reply_action(channel, author, 'test', True, [])
    embed = user.send.call_args.kwargs['embed']
    assert embed.author.name == 'Support Team'
    assert not embed.author.url
    assert str(author.id) not in str(embed.to_dict())


@pytest.mark.asyncio
async def test_newcomer_does_not_count_as_last_to_leave_winner(make_cog):
    cog = make_cog('ltl.ltl')
    g = guild()
    role, host = Mock(), Mock()
    g.get_role.side_effect = lambda rid: role if rid == 1 else host
    announcement = SimpleNamespace(send=AsyncMock())
    g.get_channel.return_value = announcement
    member = SimpleNamespace(guild=g, roles=[role], remove_roles=AsyncMock(), name='Leaving')
    participant = SimpleNamespace(roles=[role], mention='<@43>', bot=False, remove_roles=AsyncMock())
    newcomer = SimpleNamespace(roles=[], bot=False)
    vc = SimpleNamespace(id=10, members=[participant, newcomer])
    await cog.config.guild(g).set(dict(is_active=True, vc_id=10, participant_role_id=1, host_role_id=2, announce_channel_id=11))
    await cog.on_voice_state_update(member, SimpleNamespace(channel=vc), SimpleNamespace(channel=None))
    assert not await cog.config.guild(g).is_active()
    assert announcement.send.await_count == 2


@pytest.mark.asyncio
async def test_failed_replacement_role_preserves_trigger_role(make_cog):
    cog = make_cog('autorole.roleautomation')
    g = guild()
    trigger = SimpleNamespace(id=1)
    g.get_role.return_value = Mock()
    await cog.config.guild(g).trigger_role.set(1)
    await cog.config.guild(g).replacement_role.set(2)
    member = SimpleNamespace(guild=g, roles=[trigger], add_roles=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'denied')), remove_roles=AsyncMock())
    await cog.on_member_update(SimpleNamespace(roles=[]), member)
    member.remove_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_plain_stop_closes_dm_conversation(make_cog):
    cog = make_cog('dmutils.dmutils')
    author = SimpleNamespace(id=42)
    ctx = SimpleNamespace(author=author, send=AsyncMock())
    cog.bot.get_context = AsyncMock(return_value=ctx)
    cog.active_conversations[42] = dict(staff_id=56, conversation_id='M1')
    await cog.on_message(SimpleNamespace(guild=None, author=SimpleNamespace(id=42, bot=False), content='stop'))
    assert 42 not in cog.active_conversations


@pytest.mark.asyncio
async def test_wordle_old_button_starts_today_instead_of_reusing_completion(make_cog):
    cog = make_cog('wordle.wordle')
    g = guild()
    user = SimpleNamespace(id=42)
    cog.bot.get_user.return_value = user
    cog.bot.get_guild.return_value = g
    await cog.config.guild(g).secret_word.set('METRO')
    await cog.config.guild(g).validate_word.set(False)
    await cog.config.user(user).date.set('2000-01-01')
    await cog.config.user(user).completed.set(True)
    i = interaction(g)
    await cog.process_guess(i, 42, 'TRAIN')
    data = await cog.config.user(user).all()
    assert data['date'] == cog.get_today_string()
    assert data['guesses'] == ['TRAIN']
    assert data['start_time'] is not None


@pytest.mark.asyncio
async def test_concurrent_quota_messages_are_not_lost(make_cog):
    cog = make_cog('quotatracker.quotatracker')
    g = guild()
    author = SimpleNamespace(id=42, guild=g, bot=False)
    await cog.config.main_guild_id.set(g.id)
    await cog.config.guild(g).departments.set({'test': {'quota': 1000}})
    await cog.config.member(author).department.set('test')
    message = SimpleNamespace(guild=g, author=author)
    await asyncio.gather(*(cog.on_message(message) for _ in range(30)))
    assert await cog.config.member(author).message_count() == 30


@pytest.mark.asyncio
async def test_strict_ban_review_requires_director(make_cog):
    from AdvancedMod.advmod import DynamicRequestView
    cog = make_cog('AdvancedMod.advmod')
    g = guild()
    await cog.config.guild(g).active_requests.set({'request': dict(message_id=123, type='director review (strict ban)', target=42, reason='test', proof='None Provided', author=56)})
    cog._has_level_member = AsyncMock(side_effect=lambda g, m, level: level <= 3)
    cog._process_ban = AsyncMock()
    view = DynamicRequestView(cog)
    i = interaction(g)
    await view.approve_button.callback(i)
    assert cog._has_level_member.call_args.args[2] == 5
    cog._process_ban.assert_not_awaited()
    i.response.defer.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_ban_override_keeps_original_expiry(make_cog):
    cog = make_cog('AdvancedMod.advmod')
    g = guild()
    g.ban = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'denied'))
    target = SimpleNamespace(id=42, mention='<@42>')
    record = dict(user_id=42, timestamp=100, hold_seconds=3600)
    await cog.config.guild(g).pending_appeals.set([record])
    cog._dm_user = AsyncMock()
    with pytest.raises(discord.Forbidden):
        await cog._execute_ban_action(g, target, SimpleNamespace(id=56), 'test', 'None Provided', False, is_override=True)
    assert await cog.config.guild(g).pending_appeals() == [record]


@pytest.mark.asyncio
async def test_raw_json_cannot_override_mention_restrictions(make_cog):
    cog = make_cog('components.compsender')
    cog.bot.http = SimpleNamespace(request=AsyncMock())
    ctx = SimpleNamespace(channel=SimpleNamespace(id=10), message=SimpleNamespace(add_reaction=AsyncMock()), send=AsyncMock())
    await cog.sendjson.callback(cog, ctx, json_data='{"content":"@everyone", "allowed_mentions":{"parse":["everyone"]}}')
    payload = cog.bot.http.request.call_args.kwargs['json']
    assert payload['allowed_mentions']['parse'] == []
