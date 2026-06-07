import * as path from 'path';
import * as fs from 'fs';
import { initDatabase } from '../db/init.js';
import { loadDomainGraph } from './domain-graph-loader.js';
import { scanKnowledgeDir } from './knowledge-scanner.js';
import { scanMemoryDir } from './memory-scanner.js';
import { importSddDocuments } from './sdd-importer.js';

function findFile(dir: string, filename: string): string | null {
  const direct = path.join(dir, filename);
  if (fs.existsSync(direct)) return direct;
  try {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        const found = findFile(path.join(dir, entry.name), filename);
        if (found) return found;
      }
    }
  } catch {}
  return null;
}

async function main() {
  const dbPath = process.env.DB_PATH || './data/knowledge.db';
  const rootDir = process.env.ROOT_DIR || path.resolve('../../');

  const db = initDatabase(dbPath);

  // Load domain graph (search recursively)
  const graphPath = findFile(path.join(rootDir, 'knowledge'), 'domain_graph.json');
  let domainsLoaded = 0;
  if (graphPath) {
    domainsLoaded = loadDomainGraph(db, graphPath);
    console.log(`Loaded ${domainsLoaded} domains from ${graphPath}`);
  } else {
    console.log('domain_graph.json not found, skipping');
  }

  // Scan knowledge directory
  const knowledgeDir = path.join(rootDir, 'knowledge');
  const filesScanned = scanKnowledgeDir(db, knowledgeDir);
  console.log(`Scanned ${filesScanned} files from knowledge/`);

  // Scan memory directory
  const memoryDir = process.env.MEMORY_DIR || path.resolve(rootDir, '../.claude/projects/-Users-claw-sandbox/memory');
  const memoryScanned = scanMemoryDir(db, memoryDir);
  console.log(`Scanned ${memoryScanned} files from memory/`);

  // Import SDD documents (if exists)
  const sddDir = process.env.SDD_DIR || path.resolve(rootDir, '../../tasks/2026-06-05_SDD文档提炼_hjly-admin-console');
  let sddImported = 0;
  if (fs.existsSync(sddDir)) {
    sddImported = importSddDocuments(db, sddDir);
    console.log(`Imported ${sddImported} rules from SDD documents`);
  } else {
    console.log('SDD directory not found, skipping');
  }

  // Print summary
  const counts = {
    domains: (db.prepare('SELECT COUNT(*) as c FROM domains').get() as any).c,
    edges: (db.prepare('SELECT COUNT(*) as c FROM domain_edges').get() as any).c,
    tables: (db.prepare('SELECT COUNT(*) as c FROM tables').get() as any).c,
    rules: (db.prepare('SELECT COUNT(*) as c FROM business_rules').get() as any).c,
    files: (db.prepare('SELECT COUNT(*) as c FROM knowledge_files').get() as any).c,
  };
  console.log('\nDatabase summary:', JSON.stringify(counts, null, 2));

  db.close();
}

main().catch(console.error);
