import {
  startTransition,
  useDeferredValue,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  deleteDocument,
  enqueueExtract,
  enqueueSandbox,
  enqueueVerify,
  getArtifactUrl,
  getCard,
  getDocumentCards,
  JobExecutionError,
  listDocuments,
  retryJob,
  uploadDocument,
  waitForJob,
} from "./api";
import type {
  CardStage,
  ClaimCardDetailRecord,
  ClaimCardRecord,
  ClaimKind,
  JobRecord,
  ReferenceMode,
} from "./types";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./components/ui/card";
import { cn } from "./lib/utils";

const stageActionLabels: Record<CardStage, string> = {
  draft: "Draft",
  extracted: "Extracted",
  verified: "Verified",
  web_evidence_acquired: "Web Evidence",
  externally_checked: "Externally Checked",
  sandboxed: "Sandboxed",
  completed: "Completed",
  failed: "Needs Attention",
};

type ClaimLane = ReferenceMode | "sandbox";

interface ActiveJobState {
  job: JobRecord;
  label: string;
}

function App() {
  const queryClient = useQueryClient();
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [noticeMessage, setNoticeMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryJobId, setRetryJobId] = useState<string | null>(null);
  const [documentJobs, setDocumentJobs] = useState<Record<string, ActiveJobState>>({});
  const [claimJobs, setClaimJobs] = useState<Record<string, ActiveJobState>>({});
  const [extractQueueingDocumentId, setExtractQueueingDocumentId] = useState<string | null>(null);
  const [deletePendingDocumentId, setDeletePendingDocumentId] = useState<string | null>(null);
  const [claimQueueingLabels, setClaimQueueingLabels] = useState<Record<string, string>>({});

  const deferredDocumentId = useDeferredValue(selectedDocumentId);
  const deferredClaimId = useDeferredValue(selectedClaimId);

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
  });

  const claimsQuery = useQuery({
    queryKey: ["claims", deferredDocumentId],
    queryFn: () => getDocumentCards(deferredDocumentId!),
    enabled: Boolean(deferredDocumentId),
  });

  const claimDetailQuery = useQuery({
    queryKey: ["claim", deferredClaimId],
    queryFn: () => getCard(deferredClaimId!),
    enabled: Boolean(deferredClaimId),
  });

  const documents = documentsQuery.data ?? [];
  const claims = claimsQuery.data ?? [];
  const rankedClaims = [...claims].sort((left, right) => {
    const leftLane = claimLane(left);
    const rightLane = claimLane(right);
    if (leftLane !== rightLane) {
      return claimLanePriority(leftLane) - claimLanePriority(rightLane);
    }
    return left.created_at.localeCompare(right.created_at);
  });
  const selectedDocument = documents.find((document) => document.id === selectedDocumentId) ?? null;
  const selectedClaim = claimDetailQuery.data ?? null;
  const selectedDocumentJob = selectedDocumentId ? documentJobs[selectedDocumentId] ?? null : null;
  const selectedClaimJob = selectedClaimId ? claimJobs[selectedClaimId] ?? null : null;
  const selectedClaimQueueingLabel = selectedClaimId ? claimQueueingLabels[selectedClaimId] ?? null : null;

  useEffect(() => {
    if (!documents.length) {
      setSelectedDocumentId(null);
      return;
    }
    if (!selectedDocumentId || !documents.some((document) => document.id === selectedDocumentId)) {
      startTransition(() => {
        setSelectedDocumentId(documents[0].id);
      });
    }
  }, [documents, selectedDocumentId]);

  useEffect(() => {
    if (!rankedClaims.length) {
      setSelectedClaimId(null);
      return;
    }
    if (!selectedClaimId || !rankedClaims.some((claim) => claim.id === selectedClaimId)) {
      startTransition(() => {
        setSelectedClaimId(rankedClaims[0].id);
      });
    }
  }, [rankedClaims, selectedClaimId]);

  const refreshSelection = async (): Promise<void> => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["documents"] }),
      deferredDocumentId
        ? queryClient.invalidateQueries({ queryKey: ["claims", deferredDocumentId] })
        : Promise.resolve(),
      deferredClaimId
        ? queryClient.invalidateQueries({ queryKey: ["claim", deferredClaimId] })
        : Promise.resolve(),
    ]);
  };

  const trackDocumentJob = async (job: JobRecord, label: string): Promise<void> => {
    if (!job.document_id) {
      return;
    }
    const documentId = job.document_id;
    setRetryJobId(null);
    setDocumentJobs((current) => ({
      ...current,
      [documentId]: { job, label },
    }));

    try {
      await waitForJob(job.id, async (nextJob) => {
        if (nextJob.document_id) {
          setDocumentJobs((current) => ({
            ...current,
            [nextJob.document_id!]: { job: nextJob, label },
          }));
        }
        await refreshSelection();
      });
      setNoticeMessage(`${label} completed`);
    } finally {
      setDocumentJobs((current) => omitKey(current, documentId));
    }

    await refreshSelection();
  };

  const trackClaimJob = async (job: JobRecord, label: string): Promise<void> => {
    if (!job.claim_card_id) {
      return;
    }
    const claimId = job.claim_card_id;
    setRetryJobId(null);
    setClaimJobs((current) => ({
      ...current,
      [claimId]: { job, label },
    }));

    try {
      await waitForJob(job.id, async (nextJob) => {
        if (nextJob.claim_card_id) {
          setClaimJobs((current) => ({
            ...current,
            [nextJob.claim_card_id!]: { job: nextJob, label },
          }));
        }
        await refreshSelection();
      });
    } finally {
      setClaimJobs((current) => omitKey(current, claimId));
    }

    await refreshSelection();
  };

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => uploadDocument(file),
    onMutate: () => {
      setErrorMessage(null);
      setNoticeMessage("Uploading document");
    },
    onSuccess: async (document) => {
      setPendingFile(null);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      startTransition(() => {
        setSelectedDocumentId(document.id);
        setSelectedClaimId(null);
      });
      setNoticeMessage("Document uploaded");
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Upload failed");
      setNoticeMessage(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (documentId: string) => deleteDocument(documentId),
    onMutate: (documentId) => {
      setErrorMessage(null);
      setDeletePendingDocumentId(documentId);
      setNoticeMessage("Removing document");
    },
    onSuccess: async (_void, documentId) => {
      if (selectedDocumentId === documentId) {
        startTransition(() => {
          setSelectedDocumentId(null);
          setSelectedClaimId(null);
        });
      }
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setNoticeMessage("Document removed");
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Document removal failed");
    },
    onSettled: () => {
      setDeletePendingDocumentId(null);
    },
  });

  const extractMutation = useMutation({
    mutationFn: async (documentId: string) => enqueueExtract(documentId),
    onMutate: (documentId) => {
      setErrorMessage(null);
      setExtractQueueingDocumentId(documentId);
    },
    onSuccess: async (job) => {
      try {
        await trackDocumentJob(job, "Claim extraction");
      } catch (error) {
        if (error instanceof JobExecutionError) {
          setRetryJobId(error.job.id);
          setErrorMessage(error.message);
        } else {
          setErrorMessage(error instanceof Error ? error.message : "Claim extraction failed");
        }
      }
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Claim extraction failed");
    },
    onSettled: () => {
      setExtractQueueingDocumentId(null);
    },
  });

  const verifyMutation = useMutation({
    mutationFn: async (claimId: string) => enqueueVerify(claimId),
    onMutate: (claimId) => {
      setErrorMessage(null);
      setClaimQueueingLabels((current) => ({
        ...current,
        [claimId]: "Verification & evidence capture",
      }));
    },
    onSuccess: async (job) => {
      try {
        await trackClaimJob(job, "Verification & evidence capture");
      } catch (error) {
        if (error instanceof JobExecutionError) {
          setRetryJobId(error.job.id);
          setErrorMessage(error.message);
        } else {
          setErrorMessage(error instanceof Error ? error.message : "Verification failed");
        }
      }
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Verification failed");
    },
    onSettled: (_data, _error, claimId) => {
      setClaimQueueingLabels((current) => omitKey(current, claimId));
    },
  });

  const sandboxMutation = useMutation({
    mutationFn: async (claimId: string) => enqueueSandbox(claimId),
    onMutate: (claimId) => {
      setErrorMessage(null);
      setClaimQueueingLabels((current) => ({
        ...current,
        [claimId]: "Sandbox simulation",
      }));
    },
    onSuccess: async (job) => {
      try {
        await trackClaimJob(job, "Sandbox simulation");
      } catch (error) {
        if (error instanceof JobExecutionError) {
          setRetryJobId(error.job.id);
          setErrorMessage(error.message);
        } else {
          setErrorMessage(error instanceof Error ? error.message : "Sandbox simulation failed");
        }
      }
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Sandbox simulation failed");
    },
    onSettled: (_data, _error, claimId) => {
      setClaimQueueingLabels((current) => omitKey(current, claimId));
    },
  });

  const retryLatestFailedJob = useMutation({
    mutationFn: async (jobId: string) => retryJob(jobId),
    onMutate: () => {
      setErrorMessage(null);
    },
    onSuccess: async (job) => {
      const label = job.job_type === "verify_card"
        ? "Verification & evidence capture"
        : job.job_type === "sandbox"
          ? "Sandbox simulation"
          : job.job_type === "web_evidence"
            ? "TinyFish evidence capture"
            : "Claim extraction";
      try {
        if (job.claim_card_id) {
          await trackClaimJob(job, label);
        } else {
          await trackDocumentJob(job, label);
        }
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Retry failed");
      }
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Retry failed");
    },
  });

  return (
    <div className="relative min-h-screen overflow-hidden">
      <div
        className={cn(
          "pointer-events-none absolute inset-0",
          "bg-[linear-gradient(rgba(30,32,36,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(30,32,36,0.03)_1px,transparent_1px)] bg-[size:32px_32px]",
          "[mask-image:linear-gradient(180deg,rgba(0,0,0,0.65),transparent_84%)]",
        )}
      />
      <div className="relative z-10 mx-auto max-w-[1520px] px-4 py-4 sm:px-6 lg:px-8">
        <header className="mb-5 grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.9fr)]">
          <Card className="p-7">
            <CardContent>
              <p className="text-[0.78rem] font-bold uppercase tracking-[0.18em] text-[#7b5a3f]">
                Local-First Research Verification
              </p>
              <h1 className="mt-2 font-serif text-[clamp(2.25rem,4vw,3.6rem)] leading-[0.95] tracking-[-0.04em]">
                VeriNode Workbench
              </h1>
              <p className="max-w-[62ch] text-[15px] leading-7 text-[#4e5055]">
                Upload a PDF or Markdown paper, extract atomic claims, verify cited work, and
                switch code or math claims into an executable sandbox lane.
              </p>
            </CardContent>
          </Card>
          <Card className="p-4">
            <CardContent className="grid gap-3 sm:grid-cols-3 xl:grid-cols-3">
              <StatCard label="Documents" value={String(documents.length)} />
              <StatCard label="Claims" value={String(rankedClaims.length)} />
              <StatCard
                label="Current Stage"
                value={selectedClaim ? stageActionLabels[selectedClaim.stage] : "Idle"}
                compact
              />
            </CardContent>
          </Card>
        </header>

        {(noticeMessage || errorMessage) && (
          <Card className="mb-4 rounded-[20px] px-4 py-3">
            <CardContent className="space-y-3">
              {noticeMessage && (
                <div className="rounded-full bg-[#137882]/12 px-4 py-2 text-sm text-[#0d5b63]">
                  {noticeMessage}
                </div>
              )}
              {errorMessage && (
                <div className="rounded-full bg-[#a6432a]/12 px-4 py-2 text-sm text-[#8f3320]">
                  {errorMessage}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <main className="grid gap-4 xl:h-[calc(100vh-13rem)] xl:grid-cols-[300px_minmax(320px,430px)_minmax(0,1fr)]">
          <Card className="flex min-h-[70vh] flex-col overflow-hidden p-5 xl:min-h-0 xl:h-full">
            <CardHeader>
              <CardTitle>Documents</CardTitle>
              <CardDescription>
                Upload one source file, then rerun, delete, or inspect it from the same workspace.
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-4 flex min-h-0 flex-1 flex-col gap-4">
              <UploadComposer
                pendingFile={pendingFile}
                onFileChange={setPendingFile}
                onUpload={() => {
                  if (pendingFile) {
                    uploadMutation.mutate(pendingFile);
                  }
                }}
                isUploading={uploadMutation.isPending}
              />

              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                <div className="grid gap-3">
                  {documentsQuery.isLoading && (
                    <EmptyState
                      title="Loading documents"
                      body="Connecting to the backend workbench."
                    />
                  )}
                  {!documentsQuery.isLoading && !documents.length && (
                    <EmptyState
                      title="No documents yet"
                      body="Upload one of your sample papers or a new source document to start the demo flow."
                    />
                  )}
                  {documents.map((document) => (
                    <button
                      key={document.id}
                      type="button"
                      className={cn(
                        "min-w-0 overflow-hidden rounded-[22px] border border-black/8 bg-white/70 p-4 text-left transition",
                        "hover:border-[#0d5b63]/25 hover:shadow-[0_14px_28px_rgba(13,91,99,0.08)]",
                        document.id === selectedDocumentId &&
                          "border-[#0d5b63]/45 bg-[#f8f2e9] ring-2 ring-[#1f7c6f]/18 shadow-[0_18px_32px_rgba(13,91,99,0.14)]",
                      )}
                      onClick={() =>
                        startTransition(() => {
                          setSelectedDocumentId(document.id);
                          setSelectedClaimId(null);
                        })
                      }
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <StatusBadge tone={document.status}>{document.status}</StatusBadge>
                        <div className="flex flex-wrap items-center gap-2">
                          {documentJobs[document.id] && (
                            <InlineJobChip
                              label={documentJobs[document.id].label}
                              status={documentJobs[document.id].job.status}
                            />
                          )}
                          {deletePendingDocumentId === document.id && (
                            <InlineJobChip label="Removing document" status="running" />
                          )}
                          <span className="text-xs text-[#70695f]">{document.file_type.toUpperCase()}</span>
                        </div>
                      </div>
                      <h3 className="mt-3 break-words font-medium text-[#1f2329]">
                        {document.title ?? document.filename}
                      </h3>
                      <p className="mt-1 break-words text-sm leading-6 text-[#52545a]">
                        {document.filename}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="flex min-h-[70vh] flex-col overflow-hidden p-5 xl:min-h-0 xl:h-full">
            <CardHeader>
              <CardTitle>
                {selectedDocument ? selectedDocument.title ?? selectedDocument.filename : "Claims"}
              </CardTitle>
              <CardDescription>
                {selectedDocument
                  ? "Run extraction once, then review the resulting claims."
                  : "Pick a document to inspect its extracted claims."}
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-4 flex min-h-0 flex-1 flex-col gap-4">
              <div className="flex flex-wrap items-center justify-between gap-4 rounded-[22px] bg-[#f2ece1]/70 p-4">
                <div>
                  <span className="mb-1 block text-[0.78rem] uppercase tracking-[0.08em] text-[#70695f]">
                    Document status
                  </span>
                  <StatusBadge tone={selectedDocument?.status ?? "uploaded"}>
                    {selectedDocument?.status ?? "idle"}
                  </StatusBadge>
                  {selectedDocumentJob && (
                    <div className="mt-2">
                      <InlineJobChip
                        label={selectedDocumentJob.label}
                        status={selectedDocumentJob.job.status}
                      />
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button
                    disabled={
                      !selectedDocumentId ||
                      extractQueueingDocumentId === selectedDocumentId ||
                      Boolean(selectedDocumentJob)
                    }
                    onClick={() => {
                      if (selectedDocumentId) {
                        extractMutation.mutate(selectedDocumentId);
                      }
                    }}
                  >
                    {extractQueueingDocumentId === selectedDocumentId || selectedDocumentJob
                      ? "Extracting..."
                      : "Extract Claims"}
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={!selectedDocumentId || deletePendingDocumentId === selectedDocumentId}
                    onClick={() => {
                      if (selectedDocumentId) {
                        deleteMutation.mutate(selectedDocumentId);
                      }
                    }}
                  >
                    {deletePendingDocumentId === selectedDocumentId ? "Removing..." : "Remove Document"}
                  </Button>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                <div className="grid gap-3">
                  {!selectedDocumentId && (
                    <EmptyState
                      title="Choose a document"
                      body="The next claim list will appear here as soon as a document is selected."
                    />
                  )}
                  {selectedDocumentId && claimsQuery.isLoading && (
                    <EmptyState
                      title="Loading claims"
                      body="Fetching extracted claims for the selected document."
                    />
                  )}
                  {selectedDocumentId && !claimsQuery.isLoading && !rankedClaims.length && (
                    <EmptyState
                      title="No claims yet"
                      body="Run claim extraction to populate the first set of atomic review claims."
                    />
                  )}
                  {rankedClaims.map((claim) => (
                    <button
                      key={claim.id}
                      type="button"
                      className={cn(
                        "min-w-0 overflow-hidden rounded-[22px] border border-black/8 bg-white/70 p-4 text-left transition",
                        "hover:border-[#0d5b63]/25 hover:shadow-[0_14px_28px_rgba(13,91,99,0.08)]",
                        claim.id === selectedClaimId &&
                          "border-[#0d5b63]/45 bg-[#f8f2e9] ring-2 ring-[#1f7c6f]/18 shadow-[0_18px_32px_rgba(13,91,99,0.14)]",
                      )}
                      onClick={() =>
                        startTransition(() => {
                          setSelectedClaimId(claim.id);
                        })
                      }
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <StatusBadge tone={claim.stage}>{stageActionLabels[claim.stage]}</StatusBadge>
                        <ClaimLaneChip lane={claimLane(claim)} />
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <KindChip>{formatClaimKind(claim.claim_kind)}</KindChip>
                        {claimQueueingLabels[claim.id] && (
                          <InlineJobChip label={claimQueueingLabels[claim.id]} status="queued" />
                        )}
                        {claimJobs[claim.id] && (
                          <InlineJobChip
                            label={claimJobs[claim.id].label}
                            status={claimJobs[claim.id].job.status}
                          />
                        )}
                        {claim.has_declared_reference && (
                          <Badge className="bg-emerald-100 text-emerald-800">
                            {claim.declared_reference_count} cited
                          </Badge>
                        )}
                      </div>
                      <strong className="mt-3 block break-words text-[#1f2329]">
                        {claim.summary ?? claim.claim_text ?? "Untitled claim"}
                      </strong>
                      <p className="mt-2 break-words text-sm leading-6 text-[#52545a]">
                        {claim.claim_text ?? "No claim text available."}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="flex min-h-[70vh] flex-col overflow-hidden p-5 xl:min-h-0 xl:h-full">
            <CardHeader>
              <CardTitle>Claim Detail</CardTitle>
              <CardDescription>
                Inspect evidence, references, verification verdicts, browser output, and sandbox process.
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1">
              {!selectedClaim && (
                <EmptyState
                  title="Select a claim"
                  body="Choose a claim in the middle column to run verification or sandbox simulation."
                />
              )}

              {selectedClaim && (
                <ClaimDetail
                  claim={selectedClaim}
                  onRunPrimaryAction={() => {
                    if (isSandboxClaim(selectedClaim)) {
                      sandboxMutation.mutate(selectedClaim.id);
                    } else {
                      verifyMutation.mutate(selectedClaim.id);
                    }
                  }}
                  onRetry={() => {
                    if (retryJobId) {
                      retryLatestFailedJob.mutate(retryJobId);
                    }
                  }}
                  activeJob={selectedClaimJob}
                  queueingLabel={selectedClaimQueueingLabel}
                  retryPending={retryLatestFailedJob.isPending}
                  canRetry={Boolean(retryJobId)}
                />
              )}
            </CardContent>
          </Card>
        </main>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div className="flex min-h-28 flex-col justify-between rounded-[22px] border border-black/6 bg-[linear-gradient(180deg,rgba(255,255,255,0.86),rgba(247,242,234,0.95))] p-4">
      <span className="text-[0.8rem] uppercase tracking-[0.08em] text-[#746a60]">{label}</span>
      <strong
        className={cn(
          "font-serif leading-[1.02] break-words",
          compact
            ? "text-[clamp(1.1rem,2vw,1.65rem)]"
            : "text-[clamp(1.75rem,3vw,2.5rem)]",
        )}
      >
        {value}
      </strong>
    </div>
  );
}

function UploadComposer({
  pendingFile,
  onFileChange,
  onUpload,
  isUploading,
}: {
  pendingFile: File | null;
  onFileChange: (file: File | null) => void;
  onUpload: () => void;
  isUploading: boolean;
}) {
  return (
    <div className="grid gap-3">
      <label className="relative grid cursor-pointer gap-1.5 rounded-[22px] border border-dashed border-[#137882]/35 bg-[linear-gradient(180deg,rgba(250,247,241,0.92),rgba(244,237,227,0.88))] px-4 py-4">
        <input
          type="file"
          accept=".pdf,.md,.markdown"
          className="absolute inset-0 cursor-pointer opacity-0"
          onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
        />
        <span className="font-medium">{pendingFile ? pendingFile.name : "Drop a PDF or Markdown paper here"}</span>
        <small className="text-sm leading-6 text-[#666158]">
          VeriNode keeps the backend authoritative and persists every stage result.
        </small>
      </label>
      <Button variant="default" disabled={!pendingFile || isUploading} onClick={onUpload}>
        {isUploading ? "Uploading..." : "Upload Document"}
      </Button>
    </div>
  );
}

function ClaimDetail({
  claim,
  onRunPrimaryAction,
  onRetry,
  activeJob,
  queueingLabel,
  retryPending,
  canRetry,
}: {
  claim: ClaimCardDetailRecord;
  onRunPrimaryAction: () => void;
  onRetry: () => void;
  activeJob: ActiveJobState | null;
  queueingLabel: string | null;
  retryPending: boolean;
  canRetry: boolean;
}) {
  const sandboxClaim = isSandboxClaim(claim);
  const screenshotUrl = getArtifactUrl(claim.tinyfish_runs.at(-1)?.artifact_path);
  const latestTinyFishRun = claim.tinyfish_runs.at(-1) ?? null;
  const latestSandboxRun = claim.sandbox_runs.at(-1) ?? null;
  const isBusy = Boolean(queueingLabel || activeJob);
  const primaryActionLabel = sandboxClaim
    ? isBusy
      ? "Running Sandbox..."
      : "Run Sandbox Simulation"
    : isBusy
      ? "Verifying..."
      : "Verify + Capture Evidence";

  return (
    <div className="grid gap-4">
      <section className="rounded-[24px] border border-black/8 bg-[linear-gradient(145deg,rgba(245,239,228,0.96),rgba(255,255,255,0.84))] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone={claim.stage}>{stageActionLabels[claim.stage]}</StatusBadge>
            <ClaimLaneChip lane={claimLane(claim)} />
            <KindChip>{formatClaimKind(claim.claim_kind)}</KindChip>
          </div>
        </div>
        <h3 className="mt-4 font-serif text-2xl leading-tight text-[#1f2329]">
          {claim.summary ?? claim.claim_text ?? "Untitled claim"}
        </h3>
        <p className="mt-3 text-sm leading-7 text-[#52545a]">
          {claim.claim_text ?? "No claim text available for this claim."}
        </p>
        {(queueingLabel || activeJob) && (
          <div className="mt-4">
            <LoadingInline
              text={
                queueingLabel
                  ? `${queueingLabel} queued with the backend worker.`
                  : `${activeJob?.label ?? "Claim job"} is ${formatLabel(activeJob?.job.status ?? "running")}.`
              }
            />
          </div>
        )}
        <div className="mt-4 flex flex-wrap gap-3">
          <Button disabled={isBusy} onClick={onRunPrimaryAction}>
            {primaryActionLabel}
          </Button>
          {claim.stage === "failed" && canRetry && (
            <Button variant="ghost" disabled={retryPending} onClick={onRetry}>
              {retryPending ? "Retrying..." : "Retry Last Step"}
            </Button>
          )}
        </div>
      </section>

      <div className="grid gap-4 2xl:grid-cols-2">
        <DetailSection title="Evidence Spans" bodyLabel={`${claim.evidence_spans.length} captured`}>
          {claim.evidence_spans.length ? (
            claim.evidence_spans.map((span) => (
              <article key={span.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <StatusBadge tone={span.source_kind}>{span.source_kind}</StatusBadge>
                  {span.page_label && <span className="text-xs text-[#70695f]">Page {span.page_label}</span>}
                </div>
                <p className="mt-3 text-sm leading-6 text-[#52545a]">{span.text}</p>
              </article>
            ))
          ) : (
            <EmptyInline text="No evidence spans have been persisted yet." />
          )}
        </DetailSection>

        <DetailSection title="References" bodyLabel={`${claim.references.length} linked`}>
          {claim.references.length ? (
            claim.references.map((item) => (
              <article key={item.reference.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <strong>
                    {item.relation_type === "internet_lookup"
                      ? "Internet lookup"
                      : item.reference.ref_label ?? item.relation_type}
                  </strong>
                  {item.reference.resolved_url && (
                    <a href={item.reference.resolved_url} target="_blank" rel="noreferrer">
                      Open source
                    </a>
                  )}
                </div>
                <p className="mt-3 text-sm leading-6 text-[#52545a]">
                  {item.reference.resolved_title ?? item.reference.raw_citation}
                </p>
                <small className="mt-3 block text-xs leading-5 text-[#6d6963]">
                  {item.reference.raw_citation}
                </small>
              </article>
            ))
          ) : (
            <EmptyInline
              text={
                sandboxClaim
                  ? "This executable claim does not rely on external references."
                  : "This claim does not have any extracted references."
              }
            />
          )}
        </DetailSection>

        {!sandboxClaim && (
          <DetailSection title="Verification" bodyLabel={`${claim.verification_results.length} verdicts`}>
            {claim.verification_results.length ? (
              claim.verification_results.map((result) => (
                <article key={result.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <StatusBadge tone={result.support_verdict}>{result.support_verdict}</StatusBadge>
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-xs text-[#70695f]">{formatLabel(result.exists_verdict)}</span>
                      {result.source_url && (
                        <a href={result.source_url} target="_blank" rel="noreferrer">
                          Visit source
                        </a>
                      )}
                    </div>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-[#52545a]">{result.reasoning_summary}</p>
                  <small className="mt-3 block text-xs leading-5 text-[#6d6963]">
                    {result.reference.resolved_title ?? result.reference.raw_citation}
                  </small>
                </article>
              ))
            ) : (
              <EmptyInline text="Run verification to persist support verdicts here." />
            )}
          </DetailSection>
        )}

        {!sandboxClaim && (
          <DetailSection title="TinyFish Evidence" bodyLabel={`${claim.tinyfish_runs.length} runs`}>
            {isBusy && !claim.tinyfish_runs.length ? (
              <LoadingInline text="TinyFish is gathering browser evidence and screenshot material for this claim." />
            ) : claim.tinyfish_runs.length ? (
              <>
                {claim.tinyfish_runs.map((run) => (
                  <article key={run.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <StatusBadge tone={run.status}>{run.status}</StatusBadge>
                      {run.artifact_path && (
                        <a
                          href={getArtifactUrl(run.artifact_path) ?? "#"}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open screenshot
                        </a>
                      )}
                    </div>
                    <p className="mt-3 text-sm leading-6 text-[#52545a]">
                      {run.result_summary ?? "No TinyFish summary available."}
                    </p>
                    <small className="mt-3 block text-xs leading-5 text-[#6d6963]">
                      {run.reference.resolved_title ?? run.reference.raw_citation}
                    </small>
                  </article>
                ))}
                {screenshotUrl ? (
                  <div className="overflow-hidden rounded-[22px] border border-black/8 bg-[#f5f0e8]/72">
                    <img src={screenshotUrl} alt="TinyFish browser screenshot" className="block h-auto w-full" />
                  </div>
                ) : latestTinyFishRun?.status === "failed" ? (
                  <EmptyInline
                    text={
                      latestTinyFishRun.result_summary ??
                      "TinyFish was blocked before a screenshot could be captured."
                    }
                  />
                ) : (
                  <EmptyInline text="TinyFish structured evidence is available. No screenshot artifact was persisted for the latest run." />
                )}
              </>
            ) : (
              <EmptyInline text="Run verification to capture browser-native evidence for this claim." />
            )}
          </DetailSection>
        )}

        {sandboxClaim && (
          <DetailSection title="Sandbox Process" bodyLabel={`${claim.sandbox_runs.length} runs`}>
            {isBusy && !claim.sandbox_runs.length ? (
              <LoadingInline text="OpenAI sandbox is evaluating this executable claim." />
            ) : claim.sandbox_runs.length ? (
              <>
                {claim.sandbox_runs.map((run) => (
                  <article key={run.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <StatusBadge tone={run.status}>{run.status}</StatusBadge>
                      {run.artifact_path && (
                        <a href={getArtifactUrl(run.artifact_path) ?? "#"} target="_blank" rel="noreferrer">
                          Open full process
                        </a>
                      )}
                    </div>
                    <p className="mt-3 text-sm leading-6 text-[#52545a]">{run.summary}</p>
                  </article>
                ))}
                {!latestSandboxRun?.artifact_path && (
                  <EmptyInline text="The sandbox completed without a persisted full-process artifact." />
                )}
              </>
            ) : (
              <EmptyInline text="Run sandbox simulation to preserve the full executable reasoning for this claim." />
            )}
          </DetailSection>
        )}
      </div>
    </div>
  );
}

function DetailSection({
  title,
  bodyLabel,
  children,
}: {
  title: string;
  bodyLabel: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[24px] border border-black/8 bg-white/64 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h4 className="font-serif text-[1.35rem] leading-tight text-[#1e2024]">{title}</h4>
        <span className="text-sm leading-6 text-[#6d6963]">{bodyLabel}</span>
      </div>
      <div className="mt-4 grid gap-3">{children}</div>
    </section>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[20px] border border-black/6 bg-[#f7f1e8]/66 p-4 text-[#5b5852]">
      <strong className="block">{title}</strong>
      <p className="mt-2 text-sm leading-6">{body}</p>
    </div>
  );
}

function EmptyInline({ text }: { text: string }) {
  return (
    <div className="rounded-[20px] border border-black/6 bg-[#f7f1e8]/66 p-4 text-sm leading-6 text-[#5b5852]">
      {text}
    </div>
  );
}

function LoadingInline({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 rounded-[20px] border border-black/6 bg-[#eef6f2] p-4 text-sm leading-6 text-[#215a53]">
      <span className="inline-flex size-4 animate-spin rounded-full border-2 border-[#1f7c6f]/25 border-t-[#1f7c6f]" />
      <span>{text}</span>
    </div>
  );
}

function InlineJobChip({
  label,
  status,
}: {
  label: string;
  status: JobRecord["status"] | "completed";
}) {
  const spinning = status === "queued" || status === "running";
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-[#edf6f1] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#1b5a52]">
      {spinning && (
        <span className="inline-flex size-3 animate-spin rounded-full border-2 border-[#1f7c6f]/25 border-t-[#1f7c6f]" />
      )}
      <span>{label}: {formatLabel(status)}</span>
    </span>
  );
}

function StatusBadge({
  tone,
  children,
}: {
  tone: string;
  children: string;
}) {
  return <Badge className={toneClassName(tone)}>{formatLabel(children)}</Badge>;
}

function KindChip({ children }: { children: string }) {
  return <Badge className="bg-black/6 text-[#4d4f55]">{children}</Badge>;
}

function ClaimLaneChip({ lane }: { lane: ClaimLane }) {
  return <Badge className={claimLaneClassName(lane)}>{claimLaneLabel(lane)}</Badge>;
}

function formatClaimKind(kind: ClaimKind): string {
  return formatLabel(kind);
}

function formatLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function toneClassName(value: string): string {
  if (["ready", "extracted", "completed", "supported", "exists", "verified", "web_evidence_acquired", "tinyfish", "completed", "sandboxed"].includes(value)) {
    return "bg-emerald-100 text-emerald-800";
  }
  if (["extracting", "queued", "running", "pending"].includes(value)) {
    return "bg-amber-100 text-amber-800";
  }
  if (["partially_supported", "method_description", "result_claim"].includes(value)) {
    return "bg-sky-100 text-sky-800";
  }
  if (["not_supported", "failed", "cancelled", "not_found"].includes(value)) {
    return "bg-rose-100 text-rose-800";
  }
  if (["cannot_verify", "cannot_determine", "opinion_or_interpretation", "reference"].includes(value)) {
    return "bg-violet-100 text-violet-800";
  }
  return "bg-stone-200 text-stone-700";
}

function claimLaneClassName(lane: ClaimLane): string {
  if (lane === "declared_reference") {
    return "bg-teal-100 text-teal-800";
  }
  if (lane === "sandbox") {
    return "bg-amber-100 text-amber-800";
  }
  return "bg-[#efe8f7] text-[#6b5190]";
}

function claimLaneLabel(lane: ClaimLane): string {
  if (lane === "declared_reference") {
    return "Declared Reference";
  }
  if (lane === "sandbox") {
    return "Sandbox Simulation";
  }
  return "Internet Lookup";
}

function claimLanePriority(lane: ClaimLane): number {
  if (lane === "declared_reference") {
    return 0;
  }
  if (lane === "sandbox") {
    return 1;
  }
  return 2;
}

function claimLane(claim: Pick<ClaimCardRecord, "card_type" | "claim_kind" | "reference_mode">): ClaimLane {
  if (isSandboxClaim(claim)) {
    return "sandbox";
  }
  return claim.reference_mode;
}

function isSandboxClaim(claim: Pick<ClaimCardRecord, "card_type" | "claim_kind">): boolean {
  return claim.card_type !== "claim" || claim.claim_kind === "code_math_artifact";
}

function omitKey<T extends Record<string, unknown>>(record: T, key: string): T {
  const { [key]: _removed, ...rest } = record;
  return rest as T;
}

export default App;
