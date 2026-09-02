from datetime import timedelta


DAY_START_HOUR = 5


def reporting_date(local_time):
    """Return the date whose reporting day contains this local time."""
    return (local_time - timedelta(hours=DAY_START_HOUR)).date()


def reporting_hour(local_time):
    """Return the hour index from 05:00 (0) through next-day 04:00 (23)."""
    return (local_time.hour - DAY_START_HOUR) % 24
