import { z } from 'zod';
import Database from 'better-sqlite3';
import { queryApiContract } from '../db/queries.js';

export const queryApiContractSchema = {
  service_name: z.string().describe('服务名称')
};

export function queryApiContractHandler(db: Database.Database, args: { service_name: string }) {
  const result = queryApiContract(db, args.service_name);
  return { content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }] };
}
