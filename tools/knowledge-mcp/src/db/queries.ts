import Database from 'better-sqlite3';

export function queryDomain(db: Database.Database, domainId: string) {
  const domain = db.prepare('SELECT * FROM domains WHERE id = ?').get(domainId);
  if (!domain) return null;

  const edges = db.prepare(
    'SELECT * FROM domain_edges WHERE from_domain = ? OR to_domain = ?'
  ).all(domainId, domainId);

  const tables = db.prepare(
    'SELECT * FROM tables WHERE domain_id = ?'
  ).all(domainId);

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

export function queryEntityRelation(db: Database.Database, entityName: string) {
  const tables = db.prepare(
    "SELECT * FROM tables WHERE table_name LIKE ? OR description LIKE ?"
  ).all(`%${entityName}%`, `%${entityName}%`);

  const domains = tables.map((t: any) =>
    db.prepare('SELECT * FROM domains WHERE id = ?').get(t.domain_id)
  ).filter(Boolean);

  return { tables, domains };
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

export function searchKnowledge(db: Database.Database, queryText: string) {
  try {
    const results = db.prepare(`
      SELECT kf.*, rank
      FROM knowledge_fts
      JOIN knowledge_files kf ON knowledge_fts.rowid = kf.id
      WHERE knowledge_fts MATCH ?
      ORDER BY rank
      LIMIT 20
    `).all(queryText);
    return results;
  } catch {
    // Fallback to LIKE search
    return db.prepare(`
      SELECT * FROM knowledge_files
      WHERE title LIKE ? OR tags LIKE ?
      LIMIT 20
    `).all(`%${queryText}%`, `%${queryText}%`);
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
