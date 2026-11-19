import io
import asyncio
import time
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from test_regressions import make_cog


async def viewer(make_cog, allowed=True):
    cog = make_cog('modmailerviewer.viewer')
    member = SimpleNamespace(id=42, guild_permissions=discord.Permissions(manage_messages=allowed))
    channel = SimpleNamespace(id=10, guild=SimpleNamespace(name='Staff'), permissions_for=lambda user: discord.Permissions(manage_messages=allowed, view_channel=allowed, read_message_history=allowed))
    guild = SimpleNamespace(get_channel=lambda cid: channel if cid == 10 else None, fetch_member=AsyncMock(return_value=member))
    cog.bot.get_guild.return_value = guild
    await cog.config.staff_guild.set(1)
    await cog.config.archive_channel.set(10)
    await cog.config.public_url.set('https://tickets.example.com')
    cog.sessions['test'] = dict(user_id=42, name='Staff member', expires=time.time()+3600, csrf='csrf')
    return cog, channel, guild


@pytest.mark.asyncio
async def test_all_archive_routes_require_login(make_cog):
    cog, channel, guild = await viewer(make_cog)
    async with TestClient(TestServer(cog.make_app())) as client:
        for path in ['/', '/ticket/123', '/content/123', '/download/123']:
            response = await client.get(path, allow_redirects=False)
            assert response.status == 302 and response.headers['Location'] == '/login'
            assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.asyncio
async def test_staff_permissions_are_checked_on_every_request(make_cog):
    cog, channel, guild = await viewer(make_cog, allowed=False)
    async with TestClient(TestServer(cog.make_app())) as client:
        for path in ['/content/123', '/download/123']:
            response = await client.get(path, headers={'Cookie': 'modmailer_session=test'}, allow_redirects=False)
            assert response.status == 403
    assert guild.fetch_member.await_count == 2


@pytest.mark.asyncio
async def test_expired_session_does_not_read_archive(make_cog):
    cog, channel, guild = await viewer(make_cog)
    cog.sessions['test']['expires'] = 0
    request = make_mocked_request('GET', '/', headers={'Cookie': 'modmailer_session=test'})
    with pytest.raises(web.HTTPFound):
        await cog.authorize(request)
    guild.fetch_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_oauth_state_is_browser_bound_and_single_use(make_cog):
    cog, _, _ = await viewer(make_cog)
    cog.states['state'] = dict(browser='correct-browser', verifier='verifier', expires=time.time()+300)
    request = make_mocked_request('GET', '/oauth/callback?state=state&code=code', headers={'Cookie': 'modmailer_oauth=other-browser'})
    with pytest.raises(web.HTTPForbidden):
        await cog.callback(request)
    assert 'state' not in cog.states


@pytest.mark.asyncio
async def test_login_redirect_uses_identify_pkce_and_secure_cookie(make_cog):
    cog, _, _ = await viewer(make_cog)
    cog.bot.get_shared_api_tokens = AsyncMock(return_value={'client_id': '123', 'client_secret': 'secret'})
    response = await cog.login(make_mocked_request('GET', '/login'))
    assert 'scope=identify' in response.location
    assert 'code_challenge_method=S256' in response.location
    cookie = response.cookies['modmailer_oauth']
    assert cookie['secure'] and cookie['httponly'] and cookie['samesite'] == 'Lax'


@pytest.mark.parametrize('url', ['http://tickets.example.com', 'https://user:pass@example.com', 'https://example.com/path', 'https://example.com?redirect=evil'])
def test_public_url_validation(url):
    from modmailerviewer.viewer import valid_origin
    with pytest.raises(ValueError):
        valid_origin(url)


@pytest.mark.asyncio
async def test_recent_sidebar_and_sandboxed_transcript(make_cog):
    cog, channel, guild = await viewer(make_cog)
    attachment = SimpleNamespace(filename='transcript_G1001.html', size=100, read=AsyncMock(return_value=b'<html><head></head><body>Ticket text<script>alert(1)</script></body></html>'))
    message = SimpleNamespace(id=123, author=cog.bot.user, attachments=[attachment], embeds=[], created_at=discord.utils.utcnow())
    async def history(**kwargs):
        yield message
    channel.history = history
    channel.fetch_message = AsyncMock(return_value=message)
    async with TestClient(TestServer(cog.make_app())) as client:
        response = await client.get('/ticket/123', headers={'Cookie': 'modmailer_session=test'})
        assert response.status == 200
        html = await response.text()
        assert 'G1001' in html and 'sandbox="allow-downloads"' in html
        response = await client.get('/content/123', headers={'Cookie': 'modmailer_session=test'})
        assert response.status == 200
        assert 'sandbox allow-downloads' in response.headers['Content-Security-Policy']
        assert 'script-src' not in response.headers['Content-Security-Policy']


@pytest.mark.asyncio
async def test_transcripts_from_other_authors_are_rejected(make_cog):
    cog, channel, _ = await viewer(make_cog)
    channel.fetch_message = AsyncMock(return_value=SimpleNamespace(author=SimpleNamespace(id=77), attachments=[SimpleNamespace(filename='transcript_G1.html')]))
    async with TestClient(TestServer(cog.make_app())) as client:
        response = await client.get('/content/123', headers={'Cookie': 'modmailer_session=test'})
        assert response.status == 404


@pytest.mark.asyncio
async def test_avatar_fetch_only_uses_discord_cdn():
    from ticketmail.transcripts import avatar_data
    assert await avatar_data('http://127.0.0.1/private.png', {}) == ''
    assert await avatar_data('https://attacker.example/picture.png', {}) == ''


@pytest.mark.asyncio
async def test_permission_revocation_invalidates_existing_session(make_cog):
    cog, channel, guild = await viewer(make_cog)
    request = make_mocked_request('GET', '/', headers={'Cookie': 'modmailer_session=test'})
    await cog.authorize(request)
    guild.fetch_member.return_value.guild_permissions = discord.Permissions.none()
    with pytest.raises(web.HTTPForbidden):
        await cog.authorize(request)


@pytest.mark.asyncio
async def test_oauth_callback_exchanges_code_with_pkce_and_discards_token(make_cog):
    cog, _, _ = await viewer(make_cog)
    cog.bot.get_shared_api_tokens = AsyncMock(return_value={'client_id': '123', 'client_secret': 'secret'})
    class Response:
        def __init__(self, data): self.data = data
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def json(self): return self.data
    cog.http = SimpleNamespace(post=Mock(return_value=Response({'access_token': 'private-token'})), get=Mock(return_value=Response({'id': '42', 'username': 'Staff'})))
    cog.states['state'] = dict(browser='browser', verifier='verifier', expires=time.time()+300)
    request = make_mocked_request('GET', '/oauth/callback?state=state&code=code', headers={'Cookie': 'modmailer_oauth=browser'})
    response = await cog.callback(request)
    assert response.status == 302
    assert cog.http.post.call_args.kwargs['data']['code_verifier'] == 'verifier'
    assert 'private-token' not in str(cog.sessions)
    assert response.cookies['modmailer_session']['httponly']
    assert response.cookies['modmailer_session']['secure']


@pytest.mark.asyncio
async def test_zip_transcript_is_read_without_extracting_files(make_cog):
    cog, channel, _ = await viewer(make_cog)
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('transcript_G1.html', '<html><head></head><body>Archived ticket</body></html>')
    attachment = SimpleNamespace(filename='transcript_G1.zip', size=len(data.getvalue()), read=AsyncMock(return_value=data.getvalue()))
    channel.fetch_message = AsyncMock(return_value=SimpleNamespace(id=123, author=cog.bot.user, attachments=[attachment]))
    async with TestClient(TestServer(cog.make_app())) as client:
        response = await client.get('/content/123', headers={'Cookie': 'modmailer_session=test'})
        assert response.status == 200
        assert 'Archived ticket' in await response.text()


@pytest.mark.asyncio
async def test_logout_requires_origin_and_csrf(make_cog):
    cog, _, _ = await viewer(make_cog)
    async with TestClient(TestServer(cog.make_app())) as client:
        response = await client.post('/logout', headers={'Cookie': 'modmailer_session=test', 'Origin': 'https://attacker.example'}, data={'csrf': 'csrf'}, allow_redirects=False)
        assert response.status == 403 and 'test' in cog.sessions
        response = await client.post('/logout', headers={'Cookie': 'modmailer_session=test', 'Origin': 'https://tickets.example.com'}, data={'csrf': 'csrf'}, allow_redirects=False)
        assert response.status == 302 and 'test' not in cog.sessions


@pytest.mark.asyncio
async def test_profile_picture_is_embedded_and_cached(monkeypatch):
    import ticketmail.transcripts as transcripts
    payload = b'avatar-image'
    class Response:
        status = 200
        headers = {'Content-Type': 'image/png'}
        content = SimpleNamespace(readexactly=AsyncMock(side_effect=asyncio.IncompleteReadError(payload, 262145)))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    get = Mock(return_value=Response())
    class Session:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, *args, **kwargs):
            return get(*args, **kwargs)
    monkeypatch.setattr(transcripts.aiohttp, 'ClientSession', Session)
    cache = {}
    url = 'https://cdn.discordapp.com/avatars/42/image.png'
    first = await transcripts.avatar_data(url, cache)
    assert first.startswith('data:image/png;base64,')
    assert await transcripts.avatar_data(url, cache) == first
    assert get.call_count == 1


@pytest.mark.asyncio
async def test_successful_oauth_callback_creates_staff_session_without_saving_token(make_cog):
    cog, _, _ = await viewer(make_cog)
    cog.bot.get_shared_api_tokens = AsyncMock(return_value={'client_id': '123', 'client_secret': 'secret'})
    cog.states['state'] = dict(browser='browser', verifier='verifier', expires=time.time()+300)
    class Response:
        def __init__(self, payload): self.payload = payload
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def json(self): return self.payload
    post = Mock(return_value=Response({'access_token': 'private-token'}))
    cog.http = SimpleNamespace(post=post, get=Mock(return_value=Response({'id': '42', 'username': 'Staff'})))
    request = make_mocked_request('GET', '/oauth/callback?state=state&code=code', headers={'Cookie': 'modmailer_oauth=browser'})
    response = await cog.callback(request)
    assert response.status == 302 and response.cookies['modmailer_session']['secure']
    assert post.call_args.kwargs['data']['code_verifier'] == 'verifier'
    assert 'private-token' not in str(cog.sessions)
    assert not cog.states


@pytest.mark.parametrize('url', ['http://203.0.113.10:8088', 'http://[2001:db8::10]:8088'])
def test_http_ip_requires_explicit_opt_in(url):
    from modmailerviewer.viewer import valid_origin
    with pytest.raises(ValueError):
        valid_origin(url)
    assert valid_origin(url, allow_http=True) == url
    with pytest.raises(ValueError):
        valid_origin('http://example.com', allow_http=True)


@pytest.mark.asyncio
async def test_disk_archive_survives_restart_and_expires_from_creation(tmp_path, monkeypatch):
    from modmailerviewer.storage import ArchiveStore, RETENTION
    monkeypatch.setattr('modmailerviewer.storage.time.time', lambda: 10000000)
    store = ArchiveStore(tmp_path / 'archive.sqlite3')
    created = 10000000 - RETENTION + 100
    await store.put(10, 123, 'transcript_G1.html', 'Ticket', created, b'original')
    reopened = ArchiveStore(store.path)
    assert (await reopened.get(10, 123))['data'] == b'original'
    assert 'data' not in (await reopened.recent(10, 50))[0]
    monkeypatch.setattr('modmailerviewer.storage.time.time', lambda: 10000100)
    await reopened.expire()
    assert await reopened.get(10, 123) is None
    await reopened.put(10, 123, 'transcript_G1.html', 'Ticket', created, b'expired')
    assert await reopened.recent(10, 50) == []


@pytest.mark.asyncio
async def test_local_copy_precedes_discord_and_old_archive_falls_back_without_recaching(make_cog):
    import datetime
    from modmailerviewer.storage import RETENTION
    cog, channel, _ = await viewer(make_cog)
    await cog.store.put(10, 123, 'transcript_G1.html', 'Ticket', time.time(), b'local')
    channel.fetch_message = AsyncMock()
    assert await cog.get_archive(channel, '123') == ('transcript_G1.html', b'local')
    channel.fetch_message.assert_not_awaited()
    attachment = SimpleNamespace(filename='transcript_G2.html', size=7, read=AsyncMock(return_value=b'channel'))
    channel.fetch_message.return_value = SimpleNamespace(id=456, author=cog.bot.user, attachments=[attachment], embeds=[], created_at=discord.utils.utcnow()-datetime.timedelta(seconds=RETENTION+1))
    assert await cog.get_archive(channel, '456') == ('transcript_G2.html', b'channel')
    assert await cog.store.get(10, 456) is None


@pytest.mark.asyncio
async def test_backfill_stores_recent_bot_transcripts(make_cog):
    cog, channel, _ = await viewer(make_cog)
    cog.bot.wait_until_red_ready = AsyncMock()
    attachment = SimpleNamespace(filename='transcript_G1.html', size=4, read=AsyncMock(return_value=b'html'))
    async def history(**kwargs):
        assert kwargs['after'] < discord.utils.utcnow()
        yield SimpleNamespace(id=123, author=cog.bot.user, attachments=[attachment], embeds=[], created_at=discord.utils.utcnow())
        yield SimpleNamespace(id=124, author=SimpleNamespace(id=1), attachments=[attachment])
    channel.history = history
    await cog.sync_archives()
    assert (await cog.store.get(10, 123))['data'] == b'html'
    assert await cog.store.get(10, 124) is None


@pytest.mark.parametrize('url', ['https://tickets.example.com:99999', 'https://tickets.example.com:not-a-port', 'http://203.0.113.10:99999'])
def test_invalid_origin_ports_are_rejected(url):
    from modmailerviewer.viewer import valid_origin
    with pytest.raises(ValueError):
        valid_origin(url, allow_http=True)


@pytest.mark.asyncio
async def test_avatar_fetches_share_one_session_and_limit_concurrency(monkeypatch):
    import ticketmail.transcripts as transcripts
    sessions = []
    active = 0
    maximum = 0
    class Session:
        def __init__(self, **kwargs): sessions.append(self)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    async def avatar(url, cache, session):
        nonlocal active, maximum
        assert session is sessions[0]
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        cache[url] = 'picture'
        active -= 1
    monkeypatch.setattr(transcripts.aiohttp, 'ClientSession', Session)
    monkeypatch.setattr(transcripts, 'avatar_data', avatar)
    urls = [str(i) for i in range(12)]
    cache = {}
    await transcripts.fetch_avatars(urls + urls, cache)
    assert len(sessions) == 1 and maximum == 4 and len(cache) == 12


@pytest.mark.asyncio
async def test_avatar_budget_cancels_slow_fetches(monkeypatch):
    import ticketmail.transcripts as transcripts
    cancelled = []
    async def slow(url, cache, session):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(url)
    real_wait = asyncio.wait_for
    async def short_wait(task, timeout):
        assert timeout == 6
        return await real_wait(task, timeout=0.01)
    monkeypatch.setattr(transcripts, 'avatar_data', slow)
    monkeypatch.setattr(transcripts.asyncio, 'wait_for', short_wait)
    await transcripts.fetch_avatars(['a', 'b'], {})
    assert sorted(cancelled) == ['a', 'b']
