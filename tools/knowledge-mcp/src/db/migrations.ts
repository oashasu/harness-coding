import Database from 'better-sqlite3';
import { BITEMPORAL_MIGRATION_SQL, GRAPH_SCHEMA_SQL } from './schema.js';

interface Migration {
  id: string;
  sql: string;
}

const MIGRATIONS: Migration[] = [
  { id: 'bitemporal_001', sql: BITEMPORAL_MIGRATION_SQL },
  { id: 'graph_001', sql: GRAPH_SCHEMA_SQL },
];

export function runMigrations(db: Database.Database): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS _migrations (
      id TEXT PRIMARY KEY,
      applied_at TEXT DEFAULT (datetime('now'))
    );
  `);

  const applied = new Set(
    db.prepare('SELECT id FROM _migrations').all().map((r: any) => r.id)
  );

  for (const m of MIGRATIONS) {
    if (applied.has(m.id)) continue;
    const stmts = m.sql.split(';').filter(s => s.trim());
    for (const stmt of stmts) {
      if (stmt.trim()) db.exec(stmt);
    }
    db.prepare('INSERT INTO _migrations (id) VALUES (?)').run(m.id);
    console.error(`Applied migration: ${m.id}`);
  }
}
