from dedup.exceptions import DedupDatabaseUnavailableError, DedupError, HashCalculationError


def test_hash_calculation_error_is_a_dedup_error() -> None:
    assert issubclass(HashCalculationError, DedupError)


def test_dedup_database_unavailable_error_is_a_dedup_error() -> None:
    assert issubclass(DedupDatabaseUnavailableError, DedupError)
