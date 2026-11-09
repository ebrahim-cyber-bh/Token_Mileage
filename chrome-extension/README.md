# Claude usage, quietly

A slim usage line inside the bottom of Claude's message composer, with © By Alna directly below the message box. Session and weekly percentages, longer warm orange progress bars, and reset countdowns align to the right. A second usage section appears below Projects in the expanded left sidebar, sharing the same live reading. No floating panel, toolbar popup, ads, contact links, or tracking. Adapts to light and dark themes through inherited text color.

## Install or update

1. Download this repository and select its `chrome-extension/` folder (or extract `token-mileage-chrome-extension.zip`). Open `chrome://extensions` and enable Developer mode.
2. If already installed, click the extension's reload arrow, then refresh every open Claude tab. Otherwise choose Load unpacked and select the folder containing `manifest.json`.
3. Reload your Claude tab. Disable the old third-party usage extension to avoid duplicate displays.

No build required. The source checkout includes `preview.html` with labeled sample data.

## Behavior and privacy

The line attaches inside the visible composer shell and reattaches as Claude navigates between chats. The inline line stays hidden where there is no supported composer; sidebar usage remains available where Projects is visible. The sidebar section hides when the navigation is collapsed. Requests refresh once per minute while the page is visible, on returning to the tab, or when pressing the refresh icon.

Only requests Claude's `/api/organizations` and `/api/organizations/{uuid}/usage` using the existing signed-in session. Does not read message contents, extract session tokens, store usage, or send data to third parties. Requires host access only to claude.ai. Multiple organizations use Claude's `lastActiveOrg`; if unavailable, the line asks you to choose one rather than guessing.

Claude's undocumented endpoint and composer structure can change. Errors show a message rather than invented usage; any previous reading is explicitly identified. Live account integration needs verification in signed-in Chrome.

Run `node tests.cjs` to check formatting, connection errors, account selection, and composer attachment.

Endpoint reference: https://github.com/pzfreo/claude-usage . Composer structure reference: https://github.com/simonlinuxcraft/claude-ai-desktop-app/blob/main/CHANGELOG.md . Original implementation; no source copied.

## Attribution

By Alna. The TokenMeter logo uses the supplied orange sunburst and By Alna tagline and appears in Chrome's extension list. In-page credits use text only. Reload the extension and Claude tab to see it.

Keep the visible credit in both displays. `AGENTS.md` and `CLAUDE.md` provide attribution instructions for cooperating assistants. A runtime check rejects a changed credit string, and `node verify-integrity.cjs` verifies the distributed files against SHA-256 checksums. After legitimate reviewed updates, the maintainer must update `integrity.json`.

These are local tamper checks, not copy protection: someone with source access can remove the checks, replace the checksum file, or ignore assistant instructions. They do not prevent copying or guarantee that another AI refuses changes.
