"""Shared date/time helpers for BookHive business rules.

Storage stays UTC: every timestamp written to MongoDB is a UTC instant, and
nothing here changes that. Overdue status and fines, however, are calendar rules
expressed in the library's own timezone, so a UTC instant is converted to an
Asia/Kolkata calendar date before any business comparison.

The timezone is resolved from the IANA database via ZoneInfo. A fixed +05:30
offset is never applied by hand.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# IANA identifier for the library's local calendar.
LIBRARY_TIMEZONE = ZoneInfo("Asia/Kolkata")


def utc_now():
    """Current instant as timezone-aware UTC."""
    return datetime.now(timezone.utc)


def as_utc(value):
    """Normalize a datetime from MongoDB or the API to timezone-aware UTC.

    Legacy MongoDB documents hold naive datetimes that are UTC by convention,
    so those are labelled rather than shifted. An already-aware value is
    converted once, which is a no-op when it is already UTC. Anything that is
    not a datetime (missing or malformed legacy data) becomes None.
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def local_date(value):
    """Calendar date of an instant in the library timezone, or None."""
    utc_value = as_utc(value)
    if utc_value is None:
        return None
    return utc_value.astimezone(LIBRARY_TIMEZONE).date()


def today_local():
    """Today's calendar date in the library timezone."""
    return utc_now().astimezone(LIBRARY_TIMEZONE).date()


def start_of_today_utc():
    """UTC instant of local midnight today, for MongoDB range queries.

    A due date earlier than this instant fell on a local calendar date before
    today, which is exactly the condition for being overdue.
    """
    local_midnight = datetime.combine(
        today_local(), datetime.min.time(), tzinfo=LIBRARY_TIMEZONE
    )
    return local_midnight.astimezone(timezone.utc)


def days_overdue(due_date, reference=None):
    """Whole library-local calendar days a due date is past.

    A book becomes overdue only once the local calendar date is *after* the due
    date's local calendar date, so a book due today returns 0. `reference`
    defaults to now and is the return instant when settling a returned book.
    Unusable dates return 0 rather than raising, so one legacy record cannot
    break a whole listing.
    """
    due_local = local_date(due_date)
    if due_local is None:
        return 0

    reference_local = today_local() if reference is None else local_date(reference)
    if reference_local is None:
        return 0

    return max(0, (reference_local - due_local).days)


def is_overdue(due_date, status=None, reference=None):
    """True when a still-issued transaction is past due in the local calendar."""
    if status is not None and status != "Issued":
        return False
    return days_overdue(due_date, reference) > 0
