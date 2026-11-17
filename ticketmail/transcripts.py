import base64
import asyncio
import datetime
import io
import zipfile
from urllib.parse import urlsplit, urlunsplit
from html import escape

import discord
import aiohttp


class TranscriptAttachmentError(Exception):
    pass


async def avatar_data(url, cache):
    url = str(url or "")
    if url in cache:
        return cache[url]
    cache[url] = ""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme != "https" or parsed.hostname not in {"cdn.discordapp.com", "media.discordapp.net"} or parsed.username or parsed.password:
        return ""
    try:
        if parsed.port not in (None, 443):
            return ""
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            fetch_url = url
            if parsed.path.startswith(("/avatars/", "/icons/")):
                path = parsed.path.rsplit(".", 1)[0] + ".png"
                fetch_url = urlunsplit((parsed.scheme, parsed.netloc, path, "size=64", ""))
            async with session.get(fetch_url, allow_redirects=False) as response:
                if response.status != 200:
                    return ""
                mime = response.headers.get("Content-Type", "").split(";")[0]
                if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                    return ""
                try:
                    await response.content.readexactly(262145)
                except asyncio.IncompleteReadError as exc:
                    data = exc.partial
                else:
                    return ""
                cache[url] = f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'
    except (aiohttp.ClientError, TimeoutError, ValueError):
        pass
    return cache[url]


def safe_url(url):
    value = str(url or "")
    return escape(value, quote=True) if value.startswith(("https://", "http://")) else ""


def format_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


async def attachment_card(attachment):
    try:
        data = await attachment.read()
    except Exception as exc:
        raise TranscriptAttachmentError(f"Could not archive attachment {attachment.filename!r}. The original ticket must be kept.") from exc
    name = escape(attachment.filename, quote=True)
    content_type = (attachment.content_type or "").split(";")[0].lower()
    image_types = {"image/png", "image/jpeg", "image/gif", "image/webp"}
    media_types = image_types | {"video/mp4", "video/webm", "audio/mpeg", "audio/ogg", "audio/wav"}
    mime = content_type if content_type in media_types else "application/octet-stream"
    detected_image = None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_image = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        detected_image = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        detected_image = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        detected_image = "image/webp"
    if detected_image:
        mime = detected_image
    elif mime in image_types:
        mime = "application/octet-stream"
    encoded = base64.b64encode(data).decode("ascii")
    uri = f"data:{mime};base64,{encoded}"
    preview = ""
    if mime in image_types:
        preview = f'<img class="attachment-image" src="{uri}" alt="{name}">'
    elif mime.startswith("video/"):
        preview = f'<video controls preload="metadata" src="{uri}"></video>'
    elif mime.startswith("audio/"):
        preview = f'<audio controls preload="metadata" src="{uri}"></audio>'
    return f'<div class="attachment">{preview}<a class="file" href="{uri}" download="{name}"><span class="file-icon">↓</span><span><strong>{name}</strong><small>{format_size(len(data))} · Download attachment</small></span></a></div>'


STYLE = """
:root{color-scheme:dark;--bg:#313338;--panel:#2b2d31;--rail:#1e1f22;--text:#dbdee1;--muted:#949ba4;--border:#3f4147;--link:#00a8fc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 'Segoe UI',Helvetica,Arial,sans-serif}a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.app{display:grid;grid-template-columns:224px minmax(0,1fr);min-height:100vh}.sidebar{background:var(--panel);padding:22px 12px;position:sticky;top:0;height:100vh}.server{font-weight:650;color:#f2f3f5;padding:0 10px 18px;border-bottom:1px solid var(--rail);overflow-wrap:anywhere}.section{font-size:11px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;color:var(--muted);margin:22px 10px 8px}.channel{background:#404249;color:#f2f3f5;border-radius:4px;padding:7px 10px;overflow-wrap:anywhere}.hash{font-size:21px;color:#80848e;margin-right:8px;vertical-align:-1px}.sidebar-note{font-size:12px;color:var(--muted);margin:20px 10px}
main{min-width:0}.topbar{height:54px;display:flex;align-items:center;gap:12px;padding:0 24px;border-bottom:1px solid var(--rail);background:var(--bg)}.topbar strong{color:#f2f3f5}.topbar small{border-left:1px solid var(--border);padding-left:14px;color:var(--muted)}
.intro{padding:32px 28px 22px;border-bottom:1px solid var(--border)}.channel-icon{display:grid;place-items:center;background:#41434a;width:60px;height:60px;border-radius:50%;font-size:40px;color:white;margin-bottom:14px}h1{font-size:28px;color:#f2f3f5;line-height:1.2;margin:0 0 10px}.intro p{color:var(--muted);margin:6px 0}.metadata{display:flex;flex-wrap:wrap;gap:8px 24px;font-size:12px;margin-top:20px;color:var(--muted)}.metadata b{color:var(--text);font-weight:500}.reason{font-size:13px;margin-top:14px;color:var(--muted);overflow-wrap:anywhere}
.messages{padding:10px 0 40px}.day{display:flex;align-items:center;gap:12px;margin:24px 24px 18px;color:var(--muted);font-size:11px;font-weight:600}.day:before,.day:after{content:'';height:1px;background:var(--border);flex:1}.message{display:flex;gap:16px;padding:5px 28px;margin-top:12px}.message:hover{background:#2e3035}.avatar{width:40px;height:40px;flex:0 0 40px;border-radius:50%;background:#5865f2;display:grid;place-items:center;color:#fff;font-size:17px;font-weight:600;overflow:hidden}.msg-body{min-width:0;flex:1}.msg-header{display:flex;gap:8px;align-items:center;flex-wrap:wrap;min-height:22px}.username{color:#f2f3f5;font-weight:600}.staff .username{color:#57c9a2}.timestamp{font-size:11px;color:var(--muted)}.badge{background:#5865f2;color:#fff;font-size:9px;font-weight:650;padding:1px 4px;border-radius:3px;letter-spacing:.03em}.badge.note{background:#806529}.badge.anonymous{background:#4e5058}.content{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5}.embed{border-left:4px solid #5865f2;background:var(--panel);border-radius:4px;padding:12px 16px;max-width:620px;margin-top:8px}.embed-title{font-size:14px;font-weight:650;color:#f2f3f5;margin-bottom:5px}.field{margin-top:10px;white-space:pre-wrap;overflow-wrap:anywhere}.field b{font-size:12px;color:#f2f3f5}.embed-footer{color:var(--muted);font-size:11px;margin-top:10px}.attachment{margin-top:8px;max-width:560px;border:1px solid var(--rail);border-radius:6px;overflow:hidden;background:var(--panel)}.attachment-image{display:block;max-width:100%;max-height:420px;object-fit:contain;height:auto}.file{display:flex;gap:12px;align-items:center;padding:11px 14px;overflow-wrap:anywhere}.file-icon{font-size:24px;color:#b5bac1}.file strong{font-size:13px;font-weight:500}.file small{display:block;font-size:11px;color:var(--muted);margin-top:2px}video,audio{max-width:100%;display:block}.external{font-size:12px;margin-top:8px}.end{padding:16px 28px;color:var(--muted);font-size:12px;border-top:1px solid var(--border)}
@media(max-width:700px){.app{grid-template-columns:1fr}.sidebar{display:none}.message{padding:6px 16px;gap:12px}.intro{padding:24px 16px}.topbar{padding:0 16px}h1{font-size:24px}}
"""


async def render_transcript(cog, channel, owners_text, closer_display, reason, ticket_id):
    records = []
    avatars = {}
    previous_day = None
    count = 0
    attachment_count = 0
    owners = await cog.config.channel(channel).owner_ids() or []
    if not owners:
        legacy_owner = await cog.config.channel(channel).owner_id()
        owners = [legacy_owner] if legacy_owner else []
    async for message in channel.history(limit=None, oldest_first=True):
        day = message.created_at.strftime("%d %B %Y")
        if day != previous_day:
            records.append(f'<div class="day">{day}</div>')
            previous_day = day
        author = message.author
        avatar_url = str(getattr(getattr(author, "display_avatar", None), "url", ""))
        name = author.display_name if hasattr(author, "display_name") else author.name
        content = message.clean_content
        badge = '<span class="badge">BOT</span>' if author.bot else ""
        staff = author.id not in owners and not author.bot
        embeds = []
        if author.bot and message.embeds:
            first = message.embeds[0]
            if first.author and first.author.name:
                name = first.author.name
                avatar_url = str(first.author.icon_url or avatar_url)
                staff = True
                if name.startswith("[Anonymous]") or name == "Support Team":
                    badge = '<span class="badge anonymous">ANONYMOUS</span>'
                elif first.title == "📝 Internal Note":
                    badge = '<span class="badge note">INTERNAL NOTE</span>'
                elif "User ID:" in (first.footer.text or ""):
                    staff = False
                    badge = ""
                else:
                    badge = '<span class="badge">STAFF</span>'
        for embed in message.embeds:
            title = f'<div class="embed-title">{escape(embed.title)}</div>' if embed.title else ""
            description = f'<div class="content">{escape(embed.description)}</div>' if embed.description else ""
            fields = ''.join(f'<div class="field"><b>{escape(field.name)}</b><br>{escape(field.value)}</div>' for field in embed.fields)
            footer = f'<div class="embed-footer">{escape(embed.footer.text)}</div>' if embed.footer and embed.footer.text else ""
            if title or description or fields:
                embeds.append(f'<div class="embed">{title}{description}{fields}{footer}</div>')
            for media in (embed.image, embed.thumbnail):
                if media and media.url and not any(str(a.url) == media.url for a in message.attachments):
                    url = safe_url(media.url)
                    if url:
                        embeds.append(f'<div class="external"><a href="{url}" target="_blank" rel="noopener noreferrer">Open linked image</a> · External media</div>')
        attachments = []
        for attachment in message.attachments:
            attachments.append(await attachment_card(attachment))
            attachment_count += 1
        timestamp = message.created_at.strftime("%H:%M UTC")
        initial = escape(name[:1].upper())
        picture = await avatar_data(avatar_url, avatars)
        if picture:
            initial = f'<img src="{picture}" alt="{escape(name, quote=True)}" style="width:100%;height:100%;object-fit:cover">'
        records.append(f'<article class="message {"staff" if staff else ""}"><div class="avatar">{initial}</div><div class="msg-body"><div class="msg-header"><span class="username">{escape(name)}</span>{badge}<time class="timestamp">{timestamp}</time></div><div class="content">{escape(content)}</div>{"".join(embeds)}{"".join(attachments)}</div></article>')
        count += 1
    name = escape(channel.name)
    guild_name = escape(channel.guild.name)
    title = escape(str(ticket_id))
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; media-src data:; base-uri 'none'; form-action 'none'"><title>#{name} · {title}</title><style>{STYLE}</style></head><body><div class="app"><aside class="sidebar"><div class="server">{guild_name}</div><div class="section">Ticket archive</div><div class="channel"><span class="hash">#</span>{name}</div><p class="sidebar-note">A saved copy of this support conversation.<br><br>Attachments are included in this file and can be downloaded without opening Discord.</p></aside><main><header class="topbar"><strong><span class="hash">#</span>{name}</strong><small>Ticket {title}</small></header><section class="intro"><div class="channel-icon">#</div><h1>{name}</h1><p>Support conversation in {guild_name}</p><div class="metadata"><span>Participants <b>{escape(owners_text)}</b></span><span>Closed by <b>{escape(closer_display)}</b></span><span><b>{count}</b> messages · <b>{attachment_count}</b> attachments</span></div><div class="reason">Closure reason: {escape(reason)}</div></section><section class="messages">{"".join(records)}</section><footer class="end">End of transcript · {datetime.datetime.now(datetime.timezone.utc).strftime('%d %B %Y, %H:%M UTC')}</footer></main></div></body></html>'''
    data = html.encode("utf-8")
    limit = getattr(channel.guild, "filesize_limit", 10 * 1024 * 1024)
    if len(data) > limit:
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(f"transcript_{ticket_id}.html", data)
        if archive.tell() <= limit:
            archive.seek(0)
            return discord.File(archive, filename=f"transcript_{ticket_id}.zip")
        raise TranscriptAttachmentError(f"The complete transcript exceeds the server upload limit of {format_size(limit)}, even when compressed. The ticket has been kept; its attachments need to be archived before closing.")
    return discord.File(io.BytesIO(data), filename=f"transcript_{ticket_id}.html")
