import * as fs from 'fs';
import * as crypto from 'crypto';
import Database from 'better-sqlite3';

function computeHash(content: string): string {
  return crypto.createHash('sha256').update(content).digest('hex').slice(0, 16);
}

export function needsUpdate(db: Database.Database, filePath: string): boolean {
  if (!fs.existsSync(filePath)) return false;

  const content = fs.readFileSync(filePath, 'utf-8');
  const currentHash = computeHash(content);

  const existing = db.prepare(
    'SELECT content_hash FROM knowledge_files WHERE file_path = ?'
  ).get(filePath) as any;

  if (!existing) return true;
  return existing.content_hash !== currentHash;
}

export function updateFile(db: Database.Database, filePath: string, metadata: {
  file_type?: string;
  domain_id?: string;
  title?: string;
  tags?: string[];
}): boolean {
  if (!fs.existsSync(filePath)) return false;

  const content = fs.readFileSync(filePath, 'utf-8');
  const hash = computeHash(content);
  const stat = fs.statSync(filePath);

  db.prepare(`
    INSERT OR REPLACE INTO knowledge_files (file_path, file_type, domain_id, title, tags, last_modified, content_hash, indexed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
  `).run(
    filePath,
    metadata.file_type || 'md',
    metadata.domain_id || '',
    metadata.title || '',
    JSON.stringify(metadata.tags || []),
    stat.mtime.toISOString(),
    hash
  );

  return true;
}
