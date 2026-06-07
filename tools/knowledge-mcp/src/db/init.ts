import Database from 'better-sqlite3';
import { SCHEMA_SQL, FTS_SCHEMA_SQL } from './schema.js';

export function initDatabase(dbPath: string): Database.Database {
  const db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');

  // Create tables
  db.exec(SCHEMA_SQL);

  // Create FTS table (may fail if already exists, that's ok)
  try {
    db.exec(FTS_SCHEMA_SQL);
  } catch {
    // FTS table already exists
  }

  return db;
}
