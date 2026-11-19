import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from redbot.core import commands

from test_regressions import make_cog, guild
from modmailerviewer.setup import guided_setup


def setup_context():
    g = guild()
    channel = SimpleNamespace(id=10, guild=g, mention='<#10>', permissions_for=lambda user: discord.Permissions(view_channel=True, read_message_history=True))
    ctx = SimpleNamespace(guild=g, channel=SimpleNamespace(id=7), author=SimpleNamespace(id=42), clean_prefix='!', send=AsyncMock())
    return ctx, channel


def prepare_wizard(cog, ctx, channel, replies, monkeypatch):
    monkeypatch.setattr(commands.TextChannelConverter, 'convert', AsyncMock(return_value=channel))
    replies = iter(replies)
    async def wait_for(event, timeout, check):
        assert event == 'message' and timeout == 180
        assert not check(SimpleNamespace(author=SimpleNamespace(id=99), channel=ctx.channel))
        assert not check(SimpleNamespace(author=ctx.author, channel=SimpleNamespace(id=8)))
        message = SimpleNamespace(author=ctx.author, channel=ctx.channel, content=next(replies))
        assert check(message)
        return message
    cog.bot.wait_for = wait_for
    cog.bot.get_shared_api_tokens = AsyncMock(return_value={'client_id': '123', 'client_secret': 'never-print-this'})
    cog.start_server = AsyncMock()
    monkeypatch.setattr(cog.expiry_loop, 'restart', Mock())


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,url,host', [('1', 'http://localhost:8088', '127.0.0.1'), ('1', 'http://[::1]:8088', '::1'), ('2', 'http://203.0.113.10:8088', '0.0.0.0'), ('3', 'https://tickets.example.com', '127.0.0.1')])
async def test_guided_setup_all_hosting_modes(make_cog, monkeypatch, mode, url, host):
    cog = make_cog('modmailerviewer.viewer')
    ctx, channel = setup_context()
    prepare_wizard(cog, ctx, channel, ['10', mode, '8088', url, 'ready', 'yes'], monkeypatch)
    await cog.configure.callback(cog, ctx)
    settings = await cog.config.all()
    assert settings['public_url'] == url and settings['archive_channel'] == 10
    assert settings['host'] == host and settings['allow_http'] == (mode == '2')
    cog.start_server.assert_awaited_once()
    messages = '\n'.join(call.args[0] for call in ctx.send.call_args_list)
    assert url + '/oauth/callback' in messages
    assert '!set api modmailerviewer' in messages
    assert 'never-print-this' not in messages
    assert not cog._setup_running


@pytest.mark.asyncio
@pytest.mark.parametrize('stop', ['cancel', 'timeout'])
async def test_setup_cancel_or_timeout_preserves_settings(make_cog, stop):
    cog = make_cog('modmailerviewer.viewer')
    ctx, _ = setup_context()
    before = await cog.config.all()
    cog.bot.wait_for = AsyncMock(side_effect=asyncio.TimeoutError()) if stop == 'timeout' else AsyncMock(return_value=SimpleNamespace(content='cancel'))
    await guided_setup(cog, ctx)
    assert await cog.config.all() == before and not cog._setup_running
    assert 'cancelled' in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_wizard_retries_invalid_inputs_and_missing_credentials(make_cog, monkeypatch):
    cog = make_cog('modmailerviewer.viewer')
    ctx, channel = setup_context()
    prepare_wizard(cog, ctx, channel, ['10', 'invalid', '2', '99999', '8088', 'http://example.com', 'http://203.0.113.10:9999', 'http://203.0.113.10:8088', 'ready', 'ready', 'no'], monkeypatch)
    cog.bot.get_shared_api_tokens = AsyncMock(side_effect=[{}, {'client_id': '1', 'client_secret': '2'}])
    await guided_setup(cog, ctx)
    assert not await cog.config.public_url()
    cog.start_server.assert_not_awaited()
    assert cog.bot.get_shared_api_tokens.await_count == 2


@pytest.mark.asyncio
async def test_bind_failure_restores_previous_settings(make_cog):
    cog = make_cog('modmailerviewer.viewer')
    ctx, channel = setup_context()
    before = await cog.config.all()
    cog.start_server = AsyncMock(side_effect=OSError('Address in use'))
    result = await cog.configure.callback(cog, ctx, channel, 'http://localhost:8088')
    assert result is False and await cog.config.all() == before
    assert 'Previous settings were restored' in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_setup_group_rejects_nonowner(make_cog):
    cog = make_cog('modmailerviewer.viewer')
    ctx, _ = setup_context()
    ctx.bot = cog.bot
    cog.viewerset.requires.ready_event.set()
    ctx.cog = None
    ctx.bot_permissions = discord.Permissions.all()
    assert await cog.viewerset.requires.verify(ctx) is False
    cog.bot.is_owner.return_value = True
    assert await cog.viewerset.requires.verify(ctx) is True


@pytest.mark.asyncio
async def test_only_one_wizard_can_run(make_cog):
    cog = make_cog('modmailerviewer.viewer')
    ctx, _ = setup_context()
    cog._setup_running = True
    await guided_setup(cog, ctx)
    assert 'already running' in ctx.send.call_args.args[0]
