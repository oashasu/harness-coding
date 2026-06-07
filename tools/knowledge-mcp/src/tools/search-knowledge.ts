import Database from 'better-sqlite3';
import { searchKnowledge } from '../db/queries.js';

export const searchKnowledgeTool = {
  name: 'search_knowledge',
  description: '全文检索知识库（支持中文）',
  inputSchema: {
    type: 'object' as const,
    properties: {
      query: { type: 'string', description: '搜索关键词' }
    },
    required: ['query']
  },
  handler: (db: Database.Database) => (args: { query: string }) => {
    const results = searchKnowledge(db, args.query);
    return { content: [{ type: 'text' as const, text: JSON.stringify({ results, total: results.length }, null, 2) }] };
  }
};
