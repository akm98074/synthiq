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
  use_voice_calibration: boolean;
  created_at: string;
  updated_at: string;
}

// ─── Voice Profile types ────────────────────────────────────────────────────

export type HedgingFrequency = "low" | "moderate" | "high";
export type TechVocabDensity = "low" | "moderate" | "high";
export type StructuralPreference = "bullets" | "prose" | "mixed";
export type SectionHeaderStyle = "numbered" | "plain" | "bold" | "none";
export type FormalityRegister = "informal" | "neutral" | "formal";

export interface StyleSignature {
  avg_sentence_length: number;
  avg_paragraph_length: number;
  hedging_frequency: HedgingFrequency;
  technical_vocab_density: TechVocabDensity;
  structural_preference: StructuralPreference;
  section_header_style: SectionHeaderStyle;
  formality_register: FormalityRegister;
}

export interface VoiceProfile {
  id: string;
  sample_count: number;
  style_signature: StyleSignature | null;
  voice_system_prompt: string | null;
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

  updateVoice: (id: string, use_voice_calibration: boolean) =>
    apiClient
      .patch<Project>(`/projects/${id}/voice`, { use_voice_calibration })
      .then((r) => r.data),

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

  flag: (
    projectId: string,
    sourceId: string,
    payload: { is_flagged?: boolean; is_excluded?: boolean }
  ) =>
    apiClient
      .put(`/projects/${projectId}/sources/${sourceId}/flag`, payload)
      .then((r) => r.data),
};

// ─── Source Map API ────────────────────────────────────────────────────────────

export interface ClusterData {
  id: string;
  label: string;
  source_count: number;
  chunk_count: number;
  source_ids: string[];
  key_entities: string[];
}

export interface ContradictionData {
  id: string;
  entity: string;
  claim: string;
  source_a: string;
  source_a_id: string;
  source_b: string;
  source_b_id: string;
  quote_a: string;
  quote_b: string;
  significance: number;
}

export interface GapData {
  topic: string;
  mentioned_in_count: number;
  missing_in_count: number;
  missing_source_ids: string[];
}

export interface SourceSidebarData {
  id: string;
  filename?: string;
  url?: string;
  type: string;
  status: string;
  confidence_score?: number;
  page_count?: number;
  is_excluded: boolean;
  is_flagged: boolean;
  cluster_ids: string[];
}

export interface SourceMapData {
  clusters: ClusterData[];
  contradictions: ContradictionData[];
  gaps: GapData[];
  sources: SourceSidebarData[];
  entity_count: number;
}

export const sourceMapApi = {
  get: (projectId: string) =>
    apiClient
      .get<SourceMapData>(`/projects/${projectId}/source-map`)
      .then((r) => r.data),
};

// ─── Deliverable API ──────────────────────────────────────────────────────────

export interface CitationData {
  source_id: string;
  source_title: string;
  page?: number;
  marker?: string;
  quote?: string;
}

export interface SectionData {
  id: string;
  title: string;
  content: string;
  status: "pending" | "generating" | "done" | "error";
  citations: CitationData[];
}

export interface DeliverableData {
  id: string;
  version: number;
  status: "generating" | "ready" | "error";
  outline?: Record<string, unknown>;
  sections: SectionData[];
}

export const deliverableApi = {
  get: (projectId: string) =>
    apiClient
      .get<DeliverableData>(`/projects/${projectId}/deliverable`)
      .then((r) => r.data),

  generate: (projectId: string) =>
    apiClient
      .post<DeliverableData>(`/projects/${projectId}/deliverable/generate`)
      .then((r) => r.data),

  regenerateSection: (projectId: string, sectionId: string) =>
    apiClient
      .post<DeliverableData>(
        `/projects/${projectId}/deliverable/sections/${sectionId}/regenerate`
      )
      .then((r) => r.data),

  instructSection: (
    projectId: string,
    sectionId: string,
    instruction: string
  ) =>
    apiClient
      .post<DeliverableData>(
        `/projects/${projectId}/deliverable/sections/${sectionId}/instruct`,
        { instruction }
      )
      .then((r) => r.data),
};

// ─── Export API ───────────────────────────────────────────────────────────────

export type ExportFormat = "docx" | "pdf";
export type CitationStyle = "inline" | "footnotes";

export interface ExportRequest {
  format: ExportFormat;
  citation_style: CitationStyle;
  include_source_map: boolean;
}

export interface ExportResponse {
  download_url: string;
  filename: string;
  format: ExportFormat;
}

export const exportApi = {
  export: (projectId: string, payload: ExportRequest) =>
    apiClient
      .post<ExportResponse>(`/projects/${projectId}/export`, payload)
      .then((r) => r.data),
};

// ─── Billing API ──────────────────────────────────────────────────────────────

export interface PlanInfo {
  plan: string;
  label: string;
  price_monthly_usd: number | null;
  project_limit: number | null;
  sources_per_project: number | null;
  voice_calibration: boolean;
}

export interface BillingStatus {
  plan: string;
  subscription_status: string;
  stripe_customer_id: string | null;
}

export interface CheckoutRequest {
  plan: "professional" | "team";
  success_url?: string;
  cancel_url?: string;
}

export interface CheckoutResponse {
  checkout_url: string;
}

export interface PortalResponse {
  portal_url: string;
}

export const billingApi = {
  plans: () =>
    apiClient.get<PlanInfo[]>("/billing/plans").then((r) => r.data),

  status: () =>
    apiClient.get<BillingStatus>("/billing/status").then((r) => r.data),

  checkout: (payload: CheckoutRequest) =>
    apiClient
      .post<CheckoutResponse>("/billing/checkout", payload)
      .then((r) => r.data),

  portal: () =>
    apiClient.post<PortalResponse>("/billing/portal").then((r) => r.data),
};

// ─── Voice API ────────────────────────────────────────────────────────────────

export const voiceApi = {
  get: () =>
    apiClient.get<VoiceProfile | null>("/voice").then((r) => r.data),

  uploadSample: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiClient
      .post<VoiceProfile>("/voice/samples", form, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },

  deleteProfile: () =>
    apiClient.delete("/voice").then((r) => r.data),
};
