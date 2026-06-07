import Database from 'better-sqlite3';
import { queryEntityRelation } from '../db/queries.js';

export const queryEntityRelationTool = {
  name: 'query_entity_relation',
  description: '查询实体到表的映射和关联关系',
  inputSchema: {
    type: 'object' as const,
    properties: {
      entity_name: { type: 'string', description: '实体名称，如 Order、Refund' }
    },
    required: ['entity_name']
  },
  handler: (db: Database.Database) => (args: { entity_name: string }) => {
    const result = queryEntityRelation(db, args.entity_name);
    return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
  }
};
