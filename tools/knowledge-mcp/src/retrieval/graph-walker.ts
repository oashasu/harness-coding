import Database from 'better-sqlite3';
import { queryEntityGraph } from '../db/queries.js';

export interface GraphResult {
  id: string;
  name: string;
  entity_type: string;
  depth: number;
  relation_type: string;
}

export function graphRetrieve(
  db: Database.Database,
  entityName: string,
  options?: { maxDepth?: number; relationTypes?: string[] }
): GraphResult[] {
  const entity = db.prepare('SELECT id FROM entity WHERE name = ?').get(entityName) as any;
  if (!entity) return [];

  const results = queryEntityGraph(db, entity.id, {
    max_depth: options?.maxDepth || 2,
    relation_types: options?.relationTypes,
    temporal: { mode: 'current' },
  });

  return results.map((r: any) => ({
    id: r.id,
    name: r.name,
    entity_type: r.entity_type,
    depth: r.depth,
    relation_type: r.relation_type,
  }));
}
