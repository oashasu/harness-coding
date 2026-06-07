import Database from 'better-sqlite3';

export interface TemporalFilter {
  mode?: 'current' | 'snapshot' | 'all';
  snapshot_time?: string;
}

function temporalClause(alias: string, filter?: TemporalFilter): string {
  const mode = filter?.mode || 'current';
  if (mode === 'all') return '';
  if (mode === 'snapshot' && filter?.snapshot_time) {
    return ` AND ${alias}.valid_from <= ? AND (${alias}.valid_to IS NULL OR ${alias}.valid_to > ?)`;
  }
  return ` AND ${alias}.valid_from <= datetime('now') AND (${alias}.valid_to IS NULL OR ${alias}.valid_to > datetime('now'))`;
}

function temporalParams(filter?: TemporalFilter): any[] {
  if (filter?.mode === 'snapshot' && filter.snapshot_time) {
    return [filter.snapshot_time, filter.snapshot_time];
  }
  return [];
}

export function queryDomain(db: Database.Database, domainId: string, maxResults = 50) {
  const domain = db.prepare('SELECT * FROM domains WHERE id = ?').get(domainId);
  if (!domain) return null;

  const edges = db.prepare(
    'SELECT * FROM domain_edges WHERE from_domain = ? OR to_domain = ?'
  ).all(domainId, domainId);

  const tables = db.prepare(
    'SELECT * FROM tables WHERE domain_id = ? LIMIT ?'
  ).all(domainId, maxResults);

  return { domain, edges, tables };
}

export function queryTable(db: Database.Database, tableName: string) {
  const table = db.prepare('SELECT * FROM tables WHERE table_name = ?').get(tableName);
  if (!table) return null;

  const domain = db.prepare('SELECT * FROM domains WHERE id = ?').get((table as any).domain_id);
  const relatedTables = db.prepare(
    'SELECT * FROM tables WHERE domain_id = ? AND table_name != ?'
  ).all((table as any).domain_id, tableName);

  return { table, domain, related_tables: relatedTables };
}


export function queryApiContract(db: Database.Database, serviceName: string) {
  const rules = db.prepare(
    "SELECT * FROM business_rules WHERE domain_id LIKE ? AND rule_type = 'api_contract'"
  ).all(`%${serviceName}%`);

  return { api_contracts: rules };
}

export function queryBusinessRule(db: Database.Database, domainId?: string, ruleType?: string) {
  let sql = 'SELECT * FROM business_rules WHERE 1=1';
  const params: any[] = [];

  if (domainId) {
    sql += ' AND domain_id = ?';
    params.push(domainId);
  }
  if (ruleType) {
    sql += ' AND rule_type = ?';
    params.push(ruleType);
  }

  sql += ' ORDER BY confidence DESC';
  return db.prepare(sql).all(...params);
}

export function searchKnowledge(db: Database.Database, queryText: string, temporal?: TemporalFilter) {
  const tc = temporalClause('kf', temporal);
  const tp = temporalParams(temporal);
  try {
    const results = db.prepare(`
      SELECT kf.*, rank
      FROM knowledge_fts
      JOIN knowledge_files kf ON knowledge_fts.rowid = kf.id
      WHERE knowledge_fts MATCH ? ${tc}
      ORDER BY rank
      LIMIT 20
    `).all(queryText, ...tp);
    return results;
  } catch {
    return db.prepare(`
      SELECT * FROM knowledge_files kf
      WHERE (kf.title LIKE ? OR kf.tags LIKE ?) ${tc}
      LIMIT 20
    `).all(`%${queryText}%`, `%${queryText}%`, ...tp);
  }
}

export function queryDocLayer(db: Database.Database, layer?: string, domainId?: string) {
  let sql = 'SELECT * FROM doc_layers WHERE 1=1';
  const params: any[] = [];

  if (layer) {
    sql += ' AND layer = ?';
    params.push(layer);
  }
  if (domainId) {
    sql += ' AND domain_id = ?';
    params.push(domainId);
  }

  sql += ' ORDER BY last_modified DESC';
  return db.prepare(sql).all(...params);
}

export function queryEntityGraph(
  db: Database.Database,
  entityId: string,
  options?: { max_depth?: number; relation_types?: string[]; temporal?: TemporalFilter }
) {
  const maxDepth = options?.max_depth || 2;
  const tc = temporalClause('r', options?.temporal);
  const tp = temporalParams(options?.temporal);
  const types = options?.relation_types || [];
  const typePlaceholder = types.length
    ? ` AND r.relation_type IN (${types.map(() => '?').join(',')})`
    : '';

  const sql = `
    WITH RECURSIVE graph_walk AS (
      SELECT source_id, target_id, relation_type, 1 as depth
      FROM relation r
      WHERE source_id = ? ${tc} ${typePlaceholder}
      UNION ALL
      SELECT r.source_id, r.target_id, r.relation_type, gw.depth + 1
      FROM relation r
      JOIN graph_walk gw ON r.source_id = gw.target_id
      WHERE gw.depth < ? ${tc} ${typePlaceholder}
    )
    SELECT DISTINCT e.*, gw.depth, gw.relation_type
    FROM graph_walk gw
    JOIN entity e ON e.id = gw.target_id
    ORDER BY gw.depth
  `;

  // Params: [entityId, ...tp, ...types, maxDepth, ...tp, ...types]
  const params: any[] = [entityId, ...tp, ...types, maxDepth, ...tp, ...types];

  return db.prepare(sql).all(...params);
}

export function insertEntity(db: Database.Database, entity: {
  id: string; name: string; entity_type: string; domain?: string;
  description?: string; properties?: any;
}) {
  db.prepare(`
    INSERT OR REPLACE INTO entity (id, name, entity_type, domain, description, properties)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(entity.id, entity.name, entity.entity_type, entity.domain || null,
    entity.description || null, entity.properties ? JSON.stringify(entity.properties) : null);
}

export function insertRelation(db: Database.Database, relation: {
  id: string; source_id: string; target_id: string; relation_type: string;
  weight?: number; properties?: any;
}) {
  db.prepare(`
    INSERT OR REPLACE INTO relation (id, source_id, target_id, relation_type, weight, properties)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(relation.id, relation.source_id, relation.target_id, relation.relation_type,
    relation.weight || 1.0, relation.properties ? JSON.stringify(relation.properties) : null);
}

export function invalidateEntity(db: Database.Database, id: string) {
  db.prepare(`UPDATE entity SET valid_to = datetime('now') WHERE id = ?`).run(id);
}

export function invalidateRelation(db: Database.Database, id: string) {
  db.prepare(`UPDATE relation SET valid_to = datetime('now') WHERE id = ?`).run(id);
}
