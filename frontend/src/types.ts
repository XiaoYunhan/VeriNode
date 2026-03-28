export type DocumentStatus = "uploaded" | "extracting" | "ready" | "failed";

export type CardStage =
  | "draft"
  | "extracted"
  | "verified"
  | "web_evidence_acquired"
  | "externally_checked"
  | "sandboxed"
  | "completed"
  | "failed";

export type ClaimKind =
  | "factual_claim"
  | "opinion_or_interpretation"
  | "method_description"
  | "result_claim"
  | "code_math_artifact";

export type ReferenceMode = "declared_reference" | "internet_lookup";

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type EvidenceSourceKind =
  | "document"
  | "reference"
  | "tinyfish"
  | "external_search"
  | "sandbox";

export type SupportVerdict =
  | "supported"
  | "partially_supported"
  | "not_supported"
  | "cannot_verify";

export type ExistsVerdict = "exists" | "not_found" | "cannot_determine";

export type TinyFishRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type SandboxRunStatus = "completed" | "failed";

export interface ApiErrorDetail {
  code: string;
  message: string;
}

export interface ApiError {
  detail?: ApiErrorDetail | { msg?: string }[] | string;
}

export interface DocumentRecord {
  id: string;
  filename: string;
  file_type: string;
  storage_path: string;
  status: DocumentStatus;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClaimCardRecord {
  id: string;
  document_id: string;
  card_type: "claim" | "code" | "math";
  claim_kind: ClaimKind;
  reference_mode: ReferenceMode;
  has_declared_reference: boolean;
  declared_reference_count: number;
  claim_text: string | null;
  stage: CardStage;
  page_label: string | null;
  section_label: string | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReferenceRecord {
  id: string;
  ref_label: string | null;
  raw_citation: string;
  resolved_title: string | null;
  resolved_url: string | null;
  resolved_doi: string | null;
}

export interface ClaimReferenceRecord {
  relation_type: string;
  reference: ReferenceRecord;
}

export interface EvidenceSpanRecord {
  id: string;
  source_kind: EvidenceSourceKind;
  text: string;
  page_label: string | null;
  start_anchor: string | null;
  end_anchor: string | null;
}

export interface VerificationResultRecord {
  id: string;
  exists_verdict: ExistsVerdict;
  support_verdict: SupportVerdict;
  reasoning_summary: string;
  source_url: string | null;
  created_at: string;
  reference: ReferenceRecord;
}

export interface TinyFishRunRecord {
  id: string;
  status: TinyFishRunStatus;
  goal: string;
  run_id: string | null;
  source_url: string | null;
  result_summary: string | null;
  artifact_path: string | null;
  created_at: string;
  reference: ReferenceRecord;
}

export interface SandboxRunRecord {
  id: string;
  status: SandboxRunStatus;
  summary: string;
  artifact_path: string | null;
  created_at: string;
}

export interface ClaimCardDetailRecord extends ClaimCardRecord {
  evidence_spans: EvidenceSpanRecord[];
  references: ClaimReferenceRecord[];
  verification_results: VerificationResultRecord[];
  tinyfish_runs: TinyFishRunRecord[];
  sandbox_runs: SandboxRunRecord[];
}

export interface JobRecord {
  id: string;
  job_type: string;
  document_id: string | null;
  claim_card_id: string | null;
  status: JobStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}
