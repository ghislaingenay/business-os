"""Domain exceptions for the deduplication service (TD-003 §7)."""


class DedupError(Exception):
    """Base exception for deduplication failures."""


class HashCalculationError(DedupError):
    """Raised when SHA-256 hashing fails (TD-003 §7: abort upload, return 500)."""


class DedupDatabaseUnavailableError(DedupError):
    """Raised when the hash lookup query fails or times out (TD-003 §7: return 503,
    no degradation — unlike Redis, there's no further fallback tier below the database).
    """
