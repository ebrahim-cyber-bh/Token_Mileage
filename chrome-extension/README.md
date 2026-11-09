# Claude usage, quietly

A slim usage line inside the bottom of Claude's message composer, with © By Alna directly below the message box. Session and weekly percentages, longer warm orange progress bars, and reset countdowns align to the right. A second usage section appears below Projects in the expanded left sidebar, sharing the same live reading. No floating panel, toolbar popup, ads, contact links, or tracking. Adapts to light and dark themes through inherited text color.

## Install in Chrome — 5 simple steps

Use Chrome on a computer. No Python, API key or desktop widget is needed.

1. [Download the extension ZIP](https://token-mileage.ebrahim-alnasser.com/downloads/token-mileage-chrome-extension.zip). Extract it into a folder you will keep, such as `Documents/Token-Mileage-Chrome`. If using the source repository, use its `chrome-extension/` folder instead.
2. Paste `chrome://extensions` into Chrome's address bar and press Enter.
3. Turn on **Developer mode** at the top right.
4. Click **Load unpacked** and select the extracted folder containing `manifest.json`. Choose **Select Folder** or **Open**. Select the folder, not the ZIP.
5. Open [Claude.ai](https://claude.ai/), sign in and refresh the page. Usage appears inside the bottom of the message box, with © By Alna below it, and under Projects in the expanded sidebar.

Keep the extracted folder in place. If usage appears twice, disable the other Claude usage extension.

**Update:** extract the latest ZIP into the same folder, replacing the old files. Open `chrome://extensions`, click this extension's reload button, then refresh every open Claude tab.

**Remove:** open `chrome://extensions`, find the extension and click **Remove**.

### Can it install automatically?

A normal website cannot silently install a Chrome extension. This download requires the manual steps above. A future Chrome Web Store listing would offer **Add to Chrome** and automatic updates, but the user would still confirm the initial installation. Administrators can configure automatic installation for managed work or school browsers; that is separate from personal Chrome setup.

Official guides: [load an unpacked extension](https://developer.chrome.com/docs/extensions/get-started/tutorial/hello-world#load-unpacked), [managed automatic installation](https://support.google.com/chrome/a/answer/6306504).

The source checkout includes `preview.html` with labeled sample data.

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
