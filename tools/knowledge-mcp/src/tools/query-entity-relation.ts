import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryEntityRelation } from '../db/queries.js';

export const queryEntityRelationSchema = {
  entity_name: z.string().describe('实体名称，如 Order、Refund')
};

export function queryEntityRelationHandler(db: Database.Database, args: { entity_name: string }) {
  const result = queryEntityRelation(db, args.entity_name);
  return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
}
