import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: API_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Attach Clerk session token to every request
export function setAuthToken(token: string | null) {
  if (token) {
    apiClient.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    delete apiClient.defaults.headers.common["Authorization"];
  }
}

// ─── Types ────────────────────────────────────────────────────────────────────

export type DeliverableType =
  | "executive_memo"
  | "competitive_landscape"
  | "investment_thesis"
  | "project_brief"
  | "literature_summary";

export type ProjectStatus =
  | "created"
  | "ingesting"
  | "indexing"
  | "cross_referencing"
  | "generating"
  | "ready"
  | "error";

export interface Project {
  id: string;
  name: string;
  deliverable_type: DeliverableType;
  status: ProjectStatus;
  source_count: number;
  created_at: string;
  updated_at: string;
}

export interface CreateProjectPayload {
  name: string;
  deliverable_type: DeliverableType;
}

export interface Source {
  id: string;
  project_id: string;
  type: "pdf" | "url" | "docx" | "text";
  filename?: string;
  url?: string;
  status: "pending" | "processing" | "ready" | "error";
  confidence_score?: number;
  page_count?: number;
  created_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

// ─── Project API ──────────────────────────────────────────────────────────────

export const projectsApi = {
  list: () =>
    apiClient.get<PaginatedResponse<Project>>("/projects").then((r) => r.data),

  get: (id: string) =>
    apiClient.get<Project>(`/projects/${id}`).then((r) => r.data),

  create: (payload: CreateProjectPayload) =>
    apiClient.post<Project>("/projects", payload).then((r) => r.data),

  delete: (id: string) =>
    apiClient.delete(`/projects/${id}`).then((r) => r.data),
};

// ─── Sources API ──────────────────────────────────────────────────────────────

export const sourcesApi = {
  list: (projectId: string) =>
    apiClient
      .get<Source[]>(`/projects/${projectId}/sources`)
      .then((r) => r.data),

  uploadFile: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiClient
      .post<Source>(`/projects/${projectId}/sources/upload`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },

  addUrl: (projectId: string, url: string) =>
    apiClient
      .post<Source>(`/projects/${projectId}/sources/url`, { url })
      .then((r) => r.data),

  delete: (projectId: string, sourceId: string) =>
    apiClient
      .delete(`/projects/${projectId}/sources/${sourceId}`)
      .then((r) => r.data),
};
