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
  enqueueExtract,
  enqueueVerify,
  enqueueWebEvidence,
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
  ClaimKind,
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

function App() {
  const queryClient = useQueryClient();
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [activityMessage, setActivityMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryJobId, setRetryJobId] = useState<string | null>(null);

  const deferredDocumentId = useDeferredValue(selectedDocumentId);
  const deferredCardId = useDeferredValue(selectedCardId);

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: listDocuments,
  });

  const cardsQuery = useQuery({
    queryKey: ["cards", deferredDocumentId],
    queryFn: () => getDocumentCards(deferredDocumentId!),
    enabled: Boolean(deferredDocumentId),
  });

  const cardDetailQuery = useQuery({
    queryKey: ["card", deferredCardId],
    queryFn: () => getCard(deferredCardId!),
    enabled: Boolean(deferredCardId),
  });

  const documents = documentsQuery.data ?? [];
  const cards = cardsQuery.data ?? [];
  const selectedDocument = documents.find((document) => document.id === selectedDocumentId) ?? null;

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
    if (!cards.length) {
      setSelectedCardId(null);
      return;
    }
    if (!selectedCardId || !cards.some((card) => card.id === selectedCardId)) {
      startTransition(() => {
        setSelectedCardId(cards[0].id);
      });
    }
  }, [cards, selectedCardId]);

  const refreshSelection = async (): Promise<void> => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["documents"] }),
      deferredDocumentId
        ? queryClient.invalidateQueries({ queryKey: ["cards", deferredDocumentId] })
        : Promise.resolve(),
      deferredCardId
        ? queryClient.invalidateQueries({ queryKey: ["card", deferredCardId] })
        : Promise.resolve(),
    ]);
  };

  const trackJob = async (jobId: string, label: string): Promise<void> => {
    setRetryJobId(null);
    setActivityMessage(`${label} started`);
    await waitForJob(jobId, async (job) => {
      setActivityMessage(`${label}: ${job.status.replace("_", " ")}`);
      await refreshSelection();
    });
    setActivityMessage(`${label} completed`);
    await refreshSelection();
  };

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => uploadDocument(file),
    onMutate: () => {
      setErrorMessage(null);
      setActivityMessage("Uploading document");
    },
    onSuccess: async (document) => {
      setPendingFile(null);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      startTransition(() => {
        setSelectedDocumentId(document.id);
        setSelectedCardId(null);
      });
      setActivityMessage("Document uploaded");
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Upload failed");
      setActivityMessage(null);
    },
  });

  const extractMutation = useMutation({
    mutationFn: async (documentId: string) => enqueueExtract(documentId),
    onMutate: () => {
      setErrorMessage(null);
    },
    onSuccess: async (job) => {
      try {
        await trackJob(job.id, "Claim extraction");
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
  });

  const verifyMutation = useMutation({
    mutationFn: async (cardId: string) => enqueueVerify(cardId),
    onMutate: () => {
      setErrorMessage(null);
    },
    onSuccess: async (job) => {
      try {
        await trackJob(job.id, "Reference verification");
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
  });

  const webEvidenceMutation = useMutation({
    mutationFn: async (cardId: string) => enqueueWebEvidence(cardId),
    onMutate: () => {
      setErrorMessage(null);
    },
    onSuccess: async (job) => {
      try {
        await trackJob(job.id, "TinyFish web evidence");
      } catch (error) {
        if (error instanceof JobExecutionError) {
          setRetryJobId(error.job.id);
          setErrorMessage(error.message);
        } else {
          setErrorMessage(error instanceof Error ? error.message : "TinyFish run failed");
        }
      }
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "TinyFish run failed");
    },
  });

  const retryLatestFailedJob = useMutation({
    mutationFn: async (jobId: string) => retryJob(jobId),
    onMutate: () => {
      setErrorMessage(null);
    },
    onSuccess: async (job) => {
      const label = job.job_type === "verify_card"
        ? "Reference verification"
        : job.job_type === "web_evidence"
          ? "TinyFish web evidence"
          : "Claim extraction";
      try {
        await trackJob(job.id, label);
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : "Retry failed");
      }
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "Retry failed");
    },
  });

  const selectedCard = cardDetailQuery.data ?? null;

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
                Upload a PDF or Markdown paper, extract atomic cards, verify citations with
                OpenAI, and escalate hard references to TinyFish browser evidence when needed.
              </p>
            </CardContent>
          </Card>
          <Card className="p-4">
            <CardContent className="grid gap-3 sm:grid-cols-3 xl:grid-cols-3">
              <StatCard label="Documents" value={String(documents.length)} />
              <StatCard label="Cards" value={String(cards.length)} />
              <StatCard
                label="Current Stage"
                value={selectedCard ? stageActionLabels[selectedCard.stage] : "Idle"}
              />
            </CardContent>
          </Card>
        </header>

        {(activityMessage || errorMessage) && (
          <Card className="mb-4 rounded-[20px] px-4 py-3">
            <CardContent className="flex flex-wrap gap-3">
              {activityMessage && (
                <div className="rounded-full bg-[#137882]/12 px-4 py-2 text-sm text-[#0d5b63]">
                  {activityMessage}
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

        <main className="grid gap-4 xl:grid-cols-[300px_minmax(320px,430px)_minmax(0,1fr)]">
          <Card className="min-h-[70vh] p-5">
            <CardHeader>
              <CardTitle>Documents</CardTitle>
              <CardDescription>
                Upload one source file, then drive each stage explicitly.
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-4 space-y-4">
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
                      "rounded-[22px] border border-black/8 bg-white/70 p-4 text-left transition",
                      "hover:border-[#0d5b63]/25 hover:shadow-[0_14px_28px_rgba(13,91,99,0.08)]",
                      document.id === selectedDocumentId &&
                        "border-[#0d5b63]/35 shadow-[0_14px_28px_rgba(13,91,99,0.1)]",
                    )}
                    onClick={() =>
                      startTransition(() => {
                        setSelectedDocumentId(document.id);
                        setSelectedCardId(null);
                      })
                    }
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <StatusBadge tone={document.status}>{document.status}</StatusBadge>
                      <span className="text-xs text-[#70695f]">{document.file_type.toUpperCase()}</span>
                    </div>
                    <h3 className="mt-3 font-medium text-[#1f2329]">
                      {document.title ?? document.filename}
                    </h3>
                    <p className="mt-1 text-sm leading-6 text-[#52545a]">{document.filename}</p>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="min-h-[70vh] p-5">
            <CardHeader>
              <CardTitle>
                {selectedDocument ? selectedDocument.title ?? selectedDocument.filename : "Cards"}
              </CardTitle>
              <CardDescription>
                {selectedDocument
                  ? "Run extraction once, then review the resulting claim cards."
                  : "Pick a document to inspect its claim cards."}
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-4 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4 rounded-[22px] bg-[#f2ece1]/70 p-4">
                <div>
                  <span className="mb-1 block text-[0.78rem] uppercase tracking-[0.08em] text-[#70695f]">
                    Document status
                  </span>
                  <StatusBadge tone={selectedDocument?.status ?? "uploaded"}>
                    {selectedDocument?.status ?? "idle"}
                  </StatusBadge>
                </div>
                <Button
                  disabled={!selectedDocumentId || extractMutation.isPending}
                  onClick={() => {
                    if (selectedDocumentId) {
                      extractMutation.mutate(selectedDocumentId);
                    }
                  }}
                >
                  {extractMutation.isPending ? "Queueing..." : "Extract Claims"}
                </Button>
              </div>

              <div className="grid gap-3">
                {!selectedDocumentId && (
                  <EmptyState
                    title="Choose a document"
                    body="The next card list will appear here as soon as a document is selected."
                  />
                )}
                {selectedDocumentId && cardsQuery.isLoading && (
                  <EmptyState
                    title="Loading cards"
                    body="Fetching extracted claim cards for the selected document."
                  />
                )}
                {selectedDocumentId && !cardsQuery.isLoading && !cards.length && (
                  <EmptyState
                    title="No cards yet"
                    body="Run claim extraction to populate the first set of atomic review cards."
                  />
                )}
                {cards.map((card) => (
                  <button
                    key={card.id}
                    type="button"
                    className={cn(
                      "rounded-[22px] border border-black/8 bg-white/70 p-4 text-left transition",
                      "hover:border-[#0d5b63]/25 hover:shadow-[0_14px_28px_rgba(13,91,99,0.08)]",
                      card.id === selectedCardId &&
                        "border-[#0d5b63]/35 shadow-[0_14px_28px_rgba(13,91,99,0.1)]",
                    )}
                    onClick={() =>
                      startTransition(() => {
                        setSelectedCardId(card.id);
                      })
                    }
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <StatusBadge tone={card.stage}>{stageActionLabels[card.stage]}</StatusBadge>
                      <KindChip>{formatClaimKind(card.claim_kind)}</KindChip>
                    </div>
                    <strong className="mt-3 block text-[#1f2329]">
                      {card.summary ?? card.claim_text ?? "Untitled card"}
                    </strong>
                    <p className="mt-2 text-sm leading-6 text-[#52545a]">
                      {card.claim_text ?? "No claim text available."}
                    </p>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card className="min-h-[70vh] p-5">
            <CardHeader>
              <CardTitle>Card Detail</CardTitle>
              <CardDescription>
                Inspect evidence, references, verification verdicts, and TinyFish browser output.
              </CardDescription>
            </CardHeader>
            <CardContent className="mt-4">
              {!selectedCard && (
                <EmptyState
                  title="Select a card"
                  body="Choose a card in the middle column to run verification or browser evidence."
                />
              )}

              {selectedCard && (
                <CardDetail
                  card={selectedCard}
                  onVerify={() => verifyMutation.mutate(selectedCard.id)}
                  onWebEvidence={() => webEvidenceMutation.mutate(selectedCard.id)}
                  onRetry={() => {
                    if (retryJobId) {
                      retryLatestFailedJob.mutate(retryJobId);
                    }
                  }}
                  verifyPending={verifyMutation.isPending}
                  webEvidencePending={webEvidenceMutation.isPending}
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

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-h-28 flex-col justify-between rounded-[22px] border border-black/6 bg-[linear-gradient(180deg,rgba(255,255,255,0.86),rgba(247,242,234,0.95))] p-4">
      <span className="text-[0.8rem] uppercase tracking-[0.08em] text-[#746a60]">{label}</span>
      <strong className="font-serif text-[clamp(1.75rem,3vw,2.5rem)]">{value}</strong>
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

function CardDetail({
  card,
  onVerify,
  onWebEvidence,
  onRetry,
  verifyPending,
  webEvidencePending,
  retryPending,
  canRetry,
}: {
  card: ClaimCardDetailRecord;
  onVerify: () => void;
  onWebEvidence: () => void;
  onRetry: () => void;
  verifyPending: boolean;
  webEvidencePending: boolean;
  retryPending: boolean;
  canRetry: boolean;
}) {
  const hasResolvedReference = card.references.some((item) => Boolean(item.reference.resolved_url));
  const screenshotUrl = getArtifactUrl(card.tinyfish_runs.at(-1)?.artifact_path);

  return (
    <div className="grid gap-4">
      <section className="rounded-[24px] border border-black/8 bg-[linear-gradient(145deg,rgba(245,239,228,0.96),rgba(255,255,255,0.84))] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone={card.stage}>{stageActionLabels[card.stage]}</StatusBadge>
            <KindChip>{formatClaimKind(card.claim_kind)}</KindChip>
          </div>
        </div>
        <h3 className="mt-4 font-serif text-2xl leading-tight text-[#1f2329]">
          {card.summary ?? card.claim_text ?? "Untitled card"}
        </h3>
        <p className="mt-3 text-sm leading-7 text-[#52545a]">
          {card.claim_text ?? "No claim text available for this card."}
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <Button
            disabled={!card.references.length || verifyPending}
            onClick={onVerify}
          >
            {verifyPending ? "Verifying..." : "Verify References"}
          </Button>
          <Button
            disabled={!hasResolvedReference || webEvidencePending}
            onClick={onWebEvidence}
          >
            {webEvidencePending ? "Running TinyFish..." : "Acquire Web Evidence"}
          </Button>
          {card.stage === "failed" && canRetry && (
            <Button variant="ghost" disabled={retryPending} onClick={onRetry}>
              {retryPending ? "Retrying..." : "Retry Last Stage"}
            </Button>
          )}
        </div>
      </section>

      <div className="grid gap-4 2xl:grid-cols-2">
        <DetailSection title="Evidence Spans" bodyLabel={`${card.evidence_spans.length} captured`}>
          {card.evidence_spans.length ? (
            card.evidence_spans.map((span) => (
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

        <DetailSection title="References" bodyLabel={`${card.references.length} linked`}>
          {card.references.length ? (
            card.references.map((item) => (
              <article key={item.reference.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <strong>{item.reference.ref_label ?? item.relation_type}</strong>
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
            <EmptyInline text="This card does not have any extracted references." />
          )}
        </DetailSection>

        <DetailSection title="Verification" bodyLabel={`${card.verification_results.length} verdicts`}>
          {card.verification_results.length ? (
            card.verification_results.map((result) => (
              <article key={result.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <StatusBadge tone={result.support_verdict}>{result.support_verdict}</StatusBadge>
                  <span className="text-xs text-[#70695f]">{formatLabel(result.exists_verdict)}</span>
                </div>
                <p className="mt-3 text-sm leading-6 text-[#52545a]">{result.reasoning_summary}</p>
                <small className="mt-3 block text-xs leading-5 text-[#6d6963]">
                  {result.reference.resolved_title ?? result.reference.raw_citation}
                </small>
              </article>
            ))
          ) : (
            <EmptyInline text="Run reference verification to persist support verdicts here." />
          )}
        </DetailSection>

        <DetailSection title="TinyFish Evidence" bodyLabel={`${card.tinyfish_runs.length} runs`}>
          {card.tinyfish_runs.length ? (
            <>
              {card.tinyfish_runs.map((run) => (
                <article key={run.id} className="rounded-[22px] border border-black/8 bg-white/70 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <StatusBadge tone={run.status}>{run.status}</StatusBadge>
                    {run.source_url && (
                      <a href={run.source_url} target="_blank" rel="noreferrer">
                        Visit page
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
              ) : (
                <EmptyInline text="TinyFish structured evidence is available. No screenshot artifact was persisted for the latest run." />
              )}
            </>
          ) : (
            <EmptyInline text="Run TinyFish web evidence when a live citation page needs browser-native inspection." />
          )}
        </DetailSection>
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

function formatClaimKind(kind: ClaimKind): string {
  return formatLabel(kind);
}

function formatLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function toneClassName(value: string): string {
  if (["ready", "extracted", "completed", "supported", "exists", "verified", "web_evidence_acquired", "tinyfish", "completed"].includes(value)) {
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

export default App;
