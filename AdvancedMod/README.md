Advanced moderation
===================

`ban` replaces `strictban`. Set `allow_appeals` to false for an unappealable ban; this requires Manager clearance. Normal ban approval levels still apply.

The duration field accepts free text:

| Input | Duration |
| --- | --- |
| `6 months`, `6mo` | Six calendar months |
| `14 days`, `14d` | Fourteen days |
| `12 hours`, `12h` | Twelve hours |
| `30 minutes`, `30m` | Thirty minutes |
| `1h30m` | One hour and thirty minutes |
| `permanent` | No automatic expiry |

`m` means minutes. `mo` means months. Calendar months and years are calculated from the time the ban is issued. A bare number retains the existing interpretation of days.

DM appeals
----------

Configure the review channel with `[p]advmodset appealschannel #appeals`. Users then receive an **Appeal punishment** button in DMs for appealable warnings, timeouts, kicks and bans. The button opens a form, and its answers are posted to the configured channel with **Accept appeal** and **Deny appeal** buttons. Only Managers and higher can accept or deny appeals.

- `[p]advmodset appealquestion <1–5> <question>` changes a question or appends the next question. Questions are limited to 45 characters; answers are limited to 1,000 characters each.
- `[p]advmodset appealdelay 0` enables immediate appeals. A custom duration sets a waiting period instead.
- `[p]advmodset rejoinchannel #welcome` configures the invitation source for accepted kick appeals.

Accepting removes the original warning, clears the original timeout or unbans the user. A kick cannot automatically put someone back into a Discord server, so an accepted kick appeal sends a single-use rejoin invitation valid for 24 hours. Denials notify the user without changing the punishment. A failed reversal leaves the appeal pending. Staff are told when a DM cannot be delivered.

Forms and reviews survive restarts. One appeal can be submitted per punishment. A superseded punishment or a ban/timeout changed by another moderation tool cannot be removed by an older appeal. Existing external appeal links remain available only for legacy punishment records; new cases use the DM forms.

After updating, reload the cog and enable/sync the updated commands through Red. This removes the old `strictban` application command. Existing punishments are not automatically converted into new appeal cases.

Evidence
--------

Image evidence appears inside moderation and request embeds. Discord image attachments are copied into the log when available (up to 10 MiB); signed attachment URLs are supported. Other image links show a preview, and Discord message/channel links show the channel and server. Original evidence links remain visible.

Class I and higher can use `[p]addevidence <case number or log message link/ID> <evidence link>` or `/addevidence` with an attachment. For prefix commands, upload the attachment with the command. Log links/IDs must refer to the configured AdvancedMod log channel in the current server. Staff must be able to view the destination log channel.

Additional evidence is posted as a reply to the original log with the submitting staff member's identity. For Red cases, the reason also gains the evidence and reply link. New AdvancedMod logs show their Red case number when case creation is enabled. Existing cases can use their Red log message; older AdvancedMod logs can be referenced by message link or ID. Original messages and attachments are preserved.
