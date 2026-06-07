import Database from 'better-sqlite3';
import { queryBusinessRule } from '../db/queries.js';

export const queryBusinessRuleTool = {
  name: 'query_business_rule',
  description: '查询业务规则（按域、类型、置信度过滤）',
  inputSchema: {
    type: 'object' as const,
    properties: {
      domain_id: { type: 'string', description: '领域ID（可选）' },
      rule_type: { type: 'string', description: '规则类型：constraint/pattern/pitfall/convention（可选）' }
    }
  },
  handler: (db: Database.Database) => (args: { domain_id?: string; rule_type?: string }) => {
    const results = queryBusinessRule(db, args.domain_id, args.rule_type);
    return { content: [{ type: 'text' as const, text: JSON.stringify({ rules: results, total: results.length }, null, 2) }] };
  }
};
