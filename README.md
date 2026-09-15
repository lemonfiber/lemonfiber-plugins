# lemonfiber-plugins

The registry: where a plugin is registered to be found.

**It is not a dependency.** Publishing a plugin needs nothing beyond a git
repository — the registry is a convenience and a review mechanism, and an author
who never registers still has a working, installable plugin.

**It is not a mirror.** It records *where* a plugin is, never a copy of one. The
plugin's own repository owns its manifest, its recorded responses and its
proofs; a registry holding those would be a second source of truth for something
that already has one.

Being filled out now — how to register, what CI checks on a registration, and
the entries for the plugins that exist.
