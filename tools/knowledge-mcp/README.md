# Knowledge MCP Server

> Harness Coding v2.0.0 — 知识图谱 MCP 服务

## 构建

```bash
cd tools/knowledge-mcp
npm install
npm run build
```

## 数据导入

```bash
npm run ingest
```

## 启动

```bash
npm start
```

## MCP 工具

| 工具 | 用途 |
|------|------|
| query_domain | 查询领域详情+关联领域+包含的表 |
| query_table | 查询表结构+所属领域+关联表 |
| query_entity_relation | 查询实体→表映射+关联关系 |
| query_api_contract | 查询API端点列表+参数定义 |
| query_business_rule | 查询业务规则（按域/类型/置信度） |
| search_knowledge | FTS5全文检索 |
| query_doc_layer | 查询四层文档 |

## 注册到 Claude Code

在 `~/.claude/settings.json` 的 `mcpServers` 中添加：

```json
{
  "knowledge-graph": {
    "command": "node",
    "args": ["tools/knowledge-mcp/dist/index.js"],
    "env": {
      "DB_PATH": "tools/knowledge-mcp/data/knowledge.db"
    }
  }
}
```
