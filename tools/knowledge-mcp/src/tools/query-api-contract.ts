import Database from 'better-sqlite3';
import { queryApiContract } from '../db/queries.js';

export const queryApiContractTool = {
  name: 'query_api_contract',
  description: '查询API端点列表和参数定义',
  inputSchema: {
    type: 'object' as const,
    properties: {
      service_name: { type: 'string', description: '服务名称' }
    },
    required: ['service_name']
  },
  handler: (db: Database.Database) => (args: { service_name: string }) => {
    const result = queryApiContract(db, args.service_name);
    return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
  }
};
