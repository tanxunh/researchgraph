# ADR-002: Raw sources and immutable evidence versions

Status: Accepted for Phase 2 (2026-09-14). Extends [ADR-001](ADR-001-index-consistency.md); its SQL authority, non-ready publication, filtering and reconciliation model is retained.

## Previous model and problem

A logical document matched source_type/source_uri, then fell back to parsed content hash across unrelated sources. Versions stored metadata only. Chunk identity was document_id + normalized-text hash: duplicate paragraphs collided. Retained chunks were reassigned to the new version and obsolete chunks deleted, destroying older evidence. Mention/Relation referenced chunk IDs, while Chroma used stable_chunk_id and stored SQL version metadata.

## Decision

Use a small local content-addressed byte store and an immutable membership table:

```text
Document (logical source, current_version, pending_version, status)
  +-- DocumentVersion (monotonic number, source reference, parser/chunker identity)
        +-- DocumentVersionChunk (ordinal/page/section snapshot)
              +-- DocumentChunk (stable occurrence, immutable text/hash)
        +-- sources/aa/bb/<SHA256(raw bytes)>.blob
```

Document identity is the existing (source_type, source_uri) pair. Content equality no longer merges unrelated sources. Default text titles/file names remain convenience logical identifiers; callers should supply source_uri when different documents share a name. This is not global document identity resolution.

### Raw source lifecycle

PDF/DOCX store original upload bytes; Text stores UTF-8 bytes, TXT/Markdown retain uploaded UTF-8 bytes. URL performs one fetch, saves the received body and content-type/encoding/original URL, then parses that snapshot. This is the HTTP client's returned body, not an archival capture of transport headers or linked assets.

SHA-256 of exact bytes determines the storage key, independent of extension or user filename. Version rows hold checksum/key/type/encoding and source URI. Blobs deduplicate across documents and versions. Save uses same-directory temporary files, fsync and atomic replace; reads verify checksums. Strict key grammar, hash shards and resolved-root containment reject traversal and symlink escapes. No S3/OSS/MinIO layer or dependency is introduced.

Public imports hold a shared local filesystem lock from save through SQL publication; deletion/GC use the same lock. A failed parse/SQL transaction may leave an unreferenced blob. The default dry-run source GC checks indexed version references in batches, with bounded samples and optional JSONL streaming. Repair deletes only unreferenced blobs. This protects save-before-reference from concurrent GC in the supported shared-local-root deployment. Standalone storage.save callers must join this lifecycle protocol when creating database references.

Document deletion commits authoritative SQL deletion first, then cleans vectors and unreferenced sources. A shared blob survives until the final version reference is removed. External cleanup failure returns cleanup_pending and a cleanup_failed job. If the source directory/lock is unavailable, SQL deletion still succeeds and blob cleanup waits for GC. Process termination can leave temporary .source-* files; GC intentionally inventories complete .blob objects only.

### Version semantics and activation

Evidence identity hashes raw checksum + parser version + canonical chunking config hash (chunk_size, chunk_overlap, splitter_version). Legacy imports without raw bytes use a explicitly separate legacy identity. Parser behavior changes require a parser-version bump; changing implementation without changing its declared version cannot be detected.

Same current/pending identity means unchanged/verification or retry. A changed source/parser/chunker creates the next version. Returning to a previously historical identity creates a new monotonic version; it does not rewrite or reactivate an old row. rebuild_embedding / rebuild_graph operate on stored membership and never parse, rechunk or create versions.

Retain Document.current_version as a version number, resolved through unique(document_id, version); add pending_version instead of a cyclic current-version foreign key. Commit prepared version/membership/graph with publishing status and pending_version. Publish and verify Chroma, then atomically advance current_version, clear pending_version and mark ready. A failure preserves the old current number and pending evidence, but the document is non-ready and excluded from normal retrieval until recovery. A new document has current_version=0 before its first activation.

### Content, occurrence and membership

- Content identity: existing normalized text SHA-256 chunk_hash.
- Occurrence identity: (document_id, chunk_hash, occurrence_index), where the index counts identical chunks in document order.
- Membership: (document_version_id, chunk_id) with immutable ordinal/page/section.

Occurrence zero retains the old stable ID format; subsequent occurrences add an occurrence suffix. Duplicate text on separate pages is independently addressable. Occurrence numbering is deterministic, not a semantic tracking algorithm for identical paragraphs that move around.

DocumentChunk.document_version_id and location fields remain immutable creation provenance for compatibility/migration. Current and historical readers MUST use DocumentVersionChunk location/version, never reinterpret the origin foreign key as current membership. ORM update guards protect version, membership and chunk evidence fields; derived embedding/extractor metadata can change. This is application-level immutability, not SQL-administrator tamper resistance.

For V1=[A,B,C], V2=[A,B,D], reuse A/B identities/vectors and refresh their current metadata; embed D. Keep V1 memberships and C text in MySQL; remove C from the current Chroma index. If an old chunk returns after its vector was removed, embedding is needed again. No global embedding cache is introduced.

### Historical evidence and current retrieval

resolve_version_chunk(db, document_version_id, chunk_identity) uses indexed SQL joins to return version snapshot, text, location and raw source reference. It accepts numeric occurrence ID or stable chunk ID and verifies membership ownership. It does not load all historical chunks. QA/Search add version identity while retaining existing fields.

Dense/BM25/graph result resolution uses ready + current-version membership. Chroma is only the current derived index, not the archive. During publication the pending membership is the expected derived state; non-ready documents remain ineligible. Reconciliation uses pending/current membership rather than every SQL chunk, so historical-only vectors are orphans. Repair never activates SQL state.

Graph remains current-only. Stale current graph references can be removed/rebuilt without destroying historical text/location/source evidence. Historical graph versioning and semantic citation validation are explicitly deferred.

### Migration and legacy data

Revision 20260914_evidence_versions is an explicit forward migration with a schema_migrations ledger and MySQL advisory lock. See [migration instructions](../../backend/migrations/README.md). It adds fields/table/indexes, replaces the old chunk uniqueness constraint safely and backfills memberships only for surviving chunks using their actual stored origin version/location. Existing IDs/text/status remain.

Legacy raw keys/checksums/config identity are NULL where unknown. No parsed text is represented as an original PDF. Legacy current evidence remains searchable; reprocess returns raw_source_unavailable until the original source is uploaded. Already deleted old chunks and previously overwritten locations cannot be recovered by migration. Existing citation records lacking version IDs also cannot be made historically precise retroactively.

MySQL DDL implicitly commits; the migration inspects each step and can resume after interruption. Stop application writers and back up MySQL plus raw storage first. Startup rejects an unrecorded/incomplete Phase 2 migration; it initializes an empty database directly. No drop/recreate upgrade or downgrade is provided.

## Consequences and remaining limits

Local storage and SQL references must be backed up/restored together. Changing SOURCE_STORAGE_ROOT requires moving the corresponding blob tree. File locks serialize imports/GC and may be held through model I/O; throughput, multi-host filesystems, Windows-native concurrency and long-history scale have not been load-tested. Vector cleanup reads historical stable IDs for one document, not historical text, but its cost grows with history. Reconciliation should run without concurrent writers for a stable inventory.

This phase does not implement real BGE production defaults, BM25 caching, graph aliases/multi-hop/routing, reranking, semantic citation validation, evaluation corrections, Agent/LangGraph/Harness/Redis/MCP or cloud storage.
