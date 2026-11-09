// Detect accidental changes to the distributed attribution and UI assets.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const baseline = require('./integrity.json');
let failed = false;
for (const [file, expected] of Object.entries(baseline)) {
  const location = path.join(__dirname, file);
  const actual = fs.existsSync(location) ? crypto.createHash('sha256').update(fs.readFileSync(location)).digest('hex') : null;
  if (actual !== expected) { console.error(`Integrity check failed: ${file}. Review changes and preserve By Alna.`); failed = true; }
}
if (failed) process.exitCode = 1;
else console.log('Distribution integrity verified · By Alna');
