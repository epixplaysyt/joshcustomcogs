import asyncio
import ipaddress
from urllib.parse import urlsplit

from redbot.core import commands

from .viewer import valid_origin


class SetupCancelled(Exception):
    pass


async def guided_setup(cog, ctx):
    if cog._setup_running:
        return await ctx.send("A viewer setup is already running. Finish it or type cancel in its channel first.")
    cog._setup_running = True

    async def ask(prompt):
        await ctx.send(prompt + "\nReply within 3 minutes, or type `cancel` to stop.")
        message = await cog.bot.wait_for("message", timeout=180, check=lambda m: m.author.id == ctx.author.id and m.channel.id == ctx.channel.id)
        value = message.content.strip()
        if value.lower() == "cancel":
            raise SetupCancelled
        return value

    try:
        await ctx.send("Viewer setup: this bot hosts the webpage on its own machine. You will need access to that machine's network settings and a Discord application. A domain is optional. Do not post client secrets in this channel. Settings are saved only after the final confirmation.")
        while True:
            value = await ask("Which channel in this staff server contains the transcript archives? Mention it or enter its ID.")
            try:
                channel = await commands.TextChannelConverter().convert(ctx, value)
            except commands.BadArgument:
                await ctx.send("That channel could not be found. Try a channel mention or ID.")
                continue
            permissions = channel.permissions_for(ctx.guild.me)
            if channel.guild.id != ctx.guild.id or not permissions.view_channel or not permissions.read_message_history:
                await ctx.send("Choose a channel in this server where the bot has View Channel and Read Message History.")
                continue
            break
        while True:
            mode = await ask("How will staff reach the viewer?\n`1` — Localhost or an SSH tunnel; no domain needed.\n`2` — HTTP using the host's IP on a trusted network; no domain needed.\n`3` — HTTPS through a reverse proxy, using an IP or hostname.")
            if mode in {"1", "2", "3"}:
                break
            await ctx.send("Reply with 1, 2 or 3.")
        while True:
            value = await ask("Which port should the bot listen on? Enter `8088` for the usual choice (allowed: 1024–65535).")
            if value.isdigit() and 1024 <= int(value) <= 65535:
                port = int(value)
                break
            await ctx.send("Enter a port between 1024 and 65535.")
        example = {"1": f"http://localhost:{port}", "2": f"http://203.0.113.10:{port}", "3": "https://tickets.example.com"}[mode]
        while True:
            value = await ask(f"Enter the full address staff will open, for example `{example}`. Replace example addresses with your own. Include the public port when needed, without a path.")
            try:
                origin = valid_origin(value, allow_http=mode == "2")
                parsed = urlsplit(origin)
                if mode == "1" and (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}):
                    raise ValueError("Local mode needs an HTTP localhost or loopback address.")
                if mode == "2" and (parsed.scheme != "http" or ipaddress.ip_address(parsed.hostname).is_loopback):
                    raise ValueError("IP mode needs an HTTP address with a non-loopback IP.")
                if mode == "3" and parsed.scheme != "https":
                    raise ValueError("Proxy mode needs an HTTPS address.")
                if mode in {"1", "2"} and (parsed.port or 80) != port:
                    raise ValueError("For direct access, the address port must match the listener port.")
                break
            except ValueError as exc:
                await ctx.send(str(exc))
        if mode == "1":
            loopback = "[::1]" if urlsplit(origin).hostname == "::1" else "127.0.0.1"
            await ctx.send(f"The listener will use {loopback}:{port} on the bot machine. For access from another computer, create an SSH tunnel, for example `ssh -L {port}:{loopback}:{port} user@BOT_HOST`, then open {origin}. Each staff member needs access to the tunnel.")
        elif mode == "2":
            await ctx.send(f"The listener will bind to all interfaces on port {port}. Allow that port only from trusted staff networks in your host firewall; map the port on your router if needed. HTTP sends login session cookies without encryption. Use HTTPS for access over untrusted networks.")
        else:
            await ctx.send(f"Configure your reverse proxy on the bot machine to serve {origin} with a valid TLS certificate and forward to http://127.0.0.1:{port}. Allow public HTTPS traffic to the proxy. Keep the bot's listener private. Configure proxy logs to omit OAuth callback query strings and cookies. The cog cannot install certificates or configure your proxy/firewall.")
        await ctx.send(f"Open https://discord.com/developers/applications and create or select an application. In OAuth2, register this exact redirect URL: `{origin}/oauth/callback`. Save it. Only the identify scope is used; staff still need Manage Messages and access to the archive channel.")
        await ctx.send(f"In a private channel or DM, use `{ctx.clean_prefix}set api modmailerviewer client_id YOUR_CLIENT_ID client_secret YOUR_CLIENT_SECRET`. Get both values from the application's OAuth2 page. Never paste the secret into this setup conversation.")
        while True:
            answer = await ask("After saving the redirect and credentials and preparing the network settings, reply `ready` to check credentials and review setup.")
            if answer.lower() != "ready":
                await ctx.send("Reply ready when those steps are complete, or cancel to stop.")
                continue
            tokens = await cog.bot.get_shared_api_tokens("modmailerviewer")
            if tokens.get("client_id") and tokens.get("client_secret"):
                break
            await ctx.send("The client ID or client secret is missing. Set both with Red's private API token command, then reply again.")
        answer = await ask(f"Start the viewer at {origin}, using {channel.mention} and listener port {port}? Reply `yes` to save and start" + (", accepting unencrypted HTTP access." if mode == "2" else "."))
        if answer.lower() != "yes":
            raise SetupCancelled
        started = await cog.configure.callback(cog, ctx, channel, origin, port, mode == "2")
        if not started:
            return
        await ctx.send(f"Open {origin} and choose Sign in with Discord. Test with a staff account. If the page cannot be reached, check the firewall, port forwarding or proxy; if Discord rejects login, check the exact redirect URL and application credentials. Local archives expire after 28 days; Discord channel logs remain available.")
    except (asyncio.TimeoutError, SetupCancelled):
        await ctx.send("Viewer setup cancelled. No setup settings were saved.")
    finally:
        cog._setup_running = False
