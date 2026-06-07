import * as path from 'path';
import { initDatabase } from '../db/init.js';
import { loadDomainGraph } from './domain-graph-loader.js';
import { scanKnowledgeDir } from './knowledge-scanner.js';
import { scanMemoryDir } from './memory-scanner.js';

async function main() {
  const dbPath = process.env.DB_PATH || './data/knowledge.db';
  const rootDir = process.env.ROOT_DIR || path.resolve('../../');

  const db = initDatabase(dbPath);

  // Load domain graph
  const graphPath = path.join(rootDir, 'knowledge/domain_graph.json');
  const domainsLoaded = loadDomainGraph(db, graphPath);
  console.log(`Loaded ${domainsLoaded} domains from domain_graph.json`);

  // Scan knowledge directory
  const knowledgeDir = path.join(rootDir, 'knowledge');
  const filesScanned = scanKnowledgeDir(db, knowledgeDir);
  console.log(`Scanned ${filesScanned} files from knowledge/`);

  // Scan memory directory
  const memoryDir = path.join(rootDir, process.env.MEMORY_DIR || '../.claude/projects/-Users-claw-sandbox/memory');
  const memoryScanned = scanMemoryDir(db, memoryDir);
  console.log(`Scanned ${memoryScanned} files from memory/`);

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
