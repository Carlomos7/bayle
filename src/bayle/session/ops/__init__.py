"""The operations the program registers on the default registry, one module per page. Importing this package
registers them all (the API and the window's session do)."""

from bayle.session.ops import activity, profile_transfer

__all__ = ["activity", "profile_transfer"]
