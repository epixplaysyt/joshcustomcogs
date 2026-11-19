import io
from urllib.parse import urlsplit

import aiohttp
from PIL import Image

import discord


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MAX_IMAGE = 10 * 1024 * 1024
CDN_HOSTS = {"cdn.discordapp.com", "media.discordapp.net"}


def image_url(proof):
    parts = urlsplit(proof)
    parts.port
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and not parts.username and not parts.password and parts.path.lower().endswith(IMAGE_EXTENSIONS)


def format_proof_link(proof):
    if not proof or proof == "None Provided":
        return "None Provided"
    try:
        parts = urlsplit(proof)
        parts.port
    except ValueError:
        return proof
    path = parts.path.strip("/").split("/")
    if parts.hostname in {"discord.com", "ptb.discord.com", "canary.discord.com", "discordapp.com"} and len(path) in {3, 4} and path[0] == "channels" and all(p.isdigit() for p in path[1:]):
        label = "Message" if len(path) == 4 else "Channel"
        return f"[{label}]({proof}) in <#{path[2]}> (server `{path[1]}`)"
    display = f"<{proof}>" if parts.scheme in {"http", "https"} else proof
    return display


async def prepare_proof_delivery(proof):
    display = format_proof_link(proof)
    try:
        parts = urlsplit(proof)
        port = parts.port
    except ValueError:
        return display, None
    if parts.scheme == "https" and parts.hostname in CDN_HOSTS and port in {None, 443} and (image_url(proof) or parts.path.startswith("/attachments/")):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(proof, allow_redirects=False) as response:
                    if response.status != 200 or (response.content_length and response.content_length > MAX_IMAGE):
                        return display, None
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE:
                            return display, None
                    with Image.open(io.BytesIO(data)) as picture:
                        extension = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}.get(picture.format)
                        picture.verify()
                    if not extension:
                        return display, None
                    filename = "evidence" + extension
                    return display, discord.File(io.BytesIO(data), filename=filename)
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError, Image.DecompressionBombError):
            pass
    return display, None


def add_proof_field(embed, proof, display, file):
    embed.add_field(name="Proof / Evidence", value=display[:1024], inline=False)
    if file and file.filename.lower().endswith(IMAGE_EXTENSIONS):
        embed.set_image(url=f"attachment://{file.filename}")
    else:
        try:
            if image_url(proof):
                embed.set_image(url=proof)
        except ValueError:
            pass
