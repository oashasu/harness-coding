export type RetrievalStrategy = 'semantic-first' | 'bm25-first' | 'graph-first' | 'hybrid';

export function routeQuery(query: string): RetrievalStrategy {
  const entityPattern = /\b[A-Z][A-Z_]+\b|[a-z_]+_table\b|表|域/;
  const keywordPattern = /注入|泄漏|越权|超时|异常|错误|配置|枚举|分账|退款|支付/;

  const hasEntity = entityPattern.test(query);
  const hasKeyword = keywordPattern.test(query);
  const isLongQuery = query.length > 20;

  if (hasEntity && !hasKeyword) return 'graph-first';
  if (hasKeyword && !isLongQuery) return 'bm25-first';
  if (isLongQuery) return 'semantic-first';
  return 'hybrid';
}
