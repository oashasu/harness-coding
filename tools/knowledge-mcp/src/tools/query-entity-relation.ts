import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryEntityGraph } from '../db/queries.js';

export const queryEntityRelationSchema = {
  entity_name: z.string().describe('实体名称，如 Order、Refund'),
  relation_types: z.array(z.string()).optional().describe('过滤关系类型'),
  max_depth: z.number().optional().default(2).describe('最大跳数，默认2'),
  temporal_mode: z.enum(['current', 'snapshot', 'all']).optional().default('current'),
};

export function queryEntityRelationHandler(db: Database.Database, args: {
  entity_name: string;
  relation_types?: string[];
  max_depth?: number;
  temporal_mode?: string;
}) {
  const entity = db.prepare('SELECT id FROM entity WHERE name = ?').get(args.entity_name) as any;
  if (!entity) {
    return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'entity_not_found', name: args.entity_name }) }] };
  }

  const results = queryEntityGraph(db, entity.id, {
    max_depth: Math.min(args.max_depth || 2, 5),
    relation_types: args.relation_types,
    temporal: { mode: (args.temporal_mode as any) || 'current' },
  });

  return { content: [{ type: 'text' as const, text: JSON.stringify(results, null, 2) }] };
}
