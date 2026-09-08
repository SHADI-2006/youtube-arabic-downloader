"""Shared exception types."""


class Cancelled(Exception):
    """Raised (from a progress hook or between-item check) to stop a
    running download early — a user-requested stop, not a failure."""
