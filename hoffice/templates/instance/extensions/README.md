# Instance extensions

Find the hoffice engine through `$HOFFICE_HOME` and read its `docs/extensions.md` before adding an extension. If the variable is unset, read the engine path from `$HOFFICE_CONFIG_DIR/home` (`HOFFICE_CONFIG_DIR` defaults to `~/.config/hoffice`). This instance does not assume an engine checkout path.

Add only the extensions you need: `publisher.md`, `sources/<kind>.md`, `evidence.md`, `tracker.md`, `access.md`, `scheduler.md`, and `ship.md`. Each names available tools, arguments, and what to do if a tool is missing. Missing extensions are normal; engine `docs/extensions.md` defines the fallback for each.

Keep credentials out of extension files. The agent's environment holds authentication. External writes require approval for each write unless an unattended prompt explicitly authorizes the target.
