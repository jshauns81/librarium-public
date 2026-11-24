# Contributor environment

## Private context discovery

Keep credentials, host addresses, operational handoffs and audit evidence outside every checkout. An operator may set `LIBRARIUM_AGENT_CONTEXT` to a protected directory. Use mode 0700 for the directory and 0600 for its files on Unix. Private notes supply context and do not grant authority to change an installation.

## Workspace and tools

Check the repository, branch, commit and local changes before editing. Keep optional tool configuration and unpublished graph data outside Git. Resolve the provenance and revision of external references before using them. See [privacy](privacy.md) and [context hygiene](context-hygiene.md).
