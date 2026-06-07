import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import Database from 'better-sqlite3';
import { queryDomainTool } from './tools/query-domain.js';
import { queryTableTool } from './tools/query-table.js';
import { queryEntityRelationTool } from './tools/query-entity-relation.js';
import { queryApiContractTool } from './tools/query-api-contract.js';
import { queryBusinessRuleTool } from './tools/query-business-rule.js';
import { searchKnowledgeTool } from './tools/search-knowledge.js';
import { queryDocLayerTool } from './tools/query-doc-layer.js';

export function registerTools(server: McpServer, db: Database.Database) {
  const tools = [
    queryDomainTool,
    queryTableTool,
    queryEntityRelationTool,
    queryApiContractTool,
    queryBusinessRuleTool,
    searchKnowledgeTool,
    queryDocLayerTool,
  ];

  for (const tool of tools) {
    server.tool(
      tool.name,
      tool.description,
      tool.inputSchema.properties,
      tool.handler(db)
    );
  }
}
