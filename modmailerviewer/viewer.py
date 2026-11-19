import asyncio
import base64
import hashlib
import datetime
import ipaddress
import io
import re
import secrets
import time
import zipfile
from html import escape
from urllib.parse import urlencode, urlsplit

import aiohttp
import discord
from aiohttp import web
from redbot.core import Config, commands, data_manager
from discord.ext import tasks
from .storage import ArchiveStore, RETENTION


COOKIE = "modmailer_session"
STATE_COOKIE = "modmailer_oauth"
MAX_ARCHIVE = 25 * 1024 * 1024
TRANSCRIPT = re.compile(r"^transcript_[A-Za-z0-9_-]+\.(html|zip)$")
STYLE = """
*{box-sizing:border-box}body{margin:0;background:#313338;color:#dbdee1;font:14px/1.5 'Segoe UI',Arial,sans-serif}a{color:inherit;text-decoration:none}.app{display:grid;grid-template-columns:280px minmax(0,1fr);height:100vh}.sidebar{background:#2b2d31;overflow:auto;padding:16px 12px;border-right:1px solid #1e1f22}.brand{font-size:16px;font-weight:650;color:#f2f3f5;padding:0 10px 16px;border-bottom:1px solid #1e1f22}.section{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#949ba4;padding:20px 10px 8px}.ticket{display:block;border-radius:5px;padding:10px;margin-bottom:4px}.ticket:hover,.ticket.active{background:#404249}.ticket strong{font-weight:550;color:#f2f3f5}.ticket small{display:block;font-size:11px;color:#b5bac1;margin-top:2px;overflow-wrap:anywhere}.hash{color:#80848e;margin-right:7px}.account{font-size:12px;color:#949ba4;padding:16px 10px}.avatar{width:28px;height:28px;vertical-align:middle;border-radius:50%;margin-right:8px}.logout{background:none;border:1px solid #4e5058;border-radius:4px;color:#dbdee1;padding:5px 10px;cursor:pointer}.main{min-width:0;display:flex;flex-direction:column}.toolbar{height:54px;flex-shrink:0;padding:15px 22px;border-bottom:1px solid #1e1f22;display:flex;justify-content:space-between;gap:12px}.toolbar a{color:#00a8fc}iframe{border:0;width:100%;flex:1;background:#313338}.empty{padding:50px 32px;color:#b5bac1}.login{max-width:440px;margin:15vh auto;padding:32px;background:#2b2d31;border-radius:8px}.button{display:inline-block;background:#5865f2;padding:10px 18px;border-radius:4px;color:white}h1{color:#f2f3f5;font-size:24px}.notice{color:#949ba4;font-size:12px}@media(max-width:700px){.app{grid-template-columns:190px minmax(0,1fr)}.sidebar{padding:12px 6px}.toolbar{height:auto;font-size:12px;padding:12px}}
"""


def valid_origin(value, allow_http=False):
    parsed = urlsplit(value)
    port = parsed.port
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Use the public origin without a path, query or credentials.")
    try:
        ipaddress.ip_address(parsed.hostname or "")
        numeric_ip = True
    except ValueError:
        numeric_ip = False
    if not parsed.hostname or (parsed.scheme != "https" and not ((local or (numeric_ip and allow_http)) and parsed.scheme == "http")):
        raise ValueError("Use HTTPS, a loopback HTTP URL, or an HTTP IP address with allow_http enabled.")
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    suffix = f":{port}" if port is not None and port != {"http": 80, "https": 443}[parsed.scheme] else ""
    return f"{parsed.scheme}://{host}{suffix}"


@web.middleware
async def security_headers(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "SAMEORIGIN"})
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src https://cdn.discordapp.com data:; frame-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'self'")
    if isinstance(response, web.HTTPException):
        raise response
    return response


class ModmailerViewer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=87391843271, force_registration=True)
        self.config.register_global(staff_guild=None, archive_channel=None, public_url="", host="127.0.0.1", port=8088, recent_limit=50, allow_http=False)
        self.sessions = {}
        self.states = {}
        self.runner = None
        self.http = None
        self._server_lock = asyncio.Lock()
        self.store = None
        self._setup_running = False

    async def cog_load(self):
        await self.get_store().expire()
        self.expiry_loop.start()
        if await self.config.public_url():
            await self.start_server()

    async def cog_unload(self):
        self.expiry_loop.cancel()
        await self.stop_server()

    async def red_delete_data_for_the_user(self, *, user_id, **kwargs):
        self.sessions = {key: value for key, value in self.sessions.items() if value["user_id"] != user_id}

    def make_app(self):
        app = web.Application(middlewares=[security_headers], client_max_size=4096)
        app.add_routes([web.get("/", self.index), web.get("/login", self.login), web.get("/oauth/callback", self.callback), web.post("/logout", self.logout), web.get("/ticket/{message_id}", self.index), web.get("/content/{message_id}", self.content), web.get("/download/{message_id}", self.download)])
        return app

    async def start_server(self):
        async with self._server_lock:
            await self.stop_server()
            settings = await self.config.all()
            valid_origin(settings["public_url"], settings["allow_http"])
            self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
            self.runner = web.AppRunner(self.make_app(), access_log=None)
            try:
                await self.runner.setup()
                await web.TCPSite(self.runner, settings["host"], settings["port"]).start()
            except Exception:
                await self.stop_server()
                raise

    async def stop_server(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        if self.http:
            await self.http.close()
            self.http = None
        self.sessions.clear()
        self.states.clear()

    def prune(self):
        now = time.time()
        for storage in (self.sessions, self.states):
            for key in list(storage):
                if storage[key]["expires"] <= now:
                    del storage[key]

    async def authorize(self, request):
        self.prune()
        session = self.sessions.get(request.cookies.get(COOKIE, ""))
        if not session:
            raise web.HTTPFound("/login")
        return session, await self.check_access(session["user_id"])

    async def check_access(self, user_id):
        settings = await self.config.all()
        guild = self.bot.get_guild(settings["staff_guild"])
        channel = guild.get_channel(settings["archive_channel"]) if guild else None
        if not channel:
            raise web.HTTPServiceUnavailable(text="The staff archive channel is unavailable.")
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            raise web.HTTPForbidden(text="Staff server membership is required.")
        except discord.HTTPException:
            raise web.HTTPServiceUnavailable(text="Staff permissions could not be checked. Try again later.")
        permissions = channel.permissions_for(member)
        if not member.guild_permissions.manage_messages or not permissions.view_channel or not permissions.read_message_history:
            raise web.HTTPForbidden(text="Staff access to the archive channel is required.")
        return channel

    async def credentials(self):
        tokens = await self.bot.get_shared_api_tokens("modmailerviewer")
        if not tokens.get("client_id") or not tokens.get("client_secret"):
            raise web.HTTPServiceUnavailable(text="Discord OAuth is not configured. Ask the bot owner to configure modmailerviewer API tokens.")
        return tokens

    async def login(self, request):
        self.prune()
        if len(self.states) >= 1000:
            raise web.HTTPServiceUnavailable(text="Too many sign-in attempts. Try again shortly.")
        tokens = await self.credentials()
        origin = valid_origin(await self.config.public_url(), await self.config.allow_http())
        state = secrets.token_urlsafe(32)
        browser = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.states[state] = dict(browser=browser, verifier=verifier, expires=time.time() + 300)
        query = urlencode(dict(client_id=tokens["client_id"], redirect_uri=origin + "/oauth/callback", response_type="code", scope="identify", state=state, code_challenge=challenge, code_challenge_method="S256"))
        response = web.HTTPFound("https://discord.com/oauth2/authorize?" + query)
        response.set_cookie(STATE_COOKIE, browser, max_age=300, httponly=True, secure=origin.startswith("https://"), samesite="Lax", path="/")
        return response

    async def callback(self, request):
        self.prune()
        state = self.states.pop(request.query.get("state", ""), None)
        browser = request.cookies.get(STATE_COOKIE, "")
        if not state or not browser or not secrets.compare_digest(browser, state["browser"]) or not request.query.get("code"):
            raise web.HTTPForbidden(text="The sign-in request expired or could not be verified. Start again.")
        if len(self.sessions) >= 5000:
            raise web.HTTPServiceUnavailable(text="Too many active sessions.")
        tokens = await self.credentials()
        origin = valid_origin(await self.config.public_url(), await self.config.allow_http())
        try:
            async with self.http.post("https://discord.com/api/v10/oauth2/token", data=dict(client_id=tokens["client_id"], client_secret=tokens["client_secret"], grant_type="authorization_code", code=request.query["code"], redirect_uri=origin + "/oauth/callback", code_verifier=state["verifier"])) as response:
                response.raise_for_status()
                token = await response.json()
            async with self.http.get("https://discord.com/api/v10/users/@me", headers={"Authorization": "Bearer " + token["access_token"]}) as response:
                response.raise_for_status()
                user = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError):
            raise web.HTTPBadGateway(text="Discord sign-in failed. Please try again.")
        await self.check_access(int(user["id"]))
        session_id = secrets.token_urlsafe(32)
        avatar = ""
        if user.get("avatar") and re.fullmatch(r"[A-Za-z0-9_]+", user["avatar"]):
            avatar = f'https://cdn.discordapp.com/avatars/{int(user["id"])}/{user["avatar"]}.png?size=64'
        self.sessions[session_id] = dict(user_id=int(user["id"]), name=user.get("global_name") or user["username"], avatar=avatar, csrf=secrets.token_urlsafe(24), expires=time.time() + 3600)
        result = web.HTTPFound("/")
        result.set_cookie(COOKIE, session_id, max_age=3600, httponly=True, secure=origin.startswith("https://"), samesite="Lax", path="/")
        result.del_cookie(STATE_COOKIE, path="/")
        return result

    async def logout(self, request):
        session, _ = await self.authorize(request)
        data = await request.post()
        origin = valid_origin(await self.config.public_url(), await self.config.allow_http())
        if request.headers.get("Origin") != origin or not secrets.compare_digest(str(data.get("csrf", "")), session["csrf"]):
            raise web.HTTPForbidden(text="Invalid request origin.")
        self.sessions.pop(request.cookies.get(COOKIE, ""), None)
        result = web.HTTPFound("/login")
        result.del_cookie(COOKIE, path="/")
        return result

    def transcript_attachment(self, message):
        if message.author.id != self.bot.user.id:
            return None
        return next((a for a in message.attachments if TRANSCRIPT.fullmatch(a.filename)), None)

    def get_store(self):
        if self.store is None:
            self.store = ArchiveStore(data_manager.cog_data_path(self) / "transcripts.sqlite3")
        return self.store

    @tasks.loop(hours=1)
    async def expiry_loop(self):
        await self.get_store().expire()
        await self.sync_archives()

    async def sync_archives(self):
        await self.bot.wait_until_red_ready()
        settings = await self.config.all()
        guild = self.bot.get_guild(settings["staff_guild"])
        channel = guild.get_channel(settings["archive_channel"]) if guild else None
        if not channel:
            return
        after = discord.utils.utcnow() - datetime.timedelta(days=28)
        try:
            async for message in channel.history(limit=None, after=after, oldest_first=True):
                attachment = self.transcript_attachment(message)
                if attachment and attachment.size <= MAX_ARCHIVE and not await self.get_store().get(channel.id, message.id):
                    try:
                        await self.save_message(channel.id, message, attachment)
                    except discord.HTTPException:
                        continue
        except discord.HTTPException:
            return

    async def save_message(self, channel_id, message, attachment):
        created = getattr(message, "created_at", discord.utils.utcnow()).timestamp()
        if created + RETENTION <= time.time():
            return None
        data = await attachment.read()
        if len(data) > MAX_ARCHIVE:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_ARCHIVE, actual_size=len(data))
        title = message.embeds[0].title if getattr(message, "embeds", None) else attachment.filename
        await self.get_store().put(channel_id, message.id, attachment.filename, title or attachment.filename, created, data)
        return data

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.channel.id != await self.config.archive_channel() or message.guild.id != await self.config.staff_guild():
            return
        attachment = self.transcript_attachment(message)
        if attachment and attachment.size <= MAX_ARCHIVE:
            await self.save_message(message.channel.id, message, attachment)

    async def get_archive(self, channel, value):
        if not value.isdigit():
            raise web.HTTPNotFound()
        local = await self.get_store().get(channel.id, value)
        if local:
            return local["filename"], local["data"]
        try:
            message = await channel.fetch_message(int(value))
        except discord.NotFound:
            raise web.HTTPNotFound()
        attachment = self.transcript_attachment(message)
        if not attachment:
            raise web.HTTPNotFound()
        if attachment.size > MAX_ARCHIVE:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_ARCHIVE, actual_size=attachment.size)
        data = await self.save_message(channel.id, message, attachment)
        if data is None:
            data = await attachment.read()
        if len(data) > MAX_ARCHIVE:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_ARCHIVE, actual_size=len(data))
        return attachment.filename, data

    async def index(self, request):
        session, channel = await self.authorize(request)
        selected = request.match_info.get("message_id")
        rows = []
        limit = await self.config.recent_limit()
        entries = {item["message_id"]: item for item in await self.get_store().recent(channel.id, limit)}
        try:
            async for message in channel.history(limit=500):
                attachment = self.transcript_attachment(message)
                if not attachment:
                    continue
                key = str(message.id)
                title = message.embeds[0].title if message.embeds else attachment.filename
                entries[key] = dict(message_id=key, filename=attachment.filename, title=title, created=message.created_at.timestamp())
        except discord.HTTPException:
            if not entries:
                raise web.HTTPServiceUnavailable(text="No local archives are available and Discord logs could not be read.")
        for entry in sorted(entries.values(), key=lambda item: item["created"], reverse=True)[:limit]:
            key = entry["message_id"]
            label = entry["filename"].removeprefix("transcript_").rsplit(".", 1)[0]
            date = datetime.datetime.fromtimestamp(entry["created"], datetime.timezone.utc).strftime("%d %b %Y · %H:%M UTC")
            rows.append(f'<a class="ticket {"active" if selected == key else ""}" href="/ticket/{key}"><strong><span class="hash">#</span>{escape(label)}</strong><small>{escape(entry["title"] or label)}</small><small>{date}</small></a>')
        if selected:
            await self.get_archive(channel, selected)
            pane = f'<div class="toolbar"><span>Ticket archive</span><a href="/download/{selected}">Download original</a></div><iframe title="Ticket transcript" sandbox="allow-downloads" referrerpolicy="no-referrer" src="/content/{selected}"></iframe>'
        else:
            pane = '<div class="toolbar">Ticket archive</div><div class="empty"><h1>Recent transcripts</h1><p>Select a ticket from the sidebar to read its conversation and attachments.</p></div>'
        account_avatar = f'<img class="avatar" src="{escape(session.get("avatar", ""), quote=True)}" alt="Profile picture">' if session.get("avatar") else ""
        html = f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Modmail archive</title><style>{STYLE}</style></head><body><div class="app"><aside class="sidebar"><div class="brand">{escape(channel.guild.name)}</div><div class="section">Recent transcripts</div>{"".join(rows) or "<p>No transcripts found.</p>"}<div class="account">{account_avatar}Signed in as {escape(session["name"])}<form method="post" action="/logout"><input type="hidden" name="csrf" value="{session["csrf"]}"><button class="logout">Sign out</button></form></div></aside><main class="main">{pane}</main></div></body></html>'
        return web.Response(text=html, content_type="text/html")

    async def content(self, request):
        _, channel = await self.authorize(request)
        filename, data = await self.get_archive(channel, request.match_info["message_id"])
        if len(data) > MAX_ARCHIVE:
            raise web.HTTPBadRequest(text="Archive is too large.")
        if filename.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    files = [item for item in archive.infolist() if re.fullmatch(r"transcript_[A-Za-z0-9_-]+\.html", item.filename)]
                    if len(files) != 1 or files[0].file_size > MAX_ARCHIVE:
                        raise ValueError()
                    data = archive.read(files[0])
            except (zipfile.BadZipFile, ValueError, RuntimeError):
                raise web.HTTPBadRequest(text="Unsupported transcript archive.")
        html = data.decode("utf-8", errors="replace")
        html = html.replace("</head>", '<style>.sidebar{display:none!important}.app{grid-template-columns:1fr!important}</style></head>', 1)
        return web.Response(text=html, content_type="text/html", headers={"Content-Security-Policy": "sandbox allow-downloads; default-src 'none'; style-src 'unsafe-inline'; img-src data: https://cdn.discordapp.com https://media.discordapp.net; media-src data:; base-uri 'none'; form-action 'none'"})

    async def download(self, request):
        _, channel = await self.authorize(request)
        filename, data = await self.get_archive(channel, request.match_info["message_id"])
        return web.Response(body=data, content_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @commands.group(name="viewerset")
    @commands.is_owner()
    async def viewerset(self, ctx):
        """Configure the authenticated Modmail archive viewer."""

    @viewerset.command(name="setup")
    @commands.guild_only()
    async def configure(self, ctx, channel: discord.TextChannel = None, public_url: str = None, port: commands.Range[int, 1024, 65535] = 8088, allow_http: bool = False):
        if channel is None and public_url is None:
            from .setup import guided_setup
            return await guided_setup(self, ctx)
        if channel is None or public_url is None:
            return await ctx.send("Run viewerset setup without arguments for the guide, or provide both the archive channel and URL.")
        try:
            origin = valid_origin(public_url, allow_http)
        except ValueError as exc:
            return await ctx.send(str(exc))
        if channel.guild.id != ctx.guild.id:
            return await ctx.send("Choose an archive channel in this staff server.")
        permissions = channel.permissions_for(ctx.guild.me)
        if not permissions.view_channel or not permissions.read_message_history:
            return await ctx.send("The bot needs View Channel and Read Message History in the archive channel.")
        previous = await self.config.all()
        await self.config.staff_guild.set(ctx.guild.id)
        await self.config.archive_channel.set(channel.id)
        await self.config.public_url.set(origin)
        await self.config.port.set(port)
        await self.config.allow_http.set(allow_http)
        host = "127.0.0.1"
        try:
            address = ipaddress.ip_address(urlsplit(origin).hostname)
            if address.is_loopback and address.version == 6:
                host = "::1"
            elif not address.is_loopback and origin.startswith("http://"):
                host = "0.0.0.0" if address.version == 4 else "::"
        except ValueError:
            pass
        await self.config.host.set(host)
        try:
            await self.start_server()
        except OSError:
            for key, value in previous.items():
                await self.config.get_attr(key).set(value)
            if previous["public_url"]:
                try:
                    await self.start_server()
                except OSError:
                    pass
            await ctx.send("The viewer could not bind to that address/port. Check whether the port is already in use and whether the host supports the address. Previous settings were restored; rerun setup with an available port.")
            return False
        self.expiry_loop.restart()
        await ctx.send(f"Viewer started on {host}:{port}. Public URL: {origin}. OAuth redirect: {origin}/oauth/callback" + (" HTTP connections send session cookies without encryption; use a trusted network or HTTPS." if origin.startswith("http://") and host != "127.0.0.1" else ""))
        return True

    @viewerset.command(name="stop")
    async def stop(self, ctx):
        await self.stop_server()
        await self.config.public_url.set("")
        await ctx.send("Viewer stopped. Sessions have been cleared.")
