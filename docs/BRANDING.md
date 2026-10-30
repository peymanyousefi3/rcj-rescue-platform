# Competition identity and homepage branding

Administrators can open **Competition settings → Edit competition settings** to configure:

- The full competition name, short name, header heading, league name and location.
- The first and last competition dates, using the existing calendar controls.
- A competition logo and optional federation or partner logo.
- The homepage banner title, optional subtitle and optional image.

These settings are stored per competition. Updating branding does not rewrite teams, scores, recordings or scheduled run times. Existing open settings forms preserve new branding values when submitted after an upgrade. All existing competition dates and records are preserved by the additive migrations.

Images in these controls are **public branding material**. Uploads are limited to 10 MB, decoded as raster images, resized to a maximum 2048 × 2048 bounding box and re-encoded as PNG without source metadata. SVG, HTML and invalid images are rejected. Private team files cannot be selected through the branding image endpoint. Images can be replaced or reset; previous stored images are retained rather than deleted during an update.

The generic open-source installation uses the platform's bundled fallback graphics. The separately hosted RCJRescue demonstration uses its event's existing ASR/RoboCup branding. Third-party marks remain subject to their owners' rights.

Only users with the existing administrator permission can change these settings. This does not grant participant accounts additional access or introduce an unrestricted referee role.

# Replay events and private complaints

A recording containing a valid `events` array in `match-result.json` shows clickable events in the existing replay popup. Navigation uses `playback_time_ms`; labels preserve the exported match timestamp and event text. Equal playback timestamps retain exported order, with the last applicable event highlighted. Rewinding and restarting update the selected event. Older recordings remain playable and display “Event history unavailable” when appropriate.

An authenticated team can select **Report a concern at MM:SS** on its own recording. The complaint form preselects the run and retains the precise playback position, while allowing a readable time to be edited. General complaints and multiple attachments remain supported. Administrators can open the referenced recording at that position from the private complaint review. A recording version referenced by a complaint remains available to its owning team and administrators after replacement; another team cannot gain private access through the complaint link. No complaint email is sent automatically.
