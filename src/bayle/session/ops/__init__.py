"""The operations the program registers on the default registry, one module per page. Importing this package
registers them all (the API and the window's session do)."""

from bayle.session.ops import activity, mods, mods_entries, mods_profile

__all__ = ["activity", "mods", "mods_entries", "mods_profile"]
