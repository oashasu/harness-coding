import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import Database from 'better-sqlite3';

function computeHash(content: string): string {
  return crypto.createHash('sha256').update(content).digest('hex').slice(0, 16);
}

function extractTitle(content: string, filePath: string): string {
  // Try to extract title from first heading
  const headingMatch = content.match(/^#\s+(.+)$/m);
  if (headingMatch) return headingMatch[1].trim();
  return path.basename(filePath, path.extname(filePath));
}

function extractDomainFromPath(filePath: string): string {
  // Try to extract domain from path like knowledge/AT_支付域/xxx.md
  const parts = filePath.split(path.sep);
  for (const part of parts) {
    if (part.includes('_')) return part;
  }
  return '';
}

function extractTags(content: string): string[] {
  const tags: string[] = [];
  // Extract table names
  const tableMatches = content.matchAll(/(?:表名?|table)[:：]\s*(\w+)/gi);
  for (const m of tableMatches) tags.push(m[1]);
  // Extract domain mentions
  const domainMatches = content.matchAll(/(?:域|domain)[:：]\s*(\S+)/gi);
  for (const m of domainMatches) tags.push(m[1]);
  return tags;
}

export function scanKnowledgeDir(db: Database.Database, knowledgeDir: string): number {
  if (!fs.existsSync(knowledgeDir)) return 0;

  const insertFile = db.prepare(`
    INSERT OR REPLACE INTO knowledge_files (file_path, file_type, domain_id, title, tags, last_modified, content_hash, indexed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
  `);

  const insertFTS = db.prepare(`
    INSERT OR REPLACE INTO knowledge_fts (rowid, title, content, tags)
    VALUES (?, ?, ?, ?)
  `);

  let count = 0;

  function scanDir(dir: string) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        scanDir(fullPath);
        continue;
      }
      if (!entry.name.endsWith('.md') && !entry.name.endsWith('.json')) continue;

      try {
        const content = fs.readFileSync(fullPath, 'utf-8');
        const hash = computeHash(content);
        const relPath = path.relative(knowledgeDir, fullPath);
        const title = extractTitle(content, fullPath);
        const domain = extractDomainFromPath(relPath);
        const tags = extractTags(content);
        const stat = fs.statSync(fullPath);

        insertFile.run(
          relPath,
          path.extname(entry.name).slice(1),
          domain,
          title,
          JSON.stringify(tags),
          stat.mtime.toISOString(),
          hash
        );

        // Update FTS
        try {
          const rowId = db.prepare('SELECT id FROM knowledge_files WHERE file_path = ?').get(relPath) as any;
          if (rowId) {
            insertFTS.run(rowId.id, title, content.slice(0, 5000), JSON.stringify(tags));
          }
        } catch {
          // FTS update may fail, continue
        }

        count++;
      } catch {
        // Skip unreadable files
      }
    }
  }

  scanDir(knowledgeDir);
  return count;
}
