Ticket assignments
==================

Ticket channels and command permissions belong to the staff server. Member role labels continue to come from the configured main server.

| Command | Action |
| --- | --- |
| `/modmail claim restrict:true` | Claim the ticket and restrict replies to its assigned staff. |
| `/modmail claim restrict:false` | Claim the ticket with ordinary staff replies enabled, or reopen replies on your existing claim. |
| `/modmail invite member:@staff` | The claimant sends a DM invitation to a staff-server member. |
| `/modmail unassign member:@staff` | The claimant removes a co-assignee or revokes an invitation. |
| `/modmail bypass` | An administrator explicitly joins a claimed ticket as a co-assignee. |

Invitations last 24 hours and must be accepted. Acceptance grants access to the ticket channel; removing an invited co-assignee restores their previous permission overwrite. Assignment and invitation data survive restarts. Claimants cannot overwrite another person's claim.

Restricted replies apply to slash replies, prefix replies, snippets and outgoing reactions. Confirmation buttons recheck the assignment before sending. Internal staff notes remain available. Administrators must use the bypass command before replying to a restricted ticket; merely holding Administrator does not automatically join the assignment. Staff operations retain runtime permission checks, while assigned members can use the reply commands without needing server-wide Manage Messages.

Transcripts
-----------

Transcripts use a compact channel layout with message times, staff labels, embed cards and download cards. Original attachment bytes are included in the HTML. Supported image, audio and video attachments have previews; every attachment also has a download link. SVG and other file types are offered as downloads rather than rendered as active content.

The archive is self-contained and does not depend on signed Discord attachment URLs. Linked external images are listed as external links instead of broken previews. If the HTML exceeds Discord's upload limit, a ZIP containing the same HTML is attempted. If an attachment cannot be read, or the complete archive still exceeds the upload limit, the ticket is kept and the failure is reported in the channel.

Reload the cog and enable/sync the new application commands through Red after updating.
