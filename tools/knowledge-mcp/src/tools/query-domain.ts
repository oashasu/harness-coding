import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryDomain } from '../db/queries.js';

export const queryDomainSchema = {
  domain_id: z.string().describe('领域ID，如 AT_支付域'),
  temporal_mode: z.enum(['current', 'snapshot', 'all']).optional().default('current'),
  snapshot_time: z.string().optional().describe('ISO8601 时间戳，仅 snapshot 模式'),
  max_results: z.number().optional().default(50),
};

export function queryDomainHandler(db: Database.Database, args: {
  domain_id: string;
  temporal_mode?: string;
  snapshot_time?: string;
  max_results?: number;
}) {
  const result = queryDomain(db, args.domain_id, args.max_results);
  if (!result) {
    return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'domain_not_found', domain_id: args.domain_id }) }] };
  }
  return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
}
