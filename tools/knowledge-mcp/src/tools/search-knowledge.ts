import { z } from 'zod';
import Database from 'better-sqlite3';
import { hybridRetrieve } from '../retrieval/hybrid-retriever.js';

export const searchKnowledgeSchema = {
  query: z.string().describe('搜索关键词或自然语言查询'),
  strategy: z.enum(['semantic-first', 'bm25-first', 'graph-first', 'hybrid']).optional(),
  domains: z.array(z.string()).optional().describe('限制查询的业务域'),
  max_results: z.number().optional().default(20).describe('最大返回条数，上限100'),
};

export function searchKnowledgeHandler(db: Database.Database, args: {
  query: string;
  strategy?: string;
  domains?: string[];
  max_results?: number;
}) {
  const maxResults = Math.min(args.max_results || 20, 100);
  const results = hybridRetrieve(db, args.query, {
    strategy: args.strategy as any,
    topK: maxResults,
    scope: args.domains?.length ? { domains: args.domains } : undefined,
  });

  return { content: [{ type: 'text' as const, text: JSON.stringify(results, null, 2) }] };
}
