CREATE TABLE IF NOT EXISTS documents (
  id INT AUTO_INCREMENT PRIMARY KEY,
  source_type VARCHAR(20) NOT NULL,
  source_uri VARCHAR(700) NOT NULL,
  title VARCHAR(255) NOT NULL,
  content_hash VARCHAR(64) NOT NULL,
  parser_version VARCHAR(50) NOT NULL,
  current_version INT NOT NULL DEFAULT 1,
  status VARCHAR(50) NOT NULL DEFAULT 'pending',
  error_message TEXT NULL,
  metadata_json TEXT NULL,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  indexed_at DATETIME(6) NULL,
  UNIQUE KEY uq_documents_source (source_type, source_uri),
  KEY ix_documents_content_hash (content_hash),
  KEY ix_documents_status (status)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS document_versions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  document_id INT NOT NULL,
  version INT NOT NULL,
  content_hash VARCHAR(64) NOT NULL,
  parser_version VARCHAR(50) NOT NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_document_versions_document_version (document_id, version),
  KEY ix_document_versions_content_hash (content_hash),
  CONSTRAINT fk_document_versions_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS document_chunks (
  id INT AUTO_INCREMENT PRIMARY KEY,
  stable_chunk_id VARCHAR(128) NOT NULL,
  document_id INT NOT NULL,
  document_version_id INT NOT NULL,
  chunk_index INT NOT NULL,
  text TEXT NOT NULL,
  chunk_hash VARCHAR(64) NOT NULL,
  page_number INT NULL,
  section_title VARCHAR(255) NULL,
  token_count INT NOT NULL DEFAULT 0,
  embedding_version VARCHAR(50) NOT NULL,
  graph_extractor_version VARCHAR(50) NOT NULL,
  created_at DATETIME(6) NOT NULL,
  indexed_at DATETIME(6) NULL,
  UNIQUE KEY uq_document_chunks_document_hash (document_id, chunk_hash),
  UNIQUE KEY uq_document_chunks_stable_id (stable_chunk_id),
  CONSTRAINT fk_document_chunks_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  CONSTRAINT fk_document_chunks_version FOREIGN KEY (document_version_id) REFERENCES document_versions(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS entities (
  id INT AUTO_INCREMENT PRIMARY KEY,
  entity_type VARCHAR(30) NOT NULL,
  canonical_name VARCHAR(255) NOT NULL,
  normalized_name VARCHAR(255) NOT NULL,
  description TEXT NULL,
  created_at DATETIME(6) NOT NULL,
  updated_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_entities_type_normalized (entity_type, normalized_name)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS entity_aliases (
  id INT AUTO_INCREMENT PRIMARY KEY,
  entity_id INT NOT NULL,
  alias VARCHAR(255) NOT NULL,
  normalized_alias VARCHAR(255) NOT NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_entity_aliases_entity_alias (entity_id, normalized_alias),
  CONSTRAINT fk_entity_aliases_entity FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS entity_mentions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  entity_id INT NOT NULL,
  chunk_id INT NOT NULL,
  mention_text VARCHAR(255) NOT NULL,
  confidence FLOAT NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_entity_mentions_entity_chunk_text (entity_id, chunk_id, mention_text),
  CONSTRAINT fk_entity_mentions_entity FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
  CONSTRAINT fk_entity_mentions_chunk FOREIGN KEY (chunk_id) REFERENCES document_chunks(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS relations (
  id INT AUTO_INCREMENT PRIMARY KEY,
  source_entity_id INT NOT NULL,
  relation_type VARCHAR(40) NOT NULL,
  target_entity_id INT NOT NULL,
  evidence_chunk_id INT NOT NULL,
  confidence FLOAT NOT NULL DEFAULT 0.8,
  extractor_version VARCHAR(50) NOT NULL,
  created_at DATETIME(6) NOT NULL,
  UNIQUE KEY uq_relations_evidence_path (source_entity_id, relation_type, target_entity_id, evidence_chunk_id),
  CONSTRAINT fk_relations_source FOREIGN KEY (source_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
  CONSTRAINT fk_relations_target FOREIGN KEY (target_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
  CONSTRAINT fk_relations_evidence FOREIGN KEY (evidence_chunk_id) REFERENCES document_chunks(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS index_jobs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  document_id INT NULL,
  job_type VARCHAR(50) NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'running',
  reason VARCHAR(255) NOT NULL DEFAULT '',
  started_at DATETIME(6) NOT NULL,
  finished_at DATETIME(6) NULL,
  error_message TEXT NULL,
  error_type VARCHAR(100) NULL,
  stats_json TEXT NULL,
  CONSTRAINT fk_index_jobs_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS evaluation_runs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  status VARCHAR(50) NOT NULL DEFAULT 'completed',
  dataset_path VARCHAR(1024) NOT NULL,
  metrics_json TEXT NOT NULL,
  report_path VARCHAR(1024) NULL,
  created_at DATETIME(6) NOT NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
