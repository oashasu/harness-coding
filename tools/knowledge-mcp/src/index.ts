import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { initDatabase } from './db/init.js';
import { registerTools } from './server.js';

async function main() {
  const dbPath = process.env.DB_PATH || './data/knowledge.db';
  const db = initDatabase(dbPath);
  const server = new McpServer({
    name: 'knowledge-graph',
    version: '2.0.0',
  });
  registerTools(server, db);
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
