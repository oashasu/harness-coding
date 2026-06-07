import Database from 'better-sqlite3';
import { BM25 } from './bm25.js';
import { graphRetrieve } from './graph-walker.js';
import { routeQuery, RetrievalStrategy } from './router.js';
import { searchKnowledge } from '../db/queries.js';

export interface RankedResult {
  id: string;
  score: number;
  source: 'semantic' | 'bm25' | 'graph';
  data: any;
}

export function hybridRetrieve(
  db: Database.Database,
  query: string,
  options?: { strategy?: RetrievalStrategy; topK?: number; scope?: { domains?: string[] } }
): RankedResult[] {
  const strategy = options?.strategy || routeQuery(query);
  const topK = options?.topK || 20;

  switch (strategy) {
    case 'semantic-first':
      return semanticRetrieve(db, query, topK, options?.scope);
    case 'bm25-first':
      return bm25Retrieve(db, query, topK, options?.scope);
    case 'graph-first':
      return graphFirstRetrieve(db, query, topK, options?.scope);
    case 'hybrid':
    default:
      return hybridMerge(db, query, topK, options?.scope);
  }
}

function semanticRetrieve(db: Database.Database, query: string, topK: number, scope?: { domains?: string[] }): RankedResult[] {
  let results = searchKnowledge(db, query, { mode: 'current' });
  const domains = scope?.domains;
  if (domains?.length) {
    results = results.filter((r: any) => domains.includes(r.domain_id));
  }
  // Use FTS5 rank (lower = more relevant) normalized to 0-1 range
  const ranks = results.map((r: any) => r.rank ?? 0);
  const minRank = Math.min(...ranks, 0);
  const maxRank = Math.max(...ranks, 1);
  return results.slice(0, topK).map((r: any) => {
    const normalized = maxRank === minRank ? 1 : 1 - ((r.rank ?? 0) - minRank) / (maxRank - minRank);
    return { id: String(r.id), score: normalized, source: 'semantic' as const, data: r };
  });
}

function bm25Retrieve(db: Database.Database, query: string, topK: number, scope?: { domains?: string[] }): RankedResult[] {
  let docs = db.prepare('SELECT id, title, tags, domain_id FROM knowledge_files').all() as any[];
  const domains = scope?.domains;
  if (domains?.length) {
    docs = docs.filter(d => domains.includes(d.domain_id));
  }

  const bm25 = new BM25();
  bm25.index(docs.map(d => ({ id: String(d.id), text: `${d.title || ''} ${d.tags || ''}` })));
  const ranked = bm25.search(query, topK);

  return ranked.map(r => ({
    id: r.id, score: r.score, source: 'bm25' as const,
    data: docs.find(d => String(d.id) === r.id),
  }));
}

function graphFirstRetrieve(db: Database.Database, query: string, topK: number, scope?: { domains?: string[] }): RankedResult[] {
  const entityMatch = query.match(/\b([A-Z][A-Z_]+)\b/);
  if (!entityMatch) return bm25Retrieve(db, query, topK, scope);

  let graphResults = graphRetrieve(db, entityMatch[1], { maxDepth: 2 });
  const domains = scope?.domains;
  if (domains?.length) {
    graphResults = graphResults.filter((r: any) => domains.includes(r.domain));
  }
  return graphResults.slice(0, topK).map((r, i) => ({
    id: r.id, score: 1 / (i + 1), source: 'graph' as const, data: r,
  }));
}

function hybridMerge(db: Database.Database, query: string, topK: number, scope?: { domains?: string[] }): RankedResult[] {
  const semantic = semanticRetrieve(db, query, topK * 2, scope);
  const bm25 = bm25Retrieve(db, query, topK * 2, scope);
  const graph = graphFirstRetrieve(db, query, topK * 2, scope);

  return rrfMerge([semantic, bm25, graph]).slice(0, topK);
}

function rrfMerge(resultSets: RankedResult[][], k = 60): RankedResult[] {
  const scores = new Map<string, { score: number; source: string; data: any }>();

  for (const results of resultSets) {
    results.forEach((item, rank) => {
      const existing = scores.get(item.id);
      const rrfScore = 1 / (k + rank);
      if (existing) {
        existing.score += rrfScore;
        existing.source = 'hybrid';
      } else {
        scores.set(item.id, { score: rrfScore, source: item.source, data: item.data });
      }
    });
  }

  return [...scores.entries()]
    .map(([id, v]) => ({ id, score: v.score, source: v.source as any, data: v.data }))
    .sort((a, b) => b.score - a.score);
}
