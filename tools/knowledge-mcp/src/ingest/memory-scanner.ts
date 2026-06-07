import * as fs from 'fs';
import * as path from 'path';
import * as crypto from 'crypto';
import Database from 'better-sqlite3';

function computeHash(content: string): string {
  return crypto.createHash('sha256').update(content).digest('hex').slice(0, 16);
}

export function scanMemoryDir(db: Database.Database, memoryDir: string): number {
  if (!fs.existsSync(memoryDir)) return 0;

  const insertRule = db.prepare(`
    INSERT OR REPLACE INTO business_rules (rule_content, domain_id, rule_type, confidence, source_type, source_file, created_at, updated_at)
    VALUES (?, ?, ?, ?, 'memory', ?, datetime('now'), datetime('now'))
  `);

  const insertFile = db.prepare(`
    INSERT OR REPLACE INTO knowledge_files (file_path, file_type, domain_id, title, tags, last_modified, content_hash, indexed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
  `);

  let count = 0;
  const entries = fs.readdirSync(memoryDir, { withFileTypes: true });

  for (const entry of entries) {
    if (!entry.name.endsWith('.md')) continue;
    const fullPath = path.join(memoryDir, entry.name);

    try {
      const content = fs.readFileSync(fullPath, 'utf-8');
      const hash = computeHash(content);

      // Extract domain from filename or content
      let domain = '';
      const domainMatch = content.match(/(?:域|domain)[:：]\s*(\S+)/i);
      if (domainMatch) domain = domainMatch[1];

      // Determine rule type from content
      let ruleType = 'convention';
      if (content.includes('约束') || content.includes('constraint') || content.includes('禁止')) {
        ruleType = 'constraint';
      } else if (content.includes('坑') || content.includes('pitfall') || content.includes('注意')) {
        ruleType = 'pitfall';
      } else if (content.includes('模式') || content.includes('pattern')) {
        ruleType = 'pattern';
      }

      // Extract meaningful rules from content (skip frontmatter)
      const bodyStart = content.indexOf('---', 3);
      const body = bodyStart > 0 ? content.slice(bodyStart + 3) : content;
      const lines = body.split('\n').filter(l => l.trim() && !l.startsWith('#') && !l.startsWith('>'));

      // Extract key rules (limit to 3 most important)
      const ruleLines = lines.filter(l =>
        l.includes(':') || l.includes('：') || l.includes('规则') || l.includes('规范') || l.includes('禁止')
      ).slice(0, 3);

      const ruleContent = ruleLines.length > 0
        ? ruleLines.join(' | ')
        : lines[0]?.trim().slice(0, 500) || entry.name;

      insertRule.run(ruleContent, domain, ruleType, 0.9, entry.name);
      insertFile.run(entry.name, 'md', domain, entry.name.replace('.md', ''), '[]', fs.statSync(fullPath).mtime.toISOString(), hash);

      count++;
    } catch {
      // Skip unreadable files
    }
  }

  return count;
}
