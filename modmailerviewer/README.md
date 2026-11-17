Modmail archive viewer
======================

A small aiohttp server hosted by the bot. The sidebar lists up to 50 recent transcript archives from the configured Discord log channel. Selecting one opens its conversation, attachments and profile pictures. HTML and ZIP archives from Ticketmail are supported. No new copy of the transcript database is stored on the host.

Setup
-----

1. Install and load `modmailerviewer` alongside Ticketmail.
2. Create a Discord application in the Discord Developer Portal. In OAuth2, add an exact redirect URL such as `https://tickets.example.com/oauth/callback`.
3. Set the application credentials using Red's owner-only API token setup: `[p]set api modmailerviewer client_id YOUR_CLIENT_ID client_secret YOUR_CLIENT_SECRET`. Use a private channel or DM for credentials.
4. In the **staff server**, run `[p]viewerset setup #ticket-archives https://tickets.example.com 8088`.
5. Reverse-proxy the HTTPS domain to `127.0.0.1:8088` on the bot host. The hostname and certificate must be configured by the server operator. The cog binds to loopback and does not provision DNS or TLS.

For local development only, `http://localhost:8088` is accepted as the public URL. Public deployments require HTTPS. `[p]viewerset stop` stops the listener, invalidates sessions and disables automatic startup until setup is run again.

Access
------

Visitors must sign in with Discord. Every page, transcript and download checks current staff-server membership, Manage Messages permission, and View Channel/Read Message History permission in the archive channel. Removing staff access takes effect on the next request. Discord failures deny access rather than using a stale permission snapshot. A transcript's presence in the archive channel defines its visibility; private transcripts sent only to the closer's DMs do not appear here. Use a dedicated staff archive channel and do not mix records with different audiences in it.

Sessions expire after one hour and are cleared when the cog unloads. The viewer uses browser-bound OAuth state and PKCE, HTTP-only cookies, same-site cookies, no-store responses and a sandboxed transcript frame. OAuth access tokens are used only to fetch identity and are not retained. Login URLs, cookies and callback query strings are not written to web access logs.

The recent list searches the newest 500 archive-channel messages for transcript files. Downloads are limited to 25 MiB. ZIPs must contain one root-level `transcript_*.html` and are read in memory without extracting files to disk.

Profile pictures are embedded in newly generated Ticketmail transcripts. Existing transcripts keep whatever images they originally contained; archives that only stored initials cannot recover historical profile pictures automatically. External images in older archives may no longer be available.
