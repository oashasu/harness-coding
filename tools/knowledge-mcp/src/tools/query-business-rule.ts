import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryBusinessRule } from '../db/queries.js';

export const queryBusinessRuleSchema = {
  domain_id: z.string().optional().describe('领域ID（可选）'),
  rule_type: z.string().optional().describe('规则类型：constraint/pattern/pitfall/convention（可选）')
};

export function queryBusinessRuleHandler(db: Database.Database, args: { domain_id?: string; rule_type?: string }) {
  const results = queryBusinessRule(db, args.domain_id, args.rule_type);
  return { content: [{ type: 'text' as const, text: JSON.stringify({ rules: results, total: results.length }, null, 2) }] };
}
