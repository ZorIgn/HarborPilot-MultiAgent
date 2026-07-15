"use client";

import { Button as IslandButton } from "animal-island-ui";
import { ExternalLink } from "lucide-react";
import { fieldLabels } from "@/lib/copy";
import type { ReviewBulkPublishResponse, ReviewPublishResponse, ReviewQueueSummary } from "@/lib/types";

type Props = {
  report: ReviewQueueSummary | null;
  publishResult: ReviewPublishResponse | null;
  bulkPublishResult: ReviewBulkPublishResponse | null;
  loading: boolean;
  onLoad: () => void;
  onDecision: (reviewId: string, decision: "approve" | "reject", persist?: boolean) => void;
  onBulkPublish: (limit?: number, persist?: boolean) => void;
};

export function ReviewQueuePanel({ report, publishResult, bulkPublishResult, loading, onLoad, onDecision, onBulkPublish }: Props) {
  if (!report) return <div className="source-report"><p>The review queue is where operators approve field evidence before students see it.</p><IslandButton type="primary" loading={loading} onClick={onLoad}>Load review queue</IslandButton></div>;
  return <div className="source-report"><section className="status-grid three"><Metric label="Pending" value={`${report.pending_count}`} detail="PENDING fields" /><Metric label="Publishable" value={`${report.publishable_count}`} detail="after approval" /><Metric label="Generated" value={formatDate(report.generated_at)} detail="queue snapshot" /></section><div className="card-actions"><IslandButton type="default" loading={loading} onClick={() => onBulkPublish(20, false)} disabled={report.publishable_count === 0}>Preview 20 publishable</IslandButton><IslandButton type="primary" loading={loading} onClick={() => onBulkPublish(20, true)} disabled={report.publishable_count === 0}>Publish 20 verified fields</IslandButton></div>{bulkPublishResult ? <p className="form-note">{bulkPublishResult.message}</p> : null}{publishResult ? <p className="form-note">{publishResult.message}</p> : null}<div className="evidence-list">{report.items.slice(0, 30).map((item) => <article key={item.review_id}><div className="program-title-row"><strong>{fieldLabels[item.field_name] ?? item.field_name}</strong><span className="tier-pill">{item.status}</span></div><p>{item.evidence_snippet ?? item.proposed_value ?? "Missing excerpt; open source to review."}</p><div className="task-meta"><span>{item.cycle ?? "cycle to verify"}</span><span>{item.confidence}</span><span>{item.publishable ? "publishable" : "needs source"}</span></div>{item.source_url ? <a className="text-link" href={item.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} aria-hidden />Open source</a> : null}<div className="card-actions"><IslandButton type="default" size="small" disabled={!item.publishable} onClick={() => onDecision(item.review_id, "approve", false)}>Preview</IslandButton><IslandButton type="primary" size="small" disabled={!item.publishable} onClick={() => onDecision(item.review_id, "approve", true)}>Publish field</IslandButton><IslandButton type="default" size="small" onClick={() => onDecision(item.review_id, "reject", false)}>Reject</IslandButton></div></article>)}</div></div>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{detail}</span></article>; }
function formatDate(value?: string | null) { if (!value) return "not recorded"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value.slice(0, 10) : date.toISOString().slice(0, 10); }
