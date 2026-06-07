export const SCHEMA_SQL = `
-- 领域表
CREATE TABLE IF NOT EXISTS domains (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  physical_domains TEXT,
  aggregate_root TEXT,
  service TEXT,
  responsibility TEXT,
  source_file TEXT,
  updated_at TEXT
);

-- 领域关系表
CREATE TABLE IF NOT EXISTS domain_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_domain TEXT NOT NULL,
  to_domain TEXT NOT NULL,
  relation_type TEXT,
  foreign_key TEXT,
  rpc TEXT,
  priority TEXT,
  FOREIGN KEY (from_domain) REFERENCES domains(id),
  FOREIGN KEY (to_domain) REFERENCES domains(id)
);

-- 业务表元数据
CREATE TABLE IF NOT EXISTS tables (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT NOT NULL,
  domain_id TEXT NOT NULL,
  prefix TEXT,
  description TEXT,
  source_file TEXT,
  updated_at TEXT,
  FOREIGN KEY (domain_id) REFERENCES domains(id)
);
CREATE INDEX IF NOT EXISTS idx_tables_name ON tables(table_name);
CREATE INDEX IF NOT EXISTS idx_tables_domain ON tables(domain_id);
CREATE INDEX IF NOT EXISTS idx_tables_prefix ON tables(prefix);

-- 业务规则表
CREATE TABLE IF NOT EXISTS business_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_content TEXT NOT NULL,
  domain_id TEXT,
  rule_type TEXT,
  confidence REAL DEFAULT 0.8,
  source_type TEXT,
  source_file TEXT,
  needs_review INTEGER DEFAULT 0,
  effective_from TEXT,
  expired_at TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rules_domain ON business_rules(domain_id);
CREATE INDEX IF NOT EXISTS idx_rules_type ON business_rules(rule_type);

-- 知识文件索引
CREATE TABLE IF NOT EXISTS knowledge_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT UNIQUE NOT NULL,
  file_type TEXT,
  domain_id TEXT,
  title TEXT,
  tags TEXT,
  last_modified TEXT,
  content_hash TEXT,
  indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_kf_domain ON knowledge_files(domain_id);
CREATE INDEX IF NOT EXISTS idx_kf_type ON knowledge_files(file_type);

-- 四层文档索引表
CREATE TABLE IF NOT EXISTS doc_layers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_path TEXT UNIQUE NOT NULL,
  layer TEXT NOT NULL,
  title TEXT,
  description TEXT,
  domain_id TEXT,
  version TEXT,
  last_modified TEXT,
  content_hash TEXT,
  indexed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dl_layer ON doc_layers(layer);
CREATE INDEX IF NOT EXISTS idx_dl_domain ON doc_layers(domain_id);
`;

export const FTS_SCHEMA_SQL = `
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
  title, content, tags,
  content=knowledge_files,
  content_rowid=id
);
`;
