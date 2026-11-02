export type SearchMode = "reranked" | "hybrid" | "semantic" | "keyword";

export interface Source {
  source_id?: string;
  document_id: string;
  chunk_id: string;
  filename: string;
  chunk_index: number;
  reranker_score?: number;
  similarity?: number;
  rrf_score?: number;
  content?: string;
}

export interface AskResponse {
  query: string;
  answer: string;
  sources: Source[];
  retrieved_chunks: number;
  context_chunks: number;
  citation_validation: {
    valid: boolean;
    citations_found: string[];
    valid_citations: string[];
    invalid_citations: string[];
    has_citations: boolean;
    citation_coverage: number;
  };
}

export interface SearchResponse {
  query: string;
  results: Source[];
}

export interface DocumentInfo {
  document_id: string;
  filename: string;
  file_type: string;
  chunks: number;
  created_at: string | null;
}

export interface UploadResponse extends DocumentInfo {
  characters: number;
  status: "processed" | "duplicate";
}
