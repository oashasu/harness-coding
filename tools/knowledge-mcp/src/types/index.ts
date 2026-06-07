export interface Domain {
  id: string;
  name: string;
  physical_domains: string;
  aggregate_root: string;
  service: string;
  responsibility: string;
  source_file: string;
  updated_at: string;
}

export interface DomainEdge {
  id: number;
  from_domain: string;
  to_domain: string;
  relation_type: string;
  foreign_key: string;
  rpc: string;
  priority: string;
}

export interface Table {
  id: number;
  table_name: string;
  domain_id: string;
  prefix: string;
  description: string;
  source_file: string;
  updated_at: string;
}

export interface BusinessRule {
  id: number;
  rule_content: string;
  domain_id: string;
  rule_type: string;
  confidence: number;
  source_type: string;
  source_file: string;
  needs_review: number;
  effective_from: string;
  expired_at: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeFile {
  id: number;
  file_path: string;
  file_type: string;
  domain_id: string;
  title: string;
  tags: string;
  last_modified: string;
  content_hash: string;
  indexed_at: string;
}

export interface DocLayer {
  id: number;
  doc_path: string;
  layer: string;
  title: string;
  description: string;
  domain_id: string;
  version: string;
  last_modified: string;
  content_hash: string;
  indexed_at: string;
}

export interface DomainGraph {
  domains: Array<{
    id: string;
    name: string;
    physical_domains?: string[];
    aggregate_root?: string;
    service?: string;
    responsibility?: string;
  }>;
  edges: Array<{
    from: string;
    to: string;
    relation_type?: string;
    foreign_key?: string;
    rpc?: string;
    priority?: string;
  }>;
}
