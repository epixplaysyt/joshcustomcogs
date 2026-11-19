import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from PIL import Image

from test_regressions import make_cog, guild
from AdvancedMod.evidence import prepare_proof_delivery, add_proof_field, MAX_IMAGE


@pytest.mark.asyncio
@pytest.mark.parametrize('path,label', [('1/2/3', 'Message'), ('1/2', 'Channel')])
async def test_discord_links_have_channel_and_server_context(path, label):
    url = f'https://discord.com/channels/{path}'
    display, file = await prepare_proof_delivery(url)
    assert f'[{label}]({url})' in display and '<#2>' in display and 'server `1`' in display
    assert file is None


@pytest.mark.asyncio
async def test_external_image_preview_does_not_fetch_arbitrary_hosts(monkeypatch):
    session = Mock(side_effect=AssertionError('Unexpected network access'))
    monkeypatch.setattr('AdvancedMod.evidence.aiohttp.ClientSession', session)
    url = 'https://example.com/image.PNG?signature=abc'
    display, file = await prepare_proof_delivery(url)
    embed = discord.Embed()
    add_proof_field(embed, url, display, file)
    assert embed.image.url == url
    session.assert_not_called()
    display, file = await prepare_proof_delivery('https://discord.com.attacker.example/channels/1/2/3')
    assert '<#2>' not in display


@pytest.mark.asyncio
async def test_discord_image_is_uploaded_and_embedded_with_signed_url(monkeypatch):
    data = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(data, format='PNG')
    class Content:
        async def iter_chunked(self, size):
            yield data.getvalue()
    class Response:
        status = 200
        content_length = len(data.getvalue())
        content = Content()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Session:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            assert kwargs['allow_redirects'] is False
            return Response()
    monkeypatch.setattr('AdvancedMod.evidence.aiohttp.ClientSession', Session)
    for name in ['photo.png?ex=abc&hm=def', 'no-extension?ex=abc']:
        proof = 'https://cdn.discordapp.com/attachments/1/2/' + name
        display, file = await prepare_proof_delivery(proof)
        assert file.filename == 'evidence.png'
        embed = discord.Embed()
        add_proof_field(embed, proof, display, file)
        assert embed.image.url == 'attachment://evidence.png'
        assert proof in embed.fields[0].value
        file.close()
    Response.content_length = MAX_IMAGE + 1
    _, file = await prepare_proof_delivery(proof)
    assert file is None


def evidence_context(g):
    return SimpleNamespace(guild=g, author=SimpleNamespace(id=42, mention='<@42>'), message=SimpleNamespace(attachments=[]), send=AsyncMock(), defer=AsyncMock())


@pytest.mark.asyncio
async def test_add_evidence_denies_non_staff_before_fetching(make_cog, monkeypatch):
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level = AsyncMock(return_value=False)
    get_case = AsyncMock()
    monkeypatch.setattr('AdvancedMod.advmod.modlog.get_case', get_case)
    ctx = evidence_context(guild())
    await cog.add_evidence.callback(cog, ctx, '1', 'https://example.com/proof')
    get_case.assert_not_awaited()
    assert 'Only Class I' in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_evidence_appends_to_case_and_replies_without_editing_original(make_cog, monkeypatch):
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level = AsyncMock(return_value=True)
    g = guild()
    ctx = evidence_context(g)
    channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(jump_url='https://discord.com/channels/1/10/2')), permissions_for=lambda user: discord.Permissions(view_channel=True))
    message = SimpleNamespace(id=1, channel=channel, jump_url='https://discord.com/channels/1/10/1', edit=AsyncMock())
    case = SimpleNamespace(reason='Original reason', message=message, edit=AsyncMock())
    monkeypatch.setattr('AdvancedMod.advmod.modlog.get_case', AsyncMock(return_value=case))
    await cog.add_evidence.callback(cog, ctx, '1', 'https://example.com/proof')
    message.edit.assert_not_awaited()
    assert channel.send.call_args.kwargs['reference'] is message
    assert channel.send.call_args.kwargs['allowed_mentions'].everyone is False
    edit = case.edit.call_args.args[0]
    assert edit['reason'].startswith('Original reason\nAdditional evidence')
    assert 'https://example.com/proof' in edit['reason']
    assert edit['amended_by'] is ctx.author


@pytest.mark.asyncio
async def test_evidence_rejects_log_link_from_another_server(make_cog):
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level = AsyncMock(return_value=True)
    g = guild()
    await cog.config.guild(g).mod_channel.set(10)
    ctx = evidence_context(g)
    await cog.add_evidence.callback(cog, ctx, 'https://discord.com/channels/99/10/123456789012345678', 'https://example.com/proof')
    g.get_channel.assert_not_called()
    assert 'not found' in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_nonimage_attachment_is_preserved_as_file(make_cog, monkeypatch):
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level = AsyncMock(return_value=True)
    g = guild()
    g.filesize_limit = 10 * 1024 * 1024
    ctx = evidence_context(g)
    channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(jump_url='evidence')), permissions_for=lambda user: discord.Permissions(view_channel=True))
    case = SimpleNamespace(reason='Original', message=SimpleNamespace(channel=channel, jump_url='original'), edit=AsyncMock())
    monkeypatch.setattr('AdvancedMod.advmod.modlog.get_case', AsyncMock(return_value=case))
    monkeypatch.setattr('AdvancedMod.advmod.prepare_proof_delivery', AsyncMock(return_value=('<https://example.com/report.pdf>', None)))
    file = discord.File(io.BytesIO(b'report'), filename='report.pdf')
    attachment = SimpleNamespace(url='https://example.com/report.pdf', size=6, to_file=AsyncMock(return_value=file))
    ctx.message.attachments = [attachment]
    await cog.add_evidence.callback(cog, ctx, '1')
    assert channel.send.call_args.kwargs['file'] is file
    assert not channel.send.call_args.kwargs['embed'].image.url
    file.close()


@pytest.mark.asyncio
async def test_new_case_number_maps_to_log_and_sets_footer(make_cog, monkeypatch):
    cog = make_cog('AdvancedMod.advmod')
    g = guild()
    log = SimpleNamespace(id=987, edit=AsyncMock())
    channel = SimpleNamespace(send=AsyncMock(return_value=log))
    g.get_channel.return_value = channel
    await cog.config.guild(g).mod_channel.set(10)
    monkeypatch.setattr('AdvancedMod.advmod.modlog.create_case', AsyncMock(return_value=SimpleNamespace(case_number=12)))
    user = SimpleNamespace(id=42, mention='<@42>')
    await cog.log_immediate_action(g, 'Warn', user, user, 'Reason', 'None Provided')
    assert await cog.config.guild(g).case_logs() == {'12': {'channel': 10, 'message': 987}}
    assert log.edit.call_args.kwargs['embed'].footer.text == 'Case #12'


@pytest.mark.parametrize('scheme', ['javascript', 'data', 'file', 'ftp'])
def test_non_web_schemes_are_not_formatted_as_trusted_discord_links(scheme):
    from AdvancedMod.evidence import format_proof_link
    result = format_proof_link(f'{scheme}://discord.com/channels/1/2/3')
    assert '[Message]' not in result and '<#2>' not in result


def test_discord_links_are_normalized():
    from AdvancedMod.evidence import format_proof_link
    result = format_proof_link('http://ptb.discord.com/channels/1/2/3?tracking=abc')
    assert '[Message](https://discord.com/channels/1/2/3)' in result
    assert 'tracking' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('case', [None, SimpleNamespace(message=None)])
async def test_missing_case_or_log_has_a_friendly_error(make_cog, monkeypatch, case):
    cog = make_cog('AdvancedMod.advmod')
    cog._has_level = AsyncMock(return_value=True)
    ctx = evidence_context(guild())
    monkeypatch.setattr('AdvancedMod.advmod.modlog.get_case', AsyncMock(return_value=case))
    await cog.add_evidence.callback(cog, ctx, '999', 'https://example.com/proof')
    assert any(text in ctx.send.call_args.args[0] for text in ['not found', 'no available log'])
