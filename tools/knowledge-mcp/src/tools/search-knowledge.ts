import { z } from 'zod';
import Database from 'better-sqlite3';
import { searchKnowledge } from '../db/queries.js';

export const searchKnowledgeSchema = {
  query: z.string().describe('搜索关键词')
};

export function searchKnowledgeHandler(db: Database.Database, args: { query: string }) {
  const results = searchKnowledge(db, args.query);
  return { content: [{ type: 'text' as const, text: JSON.stringify({ results, total: results.length }, null, 2) }] };
}
