# VS Code workspace

Open [Librarium.code-workspace](../Librarium.code-workspace) in the actual checkout.
Built-in Git provides live diffs, staging, history and branch review. Use Source
Control for uncommitted changes and the graph/history for committed revisions.

For a remote checkout, use Microsoft's Remote - SSH extension with the operator's
privately configured SSH host and authentication. Open the repository directory
and its workspace file in the remote window. Verify the remote indicator, `pwd`,
Git branch/commit and local changes. A different clone cannot show this checkout's
uncommitted edits. [Microsoft's Remote SSH guide](https://code.visualstudio.com/docs/remote/ssh)
describes connection setup. Never place actual SSH destinations in public docs.

Keep Claude and Codex access available. Copilot is not a required extension; do
not add it to automatic installation flows. Resolve bootstrap failures through
client configuration and current logs, keeping those logs private. Do not delete
an editor server or alter built-in extensions as a shortcut.

[Development](development.md) owns runnable project checks. Machine-specific
tool locations and current handoff live in [private context](agent-environment.md).
