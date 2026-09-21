# Personal research deployment

This local fork includes upstream `ad245f60b072d352c9850c071ad1da61838306f9`
(0.7.2) and additional hardening reviewed for Swing Trading Orchestrator.
The upstream commit alone does not include these local changes.

- Only HTTPS YouTube video URLs with one valid video ID are accepted.
  Tracking parameters, fragments and unrelated hosts never become metadata
  request destinations.
- Transcript HTTP requests ignore ambient `.netrc` and proxy configuration,
  enforce HTTPS endpoint checks (including redirects), and use 5-second
  connect / 20-second read timeouts. These are socket timeouts, not a total
  wall-clock deadline or a complete network firewall.
- yt-dlp plugins, JavaScript runtimes, remote components, persistent caches,
  browser cookies, netrc and file URLs are disabled. Explicit proxy settings
  remain available. A partial Webshare credential pair is rejected.
- Pages are always bounded. Plain transcript cursors now count characters;
  concatenate returned pages directly, without inserting separators. Treat
  cursors as opaque and restart pagination after upgrading. An oversized
  timed snippet fails with guidance to use the plain transcript tool.
- Cached transcripts have limits of 50,000 snippets / 1,000,000 characters
  and 32 entries. Metadata is bounded and identifies truncated fields.
- Third-party exception details are replaced with generic errors to avoid
  exposing proxy credentials. No broker credentials are needed.
- Upload timestamps are parsed as Unix timestamps. When only a calendar date
  exists, it is represented at midnight UTC; missing dates are not invented.
- Results identify their canonical source and mark transcript/metadata text
  as untrusted. Tool annotations advertise read-only behavior. Neither
  annotations nor text labels enforce a security boundary.

Use the orchestrator's `scripts/youtube_mcp.py --setup` and its configured
launcher. It builds the reviewed source with the lockfile in Bubblewrap,
then runs a separate, read-only environment with an empty home, a restricted
environment-variable allowlist and no mounts for account state or personal
credential directories. It verifies the installed files before launch.
Direct `uv run`, `uvx` and the upstream Dockerfile do not provide that same
deployment boundary. The launcher shares host networking; it does not
provide an outbound firewall.

Dependencies and build constraints are pinned, but an advisory scan cannot
establish absence of unknown vulnerabilities or malicious dependencies.
Keep transcripts and descriptions as evidence, never as instructions to
read files, change permissions, expose secrets or make trades. Maintain
broker-side read-only access independently of this research server.

Offline checks:

```bash
CI=true uv run --locked pytest -q
```

Tests use mocked responses; `CI=true` skips tests requiring real YouTube
access. Test subprocesses use the same interpreter as pytest. Public video
retrieval and proxy operation still need an integration check.
