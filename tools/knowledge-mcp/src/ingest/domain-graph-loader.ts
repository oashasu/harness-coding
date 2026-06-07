import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';
import { DomainGraph } from '../types/index.js';

export function loadDomainGraph(db: Database.Database, graphPath: string): number {
  if (!fs.existsSync(graphPath)) return 0;

  const content = fs.readFileSync(graphPath, 'utf-8');
  const graph: DomainGraph = JSON.parse(content);

  const insertDomain = db.prepare(`
    INSERT OR REPLACE INTO domains (id, name, physical_domains, aggregate_root, service, responsibility, source_file, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
  `);

  const insertEdge = db.prepare(`
    INSERT INTO domain_edges (from_domain, to_domain, relation_type, foreign_key, rpc, priority)
    VALUES (?, ?, ?, ?, ?, ?)
  `);

  let count = 0;
  const tx = db.transaction(() => {
    for (const d of graph.domains || []) {
      insertDomain.run(
        d.id,
        d.name,
        JSON.stringify(d.physical_domains || []),
        d.aggregate_root || '',
        d.service || '',
        d.responsibility || '',
        graphPath
      );
      count++;
    }
    for (const e of graph.edges || []) {
      insertEdge.run(e.from, e.to, e.relation_type || '', e.foreign_key || '', e.rpc || '', e.priority || '');
    }
  });
  tx();

  return count;
}
