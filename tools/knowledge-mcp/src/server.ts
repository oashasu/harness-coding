import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import Database from 'better-sqlite3';
import { queryDomainSchema, queryDomainHandler } from './tools/query-domain.js';
import { queryTableSchema, queryTableHandler } from './tools/query-table.js';
import { queryEntityRelationSchema, queryEntityRelationHandler } from './tools/query-entity-relation.js';
import { queryApiContractSchema, queryApiContractHandler } from './tools/query-api-contract.js';
import { queryBusinessRuleSchema, queryBusinessRuleHandler } from './tools/query-business-rule.js';
import { searchKnowledgeSchema, searchKnowledgeHandler } from './tools/search-knowledge.js';
import { queryDocLayerSchema, queryDocLayerHandler } from './tools/query-doc-layer.js';

export function registerTools(server: McpServer, db: Database.Database) {
  server.tool('query_domain', '查询领域详情、关联领域和包含的表', queryDomainSchema, (args) => queryDomainHandler(db, args));
  server.tool('query_table', '查询表结构、所属领域和关联表', queryTableSchema, (args) => queryTableHandler(db, args));
  server.tool('query_entity_relation', '查询实体到表的映射和关联关系', queryEntityRelationSchema, (args) => queryEntityRelationHandler(db, args));
  server.tool('query_api_contract', '查询API端点列表和参数定义', queryApiContractSchema, (args) => queryApiContractHandler(db, args));
  server.tool('query_business_rule', '查询业务规则（按域、类型、置信度过滤）', queryBusinessRuleSchema, (args) => queryBusinessRuleHandler(db, args));
  server.tool('search_knowledge', '全文检索知识库（支持中文）', searchKnowledgeSchema, (args) => searchKnowledgeHandler(db, args));
  server.tool('query_doc_layer', '查询四层文档（contracts/playbooks/policies/templates）', queryDocLayerSchema, (args) => queryDocLayerHandler(db, args));
}
