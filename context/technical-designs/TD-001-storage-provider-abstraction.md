# TD-001: Storage Provider Abstraction

Status: Not Started
Owner: TBD
Created: 2026-08-11
Last Updated: 2026-08-11

Feature Spec: [FEAT-001 - Storage Provider Abstraction](../features/FEAT-001-storage-provider-abstraction.md)

---

# 1. Overview

## Summary

Adapter pattern implementation for storage backends with abstract interface, AWS S3 and GCS implementations, factory-based instantiation, and consistent error handling across providers.

## Goals

- Zero provider-specific code in service layer
- Swap providers via configuration only
- Consistent error semantics across backends

## Non-Goals

- Provider failover/circuit breaker
- Cross-provider replication

---

# 2. Architecture

## Storage Provider Interface

```python
from abc import ABC, abstractmethod
from typing import BinaryIO, Dict, Literal


class StorageProvider(ABC):
    @abstractmethod
    async def upload(self, key: str, stream: BinaryIO, metadata: Dict[str, str]) -> str:
        """Upload file, return storage key"""
        pass

    @abstractmethod
    async def download(self, key: str) -> BinaryIO:
        """Download file as stream"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete file"""
        pass

    @abstractmethod
    async def head(self, key: str) -> Dict[str, any]:
        """Get metadata without downloading (size, etag, last_modified)"""
        pass

    @abstractmethod
    async def generate_presigned_url(
        self, key: str, method: Literal["GET", "PUT"], ttl: int
    ) -> str:
        """Generate presigned URL with TTL in seconds"""
        pass
```

---

# 3. Components

## New Components

- `src/storage/provider.py` — Abstract interface
- `src/storage/s3_provider.py` — AWS S3/MinIO/R2 implementation
- `src/storage/gcs_provider.py` — Google Cloud Storage implementation
- `src/storage/factory.py` — Provider factory
- `src/storage/exceptions.py` — StorageError, NotFoundError, PermissionError

---

# 4. API Design

Factory usage:

```python
provider = StorageProviderFactory.create(config)
storage_key = await provider.upload("originals/test.jpg", file_stream, {"mime_type": "image/jpeg"})
```

---

# 5. Implementation Phases

## Phase 1: S3 + Interface (PR1)

- Abstract interface, S3 implementation, factory, tests

## Phase 2: GCS Support (PR2)

- GCS implementation, multi-provider tests

---

# 6. Security Considerations

- Credentials from environment/IAM role (never hardcoded)
- Presigned URLs use provider's signature mechanism
- Object ACLs configurable per provider

---

# 7. Deployment Notes

**Config Example (S3)**:

```bash
STORAGE_PROVIDER=s3
S3_BUCKET=uploads
S3_REGION=us-east-1
S3_ENDPOINT=https://s3.amazonaws.com  # or MinIO endpoint
```

**Config Example (GCS)**:

```bash
STORAGE_PROVIDER=gcs
GCS_BUCKET=uploads
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```
