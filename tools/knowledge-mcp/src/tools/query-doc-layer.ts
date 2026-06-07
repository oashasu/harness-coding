import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryDocLayer } from '../db/queries.js';

export const queryDocLayerSchema = {
  layer: z.string().optional().describe('文档层：contract/playbook/policy/template（可选）'),
  domain_id: z.string().optional().describe('领域ID（可选）')
};

export function queryDocLayerHandler(db: Database.Database, args: { layer?: string; domain_id?: string }) {
  const results = queryDocLayer(db, args.layer, args.domain_id);
  return { content: [{ type: 'text' as const, text: JSON.stringify({ documents: results, total: results.length }, null, 2) }] };
}
