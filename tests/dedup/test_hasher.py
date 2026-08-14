import hashlib

from dedup.hasher import hash_bytes, hash_stream


async def _async_chunks(chunks: list[bytes]):
    for chunk in chunks:
        yield chunk


def test_hash_bytes_matches_known_sha256_vector() -> None:
    # SHA-256("") — a well-known test vector.
    assert hash_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_hash_bytes_matches_stdlib_hashlib() -> None:
    content = b"hello world" * 1000

    assert hash_bytes(content) == hashlib.sha256(content).hexdigest()


async def test_hash_stream_matches_hash_bytes_for_same_content() -> None:
    content = b"hello world" * 1000

    streamed = await hash_stream(_async_chunks([content[:5000], content[5000:]]))

    assert streamed == hash_bytes(content)


async def test_hash_stream_handles_empty_stream() -> None:
    assert await hash_stream(_async_chunks([])) == hash_bytes(b"")


async def test_hash_stream_and_hash_bytes_differ_for_different_content() -> None:
    assert await hash_stream(_async_chunks([b"a"])) != hash_bytes(b"b")
