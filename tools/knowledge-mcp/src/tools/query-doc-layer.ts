import Database from 'better-sqlite3';
import { queryDocLayer } from '../db/queries.js';

export const queryDocLayerTool = {
  name: 'query_doc_layer',
  description: '查询四层文档（contracts/playbooks/policies/templates）',
  inputSchema: {
    type: 'object' as const,
    properties: {
      layer: { type: 'string', description: '文档层：contract/playbook/policy/template（可选）' },
      domain_id: { type: 'string', description: '领域ID（可选）' }
    }
  },
  handler: (db: Database.Database) => (args: { layer?: string; domain_id?: string }) => {
    const results = queryDocLayer(db, args.layer, args.domain_id);
    return { content: [{ type: 'text' as const, text: JSON.stringify({ documents: results, total: results.length }, null, 2) }] };
  }
};
