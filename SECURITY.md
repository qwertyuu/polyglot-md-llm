# Security Policy

PMD executes notebook cells as local subprocesses with the invoking user's
permissions. It is not a sandbox. Treat every `.pmd` file, cell output, rendered
artifact, and agent request as untrusted until reviewed.

## Supported versions

Security fixes are provided for the latest release. Older versions may receive
fixes when a patch can be backported safely.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability reporting for this repository:

https://github.com/qwertyuu/polyglot-md-llm/security/advisories/new

Include the affected version, platform, reproduction steps, impact, and any
suggested mitigation. Please avoid accessing data that is not yours and give
maintainers a reasonable opportunity to investigate before public disclosure.

## Security boundary

The local runner does not enforce filesystem, network, or environment isolation.
Capability declarations make requirements inspectable; they do not create an
OS-level security boundary. Execution through the agent protocol still requires
an explicit host authorization signal.
