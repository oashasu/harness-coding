import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryTable } from '../db/queries.js';

export const queryTableSchema = {
  table_name: z.string().describe('表名，如 t_order')
};

export function queryTableHandler(db: Database.Database, args: { table_name: string }) {
  const result = queryTable(db, args.table_name);
  if (!result) {
    return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'table_not_found', table_name: args.table_name }) }] };
  }
  return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
}
