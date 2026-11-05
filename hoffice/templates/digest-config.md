---
# Copy to <instance>/digests/<digest>/DIGEST.md.
digest: <directory name under digests/>
title: "<Display name> digest"
cadence: daily             # daily | weekly
timezone: UTC
baseline_lookback_days: 7
max_lookback_days: 14
rolling_days: 14           # Maximum number of dated digests in the rolling page.
open_pr_when_quiet: false
draft_pr: true            # false opens the PR ready for review; absent defaults to true.

# Running publication. Only this slug may be authorized for unattended writes.
slug: digest-<digest>
url: null
first_published: null
# The publisher extension defines these settings; the engine passes them unchanged.
publisher: {}

# JavaScript regexes without /delimiters/ or flags. Single quotes keep backslashes
# literal. Replace or extend this list with identifiers from configured sources.
link_patterns:
  - kind: PR or issue number
    pattern: '(?<![\w/&])#\d+\b'
  - kind: bare URL
    pattern: 'https?://[^\s)>\]]*[^\s)>\].,;:!?]'

projects:
  - name: <directory under projects/>
    label: "<Display name>"

# Per-kind settings are defined only by extensions/sources/<kind>.md.
# Remove unused kinds. A configured kind without an extension is a coverage gap.
# Extensions define their own source identifiers, searches, filters, repos,
# watch paths/keywords, and markers. No credentials belong here.
sources:
  - kind: chat
    settings: {}
  - kind: documents
    settings: {}
  - kind: tracker
    settings: {}
  - kind: code-host
    settings: {}
---

# Digest configuration: <digest>

Explain why these sources were chosen, which private sources may be summarized, and any special handling. Document settings through the corresponding source extension rather than assuming a system. Registered documents come from project DOCS.md; exclude local access and this digest's own publication.
