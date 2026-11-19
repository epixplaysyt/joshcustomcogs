Modmail archive viewer
======================

A small aiohttp server hosted by the bot. The sidebar lists up to 50 recent transcript archives from the configured Discord log channel. Selecting one opens its conversation, attachments and profile pictures. HTML and ZIP archives from Ticketmail are supported. Original HTML/ZIP transcript files and their metadata are stored in a local SQLite database under the cog data directory for 28 days. New archive messages are captured automatically; the last 28 days are backfilled on startup and checked hourly. Local records expire 28 days after the Discord archive message was created, not 28 days after the last view. Expired files are removed locally and requests fall back to the Discord archive channel. Channel logs are never deleted. Authentication sessions remain temporary in-memory state.

Setup
-----

Run `[p]viewerset setup` without arguments in the staff server for the owner-only setup guide. It asks for the archive channel, hosting mode, listener port and public address, then explains network setup, the exact Discord OAuth redirect and private API token setup. It checks that credentials are present before asking for a final `yes` to save and start. Type `cancel` at any prompt; each reply has a three-minute timeout. The guide does not collect secrets in chat, install a reverse proxy, open firewall ports or verify public connectivity. If the listener cannot start, previous settings are restored.

The existing command with arguments remains available for direct configuration. Manual steps:

1. Install and load `modmailerviewer` alongside Ticketmail.
2. Create a Discord application in the Discord Developer Portal. In OAuth2, add an exact redirect URL such as `https://tickets.example.com/oauth/callback`.
3. Set the application credentials using Red's owner-only API token setup: `[p]set api modmailerviewer client_id YOUR_CLIENT_ID client_secret YOUR_CLIENT_SECRET`. Use a private channel or DM for credentials.
4. In the **staff server**, run `[p]viewerset setup #ticket-archives https://tickets.example.com 8088`.
5. Reverse-proxy the HTTPS domain to `127.0.0.1:8088` on the bot host. The hostname and certificate must be configured by the server operator. HTTPS deployments bind to loopback for a reverse proxy. Direct HTTP-by-IP deployments bind to all interfaces only after the explicit opt-in. The cog does not provision DNS or TLS.

No domain is required. For access on a trusted network using a server IP, register `http://203.0.113.10:8088/oauth/callback` with Discord and run `[p]viewerset setup #ticket-archives http://203.0.113.10:8088 8088 true`, replacing the example IP with the bot host's address. The final `true` explicitly allows unencrypted HTTP and binds the listener to all interfaces. Restrict the port with your firewall: HTTP session cookies can be intercepted on untrusted networks.

For internet access, use HTTPS with an IP address and a certificate/reverse proxy, or continue using an HTTPS hostname. A domain is optional. A loopback URL such as `http://localhost:8088` also works, including through an SSH tunnel; it does not require the HTTP opt-in. The OAuth redirect URL must exactly match the URL registered in the Discord Developer Portal. `[p]viewerset stop` stops the listener, invalidates sessions and disables automatic startup until setup is run again.

IP reverse-proxy installer
--------------------------

On an Ubuntu/Debian systemd host, `scripts/install-nginx.sh` installs nginx and current Snap Certbot, obtains a Let's Encrypt certificate for a public IPv4 address, and configures nginx to proxy HTTPS to the bot on loopback. Run it on the same machine as the bot, outside containers. Python 3 must already be installed. The host must support Snap.

Download/review the script, then preview its configuration without making changes:

```bash
bash install-nginx.sh --ip YOUR_PUBLIC_IPV4 --port 8088 --check
```

Install with:

```bash
sudo bash install-nginx.sh --ip YOUR_PUBLIC_IPV4 --email YOUR_EMAIL --port 8088
```

Replace the placeholders with your actual public IPv4 and email. The installer asks for confirmation and acceptance of Let's Encrypt's subscriber agreement. `--yes` skips that prompt for unattended installation. Private, reserved and IPv6 addresses are rejected by this installer.

Allow public TCP 80 and 443 in your firewall/router before running it; the script does not change those rules. Keep port 80 reachable for renewal and keep the bot's viewer port private. IP certificates are short-lived, so the installer enables the Snap renewal timer, installs an nginx reload hook and tests renewal. The public URL and Discord callback URL are printed after success. Complete `[p]viewerset setup` using HTTPS proxy mode and those values. Bot credentials and cog settings are not changed by the script.

Existing files under the dedicated `modmailerviewer-ip` nginx/certificate names are never overwritten. Other nginx sites remain enabled. On failure, installer-created nginx configuration and the reload hook are removed; installed packages and any issued certificate remain. Inspect the reported error and those retained files before retrying. On success, configuration is in `/etc/nginx/sites-available/modmailerviewer-ip`, certificates are in `/etc/letsencrypt/live/modmailerviewer-ip/`, and the reload hook is `/etc/letsencrypt/renewal-hooks/deploy/modmailerviewer-nginx`. Check renewal with `systemctl status snap.certbot.renew.timer`. Public reachability, a working Snap installation and live certificate issuance must be verified on the target host.

Access
------

Visitors must sign in with Discord. Every page, transcript and download checks current staff-server membership, Manage Messages permission, and View Channel/Read Message History permission in the archive channel. Removing staff access takes effect on the next request. Discord failures deny access rather than using a stale permission snapshot. A transcript's presence in the archive channel defines its visibility; private transcripts sent only to the closer's DMs do not appear here. Use a dedicated staff archive channel and do not mix records with different audiences in it.

Sessions expire after one hour and are cleared when the cog unloads. The viewer uses browser-bound OAuth state and PKCE, HTTP-only cookies, same-site cookies, no-store responses and a sandboxed transcript frame. OAuth access tokens are used only to fetch identity and are not retained. The embedded aiohttp server disables its access logs. Configure any reverse proxy to omit OAuth callback query strings and cookies from its own logs; the cog cannot control proxy logging.

The sidebar combines local records with channel logs and lists the latest 50 archives. The channel fallback searches the newest 500 archive-channel messages. Local expiry runs hourly while the cog is loaded and is also enforced on every read, so expired local records are never served. Disk files survive restarts, but expiry is enforced again at startup. Downloads are limited to 25 MiB. ZIPs must contain one root-level `transcript_*.html` and are read in memory without extracting files to disk.

Profile pictures are embedded in newly generated Ticketmail transcripts. Existing transcripts keep whatever images they originally contained; archives that only stored initials cannot recover historical profile pictures automatically. External images in older archives may no longer be available.
