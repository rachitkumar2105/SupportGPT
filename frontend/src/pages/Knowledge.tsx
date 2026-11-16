import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { ErrorNote, Skeleton, useToast } from "../components/ui";
import { api, del, post, type Source } from "../lib/api";
import { useAuth } from "../lib/auth";
import { bytes, relative } from "../lib/format";

interface Doc {
  id: number;
  title: string;
  slug: string;
  source: string;
  mime: string;
  size_bytes: number;
  chunk_count: number;
  created_at: string;
}
interface DocDetail extends Doc {
  chunks: { id: number; ord: number; heading: string | null; page: number | null; content: string }[];
}
interface Inspect {
  results: Record<"hybrid" | "dense" | "bm25", Source[]>;
  confidence: number;
  would_abstain: boolean;
  threshold: number;
  took_ms: number;
}

export default function Knowledge() {
  const { user } = useAuth();
  const admin = user?.role === "admin";
  const toast = useToast();
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<DocDetail | null>(null);
  const [uploading, setUploading] = useState(false);
  const [query, setQuery] = useState("");
  const [inspect, setInspect] = useState<Inspect | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastFocus = useRef<HTMLElement | null>(null);

  const load = useCallback(() => {
    setErr(null);
    api<Doc[]>("/api/kb/documents")
      .then(setDocs)
      .catch((e) => setErr(e.message));
  }, []);
  useEffect(load, [load]);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      lastFocus.current?.focus();
    };
  }, [open]);

  const upload = async (f: File) => {
    if (f.size > 10 * 1024 * 1024) return toast("Files are limited to 10 MB.", "error");
    setUploading(true);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const d = await api<Doc>("/api/kb/documents", { method: "POST", body: fd });
      toast(`Added "${d.title}" as ${d.chunk_count} passages`);
      load();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (d: Doc) => {
    if (!window.confirm(`Remove "${d.title}" from the knowledge base? Answers will stop citing it immediately.`)) return;
    try {
      await del(`/api/kb/documents/${d.id}`);
      toast(`Removed "${d.title}"`);
      load();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const view = async (d: Doc, el: HTMLElement) => {
    lastFocus.current = el;
    try {
      setOpen(await api<DocDetail>(`/api/kb/documents/${d.id}`));
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const runInspect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setInspecting(true);
    try {
      setInspect(await post<Inspect>("/api/kb/search", { query, k: 5 }));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setInspecting(false);
    }
  };

  const totalChunks = docs?.reduce((a, d) => a + d.chunk_count, 0) ?? 0;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 1.2rem + 1.4vw, 2.2rem)" }}>Knowledge base</h1>
          <p>
            The only material the assistant may answer from. Each article is split by section into passages, embedded locally,
            and indexed for both meaning (vectors) and exact terms (BM25).
          </p>
        </div>
        {admin && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.md,.markdown,.txt,application/pdf,text/markdown,text/plain"
              className="sr-only"
              id="kb-file"
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
            />
            <label htmlFor="kb-file" className="btn primary" style={{ cursor: "pointer" }}>
              {uploading ? <span className="spinner" /> : <Icon name="upload" />} Add a document
            </label>
          </>
        )}
      </div>

      <section className="section" style={{ marginTop: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <h2 style={{ fontSize: "1.2rem" }}>Articles</h2>
          {docs && (
            <span className="faint num">
              {docs.length} documents, {totalChunks} passages
            </span>
          )}
        </div>
        {err && <ErrorNote text={err} retry={load} />}
        {!docs && !err && <Skeleton h={160} />}
        {docs && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Passages</th>
                  <th>Size</th>
                  <th>Added</th>
                  <th>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <button className="btn ghost sm" style={{ padding: 0, fontWeight: 700 }} onClick={(e) => view(d, e.currentTarget)}>
                        {d.title}
                      </button>
                      <div className="faint">{d.source === "seed" ? "Help center" : d.mime === "application/pdf" ? "Uploaded PDF" : "Uploaded text"}</div>
                    </td>
                    <td className="num">{d.chunk_count}</td>
                    <td className="num">{bytes(d.size_bytes)}</td>
                    <td>{relative(d.created_at)}</td>
                    <td style={{ textAlign: "right" }}>
                      {admin && (
                        <button className="btn ghost sm danger" onClick={() => remove(d)} title={`Remove ${d.title}`}>
                          <Icon name="trash" size={18} />
                          <span className="sr-only">Remove {d.title}</span>
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {admin && <p className="faint">PDF, Markdown or plain text up to 10 MB. Scanned PDFs need OCR first; duplicates are rejected.</p>}
      </section>

      <section className="section">
        <h2 style={{ fontSize: "1.2rem" }}>Retrieval inspector</h2>
        <p className="muted" style={{ maxWidth: "70ch" }}>
          See exactly what the assistant would read for a question: the vector ranking, the keyword ranking, and the fused order
          it actually uses (reciprocal rank fusion).
        </p>
        <form onSubmit={runInspect} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label htmlFor="iq" className="sr-only">
            Test question
          </label>
          <input id="iq" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. getting error E-402 on my laptop" style={{ flex: "1 1 280px" }} maxLength={500} />
          <button className="btn" disabled={inspecting}>
            {inspecting ? <span className="spinner" /> : <Icon name="search" />} Inspect
          </button>
        </form>
        {inspect && (
          <>
            <p className={inspect.would_abstain ? "notice" : "faint"}>
              Best match {inspect.confidence.toFixed(3)} against a threshold of {inspect.threshold.toFixed(2)}:{" "}
              {inspect.would_abstain ? "the assistant would decline and offer a person." : "the assistant would answer."} ({inspect.took_ms} ms)
            </p>
            <div className="split2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))" }}>
              {(["hybrid", "dense", "bm25"] as const).map((mode) => (
                <div key={mode} className="panel" style={{ padding: 14, display: "grid", gap: 10, alignContent: "start" }}>
                  <h3>{mode === "hybrid" ? "Fused (used for answers)" : mode === "dense" ? "Vectors (meaning)" : "BM25 (exact terms)"}</h3>
                  <ol style={{ margin: 0, paddingLeft: "1.2em", display: "grid", gap: 8 }}>
                    {inspect.results[mode].map((s) => (
                      <li key={s.chunk_id} style={{ fontSize: "0.88rem" }}>
                        <strong>{s.doc_title}</strong>
                        <div className="faint">{s.heading ?? "Overview"}</div>
                        <div className="faint num">
                          cos {s.dense.toFixed(3)}, bm25 {s.bm25.toFixed(2)}
                        </div>
                      </li>
                    ))}
                    {inspect.results[mode].length === 0 && <li className="faint">No matches</li>}
                  </ol>
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      {open && (
        <div className="scrim" onClick={() => setOpen(null)}>
          <div className="drawer" role="dialog" aria-modal="true" aria-labelledby="doc-title" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "start" }}>
              <div>
                <h2 id="doc-title" style={{ fontSize: "1.3rem" }}>
                  {open.title}
                </h2>
                <p className="faint">{open.chunks.length} passages, as indexed</p>
              </div>
              <button ref={closeRef} className="btn ghost icon-btn" onClick={() => setOpen(null)}>
                <Icon name="x" />
                <span className="sr-only">Close</span>
              </button>
            </div>
            {open.chunks.map((c) => (
              <div key={c.id} className="tmsg">
                <header>
                  <strong>{c.heading ?? "Overview"}</strong>
                  {c.page && <span>page {c.page}</span>}
                  <span className="num">{c.content.length} chars</span>
                </header>
                <div className="body" style={{ fontSize: "0.9rem" }}>
                  {c.content}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
