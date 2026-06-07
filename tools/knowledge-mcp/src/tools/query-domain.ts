import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryDomain } from '../db/queries.js';

export const queryDomainSchema = {
  domain_id: z.string().describe('领域ID，如 AT_支付域')
};

export function queryDomainHandler(db: Database.Database, args: { domain_id: string }) {
  const result = queryDomain(db, args.domain_id);
  if (!result) {
    return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'domain_not_found', domain_id: args.domain_id }) }] };
  }
  return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
}
