from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from test_regressions import make_cog, guild, interaction


async def setup_session(make_cog):
    cog = make_cog('guesses.guesses')
    g = guild()
    channel = SimpleNamespace(id=10, overwrites_for=lambda role: discord.PermissionOverwrite(), set_permissions=AsyncMock(), send=AsyncMock())
    g.get_channel.return_value = channel
    await cog.config.guild(g).guess_channel_id.set(channel.id)
    cog.bot.get_context = AsyncMock(return_value=SimpleNamespace(valid=False))
    await cog._open_guessing_channel(g, channel, 'train', True, 120, 30)
    return cog, g, channel


def guess_message(g, channel, text, user_id=42):
    return SimpleNamespace(guild=g, channel=channel, content=text, author=SimpleNamespace(id=user_id, bot=False, roles=[], premium_since=None, mention=f'<@{user_id}>'), add_reaction=AsyncMock(), delete=AsyncMock())


@pytest.mark.asyncio
async def test_manual_close_reads_saved_session_and_clears_it(make_cog):
    cog, g, channel = await setup_session(make_cog)
    i = interaction(g)
    i.user = SimpleNamespace(roles=[], guild_permissions=discord.Permissions(administrator=True))
    assert (await cog.config.guild(g).all())['active_session']['answer'] == 'train'
    await cog.guessclose.callback(cog, i)
    assert not cog.is_active
    assert (await cog.config.guild(g).all())['active_session'] == {}
    assert channel.set_permissions.call_args.kwargs['overwrite'].send_messages is False
    assert 'train' in channel.send.call_args.kwargs['embed'].description
    assert 'successfully' in i.followup.send.call_args.args[0]
    await cog.cog_load()
    assert not cog.is_active


@pytest.mark.asyncio
async def test_automark_reacts_and_closes_on_correct_guess_after_restore(make_cog):
    cog, g, channel = await setup_session(make_cog)
    cog.is_active = False
    cog.session_answer = ''
    await cog.cog_load()
    wrong = guess_message(g, channel, 'bicycle')
    await cog.on_message(wrong)
    wrong.add_reaction.assert_awaited_once_with('❌')
    assert cog.is_active
    correct = guess_message(g, channel, 'TRAIN', user_id=43)
    await cog.on_message(correct)
    correct.add_reaction.assert_awaited_once_with('✅')
    assert not cog.is_active
    assert (await cog.config.guild(g).all())['active_session'] == {}
    assert '<@43>' in channel.send.call_args.kwargs['embed'].description
    assert channel.set_permissions.call_args.kwargs['overwrite'].send_messages is False


@pytest.mark.asyncio
async def test_legacy_closed_none_can_be_read_and_reopened(make_cog):
    cog = make_cog('guesses.guesses')
    g = guild()
    await cog.config.guild(g).set_raw("active_session", value=None)
    await cog.config.guild(g).role_host.set(12)
    assert (await cog.config.guild(g).all())['active_session'] is None
    await cog.cog_load()
    assert not cog.is_active
    await cog.config.guild(g).active_session.set({'answer': 'legacy', 'auto_mark': True, 'regular_cd': 120, 'winner_cd': 30})
    await cog.cog_load()
    assert cog.is_active and cog.session_answer == 'legacy'
    assert (await cog.config.guild(g).all())['role_host'] == 12
