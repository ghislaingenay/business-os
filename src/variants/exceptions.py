"""Domain exceptions for the variants domain."""


class VariantGenerationError(Exception):
    """Raised when generating or persisting a file's variants fails.

    Wraps the underlying storage/image-decode failure so `worker.tasks`
    (the arq boundary) can decide whether to retry without depending on
    `shared.storage`/`shared.image` exception types directly.
    """
