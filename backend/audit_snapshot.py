"""Frozen preparation boundary: content-addressed PageTextIndex snapshots.

``prepare_run`` (CPU queue) owns every PDF handle and persists one compressed
canonical snapshot per bound position through ``BlobStore.put``. The LLM
worker only restores that snapshot via ``PageTextIndex.from_snapshot`` and
never reopens, re-extracts, or OCRs a PDF. The direct runner uses the same
encode/decode contract in memory.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from typing import Any

SNAPSHOT_SCHEMA = 1

_COMPRESS_MTIME = 0


def encode_snapshot(index: Any) -> bytes:
    """Serialize a prepared index to canonical compressed bytes."""
    snapshot = index.to_snapshot()
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(
            f"Unsupported extraction snapshot schema: {snapshot.get('schema')!r}"
        )
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return gzip.compress(encoded, mtime=_COMPRESS_MTIME)


def decode_snapshot(data: bytes) -> Any:
    """Restore a prepared index; stale/corrupt corpora raise, never refetch."""
    from audit_core import PageTextIndex

    try:
        raw = gzip.decompress(bytes(data))
    except (OSError, EOFError, ValueError) as exc:
        raise ValueError(f"Extraction snapshot is not valid gzip: {exc}") from exc
    try:
        snapshot = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Extraction snapshot is not valid JSON: {exc}") from exc
    return PageTextIndex.from_snapshot(snapshot)


def snapshot_ref(snapshot: dict[str, Any], blob_key: str, blob_sha256: str) -> dict[str, Any]:
    """Job-payload reference: key/SHA/schema only, never megabytes of text."""
    corpus_id = snapshot.get("corpus_id")
    if not corpus_id or not blob_key or not blob_sha256:
        raise ValueError("Extraction snapshot reference is incomplete")
    return {
        "snapshot_key": blob_key,
        "snapshot_sha256": blob_sha256,
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "corpus_id": corpus_id,
    }


def store_snapshot(blob_store: Any, index: Any) -> dict[str, Any]:
    """Persist one prepared index; returns the payload reference."""
    data = encode_snapshot(index)
    ref = blob_store.put(data)
    digest = hashlib.sha256(data).hexdigest()
    if ref.sha256 != digest:  # pragma: no cover - defensive, store is canonical
        raise ValueError("Blob store returned a mismatched snapshot hash")
    return snapshot_ref(index.to_snapshot(), ref.key, ref.sha256)


def load_snapshot(blob_store: Any, payload: dict[str, Any]) -> Any:
    """Fetch and verify a snapshot reference; failures are explicit prep errors."""
    key = payload.get("snapshot_key", "")
    want_sha = payload.get("snapshot_sha256", "")
    if payload.get("snapshot_schema") != SNAPSHOT_SCHEMA or not key or not want_sha:
        raise ValueError("Подготовка позиции не выполнена: снимок корпуса отсутствует")
    try:
        data = blob_store.get(key)
    except FileNotFoundError as exc:
        raise ValueError(
            "Подготовка позиции не выполнена: байты снимка корпуса "
            f"отсутствуют в хранилище ({key})"
        ) from exc
    if hashlib.sha256(bytes(data)).hexdigest() != want_sha:
        raise ValueError("Подготовка позиции не выполнена: хеш снимка корпуса не совпал")
    index = decode_snapshot(bytes(data))
    corpus_id = payload.get("corpus_id") or ""
    actual = index.to_snapshot().get("corpus_id", "")
    if corpus_id and actual != corpus_id:
        raise ValueError("Подготовка позиции не выполнена: корпус снимка не совпал")
    return index
