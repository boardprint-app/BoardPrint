# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately through
GitHub's private vulnerability reporting: go to
[github.com/boardprint-app/BoardPrint/security](https://github.com/boardprint-app/BoardPrint/security)
and click **Report a vulnerability**.

Include what you found, the BoardPrint version and OS, and the steps or a proof of concept to
reproduce it. The conversation continues in the private advisory. When a fix is released, the
advisory can be published, crediting you if you wish.

## Supported versions

BoardPrint is an early preview (0.x). Security fixes go to the latest release only.

## Scope

Reports about these parts are especially welcome:

- **The local backend.** The desktop shell starts the Python backend on
  `127.0.0.1` with a random port and a per-session token. Every `/api` route and the
  WebSocket require that token, and the WebSocket only accepts pages served from the local
  machine. Anything that lets another process, a web page or another user on the machine
  drive the app without the token is in scope.
- **Pack UI isolation.** A pack's own UI runs in an `iframe` with `sandbox="allow-scripts"`
  (opaque origin, no `allow-same-origin`), served with a Content Security Policy that allows
  no network (`default-src 'none'`, `connect-src 'none'`) and loads scripts, styles, images and
  fonts only from that pack's `ui/` folder. Its messages to the app are checked and bound to
  its own block. Escaping the sandbox, reaching the network, reading the app's data or acting
  on another block or pack is in scope.
- **Pack code execution.** Pack Python code does not run in the backend: it runs in a separate
  worker process, in a packs environment separate from the app's own Python.
- **`.bppack` installation.** Before anything is installed, an archive is extracted to a
  staging folder and rejected if it has paths that leave its folder (absolute, `..`, `\`,
  `:`), links, more than one top folder, duplicate paths, or more than 50 MB; it is validated
  and test-loaded in a separate process, and the user sees a summary with the warning that it
  brings code. Bypassing any of these checks is in scope.

## Out of scope

- **Packs run with your user's permissions.** The worker process isolates the app from a
  crashing pack; it is not a security sandbox. A pack you choose to install can read and write
  your files and use the network. Install packs only from sources you trust. A malicious pack
  doing what Python code can do is not a vulnerability in BoardPrint; a pack that gets code
  run *without* the user installing it is.
- Vulnerabilities in third-party software (Autodesk Fusion and its MCP server, Claude Code,
  Python libraries a pack requests). Report those to their maintainers; tell us if BoardPrint
  makes them worse.
- The development setup (backend started by hand without `--token`, Vite dev server).
