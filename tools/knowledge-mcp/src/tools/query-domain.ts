import Database from 'better-sqlite3';
import { queryDomain } from '../db/queries.js';

export const queryDomainTool = {
  name: 'query_domain',
  description: '查询领域详情、关联领域和包含的表',
  inputSchema: {
    type: 'object' as const,
    properties: {
      domain_id: { type: 'string', description: '领域ID，如 AT_支付域' }
    },
    required: ['domain_id']
  },
  handler: (db: Database.Database) => (args: { domain_id: string }) => {
    const result = queryDomain(db, args.domain_id);
    if (!result) {
      return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'domain_not_found', domain_id: args.domain_id }) }] };
    }
    return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
  }
};
