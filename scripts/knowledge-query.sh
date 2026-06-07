#!/bin/bash
# knowledge-query.sh — 知识库查询工具
# 用法: ./knowledge-query.sh <查询内容>
# 示例: ./knowledge-query.sh "前端表格组件用法"

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 颜色定义
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 检查参数
if [ $# -eq 0 ]; then
    echo -e "${YELLOW}用法: $0 <查询内容>${NC}"
    echo ""
    echo "示例:"
    echo "  $0 前端表格组件用法"
    echo "  $0 SQL注入风险"
    echo "  $0 Controller规范"
    echo "  $0 支付域约束"
    exit 1
fi

QUERY="$*"

echo -e "${BLUE}🔍 查询知识库: ${QUERY}${NC}"
echo ""

# 调用knowledge-agent
# 这里使用Claude的agent系统，通过subagent调用
# 实际使用时，可以通过harness.sh或直接调用

# 临时方案：直接查询SQLite数据库
DB_PATH="$PROJECT_ROOT/tools/knowledge-mcp/data/knowledge.db"

# 如果数据库不存在，尝试其他路径
if [ ! -f "$DB_PATH" ]; then
    DB_PATH="$PROJECT_ROOT/../tools/knowledge-mcp/data/knowledge.db"
fi

if [ ! -f "$DB_PATH" ]; then
    echo -e "${YELLOW}知识库数据库不存在，请先运行数据注入${NC}"
    exit 1
fi

echo -e "${GREEN}📚 相关规则:${NC}"
echo ""

# 查询业务规则
sqlite3 -column -header "$DB_PATH" "SELECT rule_type as 类型, substr(rule_content, 1, 100) as 规则内容, confidence as 置信度, source_type as 来源 FROM business_rules WHERE rule_content LIKE '%${QUERY}%' OR domain_id LIKE '%${QUERY}%' ORDER BY confidence DESC LIMIT 10;"

echo ""
echo -e "${GREEN}📄 相关文件:${NC}"
echo ""

# 查询知识文件
sqlite3 -column -header "$DB_PATH" "SELECT title as 标题, domain_id as 领域, tags as 标签 FROM knowledge_files WHERE title LIKE '%${QUERY}%' OR tags LIKE '%${QUERY}%' LIMIT 5;"

echo ""
echo -e "${BLUE}💡 提示: 使用 knowledge-agent 可获得更智能的语义检索${NC}"
