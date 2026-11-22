# Security policy

## No longer maintained

BoardPrint is **no longer maintained** and its repository is archived. v0.8.0 is the final
release: no version receives security fixes, and there is no channel to report a
vulnerability. If you maintain a fork, publish your own security policy there.

## What the app protects

These are the protections BoardPrint was built with, for anyone auditing it or carrying it on:

- **The local backend.** The desktop shell starts the Python backend on
  `127.0.0.1` with a random port and a per-session token. Every `/api` route and the
  WebSocket require that token, and the WebSocket only accepts pages served from the local
  machine.
- **Pack UI isolation.** A pack's own UI runs in an `iframe` with `sandbox="allow-scripts"`
  (opaque origin, no `allow-same-origin`), served with a Content Security Policy that allows
  no network (`default-src 'none'`, `connect-src 'none'`) and loads scripts, styles, images and
  fonts only from that pack's `ui/` folder. Its messages to the app are checked and bound to
  its own block.
- **Pack code execution.** Pack Python code does not run in the backend: it runs in a separate
  worker process, in a packs environment separate from the app's own Python.
- **`.bppack` installation.** Before anything is installed, an archive is extracted to a
  staging folder and rejected if it has paths that leave its folder (absolute, `..`, `\`,
  `:`), links, more than one top folder, duplicate paths, or more than 50 MB; it is validated
  and test-loaded in a separate process, and the user sees a summary with the warning that it
  brings code.

## What it does not protect

- **Packs run with your user's permissions.** The worker process isolates the app from a
  crashing pack; it is not a security sandbox. A pack you choose to install can read and write
  your files and use the network. Install packs only from sources you trust. A malicious pack
  doing what Python code can do is not something BoardPrint can stop.
- Vulnerabilities in third-party software (Autodesk Fusion and its MCP server, Claude Code,
  Python libraries a pack requests): report those to their maintainers.
- The development setup (backend started by hand without `--token`, Vite dev server).
