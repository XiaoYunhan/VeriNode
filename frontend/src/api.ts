import type {
  ApiError,
  ClaimCardDetailRecord,
  ClaimCardRecord,
  DocumentRecord,
  JobRecord,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

function readErrorMessage(error: ApiError, fallback: string): string {
  if (typeof error.detail === "string") {
    return error.detail;
  }
  if (Array.isArray(error.detail)) {
    return error.detail[0]?.msg ?? fallback;
  }
  if (error.detail?.message) {
    return error.detail.message;
  }
  return fallback;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), init);
  if (!response.ok) {
    let payload: ApiError = {};
    try {
      payload = (await response.json()) as ApiError;
    } catch {
      throw new Error(`Request failed with status ${response.status}`);
    }
    throw new Error(readErrorMessage(payload, `Request failed with status ${response.status}`));
  }
  return (await response.json()) as T;
}

export function getArtifactUrl(path: string | null | undefined): string | null {
  if (!path) {
    return null;
  }
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return apiUrl(`/${path.replace(/^\//, "")}`);
}

export function listDocuments(): Promise<DocumentRecord[]> {
  return requestJson<DocumentRecord[]>("/api/documents");
}

export async function deleteDocument(documentId: string): Promise<void> {
  const response = await fetch(apiUrl(`/api/documents/${documentId}`), {
    method: "DELETE",
  });
  if (!response.ok) {
    let payload: ApiError = {};
    try {
      payload = (await response.json()) as ApiError;
    } catch {
      throw new Error(`Delete failed with status ${response.status}`);
    }
    throw new Error(readErrorMessage(payload, `Delete failed with status ${response.status}`));
  }
}

export async function uploadDocument(file: File): Promise<DocumentRecord> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(apiUrl("/api/documents"), {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    let payload: ApiError = {};
    try {
      payload = (await response.json()) as ApiError;
    } catch {
      throw new Error(`Upload failed with status ${response.status}`);
    }
    throw new Error(readErrorMessage(payload, `Upload failed with status ${response.status}`));
  }
  return (await response.json()) as DocumentRecord;
}

export function getDocumentCards(documentId: string): Promise<ClaimCardRecord[]> {
  return requestJson<ClaimCardRecord[]>(`/api/documents/${documentId}/cards`);
}

export function getCard(cardId: string): Promise<ClaimCardDetailRecord> {
  return requestJson<ClaimCardDetailRecord>(`/api/cards/${cardId}`);
}

export function enqueueExtract(documentId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`/api/documents/${documentId}/extract`, {
    method: "POST",
  });
}

export function enqueueVerify(cardId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`/api/cards/${cardId}/verify`, {
    method: "POST",
  });
}

export function enqueueSandbox(cardId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`/api/cards/${cardId}/sandbox`, {
    method: "POST",
  });
}

export function enqueueWebEvidence(cardId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`/api/cards/${cardId}/web-evidence`, {
    method: "POST",
  });
}

export function getJob(jobId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`/api/jobs/${jobId}`);
}

export function retryJob(jobId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`/api/jobs/${jobId}/retry`, {
    method: "POST",
  });
}

export class JobExecutionError extends Error {
  job: JobRecord;

  constructor(job: JobRecord) {
    super(job.error_message ?? `Job ended with status ${job.status}`);
    this.name = "JobExecutionError";
    this.job = job;
  }
}

export async function waitForJob(
  jobId: string,
  onTick?: (job: JobRecord) => void | Promise<void>,
): Promise<JobRecord> {
  let job = await getJob(jobId);
  await onTick?.(job);

  while (job.status === "queued" || job.status === "running") {
    await new Promise((resolve) => window.setTimeout(resolve, 1_500));
    job = await getJob(jobId);
    await onTick?.(job);
  }

  if (job.status !== "succeeded") {
    throw new JobExecutionError(job);
  }

  return job;
}
