"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ListChecks, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { research, resultHref, type Job } from "@/lib/research";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["queued", "running"]);

/** Start a job and follow it; when it finishes, go to its result page. */
export function useJob(opts: { navigate?: boolean } = {}) {
  const { navigate = true } = opts;
  const router = useRouter();
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => research.job(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && !ACTIVE.has(q.state.data.status) ? false : 800),
    // Keep following while the tab is in the background, so the result opens on return.
    refetchIntervalInBackground: true,
  });
  const done = useRef<string | null>(null);

  useEffect(() => {
    const j = job.data;
    if (!j || ACTIVE.has(j.status) || done.current === j.job_id) return;
    done.current = j.job_id;
    void qc.invalidateQueries({ queryKey: ["jobs"] });
    void qc.invalidateQueries({ queryKey: ["strategies"] });
    void qc.invalidateQueries({ queryKey: ["runs"] });
    if (j.status === "done" && j.result?.run_id && navigate) router.push(resultHref(j.kind, j.result.run_id));
  }, [job.data, navigate, qc, router]);

  const start = useCallback(
    async (submit: () => Promise<{ job_id: string }>) => {
      setError(null);
      try {
        const { job_id } = await submit();
        done.current = null;
        setJobId(job_id);
        void qc.invalidateQueries({ queryKey: ["jobs"] });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [qc],
  );

  const busy = !!job.data && ACTIVE.has(job.data.status);
  return { start, job: job.data ?? null, busy: busy || (!!jobId && !job.data), error };
}

export function JobProgress({ job, error }: { job: Job | null; error?: string | null }) {
  if (error) return <p className="text-xs text-red-400">{error}</p>;
  if (!job) return null;
  const pct = Math.round(job.progress * 100);
  return (
    <div className="space-y-1 text-xs">
      <div className="flex items-center gap-2">
        {ACTIVE.has(job.status) && <Loader2 className="size-3.5 animate-spin text-primary" />}
        <span className="font-medium">{job.title}</span>
        <span className="ml-auto font-mono text-muted-foreground">{job.status === "running" ? `${pct}%` : job.status}</span>
      </div>
      {ACTIVE.has(job.status) && (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full bg-primary transition-all" style={{ width: `${Math.max(pct, 3)}%` }} />
        </div>
      )}
      <p className={cn("text-muted-foreground", job.status === "failed" && "text-red-400")}>{job.message}</p>
    </div>
  );
}

/** Header tray: running jobs with progress, and the latest finished ones with links. */
export function JobTray() {
  const [open, setOpen] = useState(false);
  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: research.jobs,
    refetchInterval: (q) => (q.state.data?.some((j) => ACTIVE.has(j.status)) ? 1500 : 15000),
    retry: false,
  });
  const running = jobs?.filter((j) => ACTIVE.has(j.status)) ?? [];
  const recent = jobs?.slice(0, 8) ?? [];
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs",
          running.length ? "border-primary/50 text-primary" : "text-muted-foreground hover:text-foreground",
        )}
        aria-expanded={open}
      >
        {running.length ? <Loader2 className="size-3.5 animate-spin" /> : <ListChecks className="size-3.5" />}
        Jobs{running.length ? ` · ${running.length} running` : ""}
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-40 w-80 max-w-[calc(100vw-2rem)] space-y-2 rounded-lg border bg-popover p-3 shadow-xl">
          <div className="flex items-center">
            <p className="text-xs font-semibold">Research jobs</p>
            <button className="ml-auto rounded p-0.5 hover:bg-muted" aria-label="Close" onClick={() => setOpen(false)}>
              <X className="size-3.5" />
            </button>
          </div>
          {!recent.length && <p className="text-xs text-muted-foreground">No jobs yet. Backtests, optimisations and validations appear here.</p>}
          {recent.map((j) => (
            <div key={j.job_id} className="space-y-1 border-t pt-2 first:border-t-0 first:pt-0">
              <JobProgress job={j} />
              <div className="flex gap-3 text-[11px]">
                {j.status === "done" && j.result?.run_id && (
                  <Link className="text-primary hover:underline" href={resultHref(j.kind, j.result.run_id)} onClick={() => setOpen(false)}>
                    Open result
                  </Link>
                )}
                {ACTIVE.has(j.status) && (
                  <button className="text-muted-foreground hover:text-red-400" onClick={() => void research.cancel(j.job_id)}>
                    Cancel
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
