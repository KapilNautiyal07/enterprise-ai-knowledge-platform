import type {
  AskResponse,
  DocumentInfo,
  SearchMode,
  SearchResponse,
  UploadResponse,
} from "./types";

const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

function friendlyError(status: number, detail?: string): string {
  if (status === 429) {
    return "I'm getting a lot of questions right now. Give me a few seconds and try again.";
  }
  if (status === 401 || status === 403) {
    return "I couldn't connect to the AI service. The API key may be missing or invalid (check GROQ_API_KEY in .env).";
  }
  if (status >= 500) {
    return "Something went wrong on my side. Please try again in a moment.";
  }
  return detail ?? "That request didn't work. Please try rephrasing it.";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, options);
  } catch {
    throw new Error(
      "I can't reach the server. Make sure the backend is running, then try again.",
    );
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The backend did not return JSON; fall back to a generic message.
    }
    throw new Error(friendlyError(response.status, detail));
  }
  return response.json() as Promise<T>;
}

export function uploadDocument(file: File): Promise<UploadResponse> {
  const body = new FormData();
  body.append("file", file);
  return request<UploadResponse>("/documents/upload", {
    method: "POST",
    body,
  });
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const response = await request<{ documents: DocumentInfo[] }>("/documents/");
  return response.documents;
}

export function deleteDocument(documentId: string): Promise<unknown> {
  return request(`/documents/${documentId}`, { method: "DELETE" });
}

export function askQuestion(
  query: string,
  topK: number,
  documentIds: string[],
): Promise<AskResponse> {
  return request<AskResponse>("/ask/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      top_k: topK,
      document_ids: documentIds.length > 0 ? documentIds : null,
    }),
  });
}

export function searchDocuments(
  query: string,
  topK: number,
  mode: SearchMode,
  documentIds: string[],
): Promise<SearchResponse> {
  const endpoint =
    mode === "semantic"
      ? "/search/"
      : mode === "keyword"
        ? "/search/keyword"
        : mode === "hybrid"
          ? "/search/hybrid"
          : "/search/reranked";
  const params = new URLSearchParams({ query, top_k: String(topK) });
  documentIds.forEach((id) => params.append("document_ids", id));
  return request<SearchResponse>(`${endpoint}?${params}`);
}
