import Database from 'better-sqlite3';
import { queryTable } from '../db/queries.js';

export const queryTableTool = {
  name: 'query_table',
  description: '查询表结构、所属领域和关联表',
  inputSchema: {
    type: 'object' as const,
    properties: {
      table_name: { type: 'string', description: '表名，如 t_order' }
    },
    required: ['table_name']
  },
  handler: (db: Database.Database) => (args: { table_name: string }) => {
    const result = queryTable(db, args.table_name);
    if (!result) {
      return { content: [{ type: 'text' as const, text: JSON.stringify({ error: 'table_not_found', table_name: args.table_name }) }] };
    }
    return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
  }
};
