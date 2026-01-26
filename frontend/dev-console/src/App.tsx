import { useEffect, useMemo, useState } from "react";

type QueryHit = {
  modality: string;
  uri: string;
  snippet?: string | null;
  timestamp_ms?: number | null;
  score: number;
  media_asset_id?: string | null;
};

type QueryResponse = {
  results: QueryHit[];
};

type StepStatus = "idle" | "working" | "done" | "error";

type ActivityItem = {
  time: string;
  message: string;
  tone: "info" | "success" | "error";
};

const DEFAULT_QUERY_URL = "http://localhost:8080/query";
const MAX_DIMENSION = 640;
const DEFAULT_RAW_PREFIX = "raw";
const DEFAULT_INDEX_JOB = "retikon-index-builder-dev";
const DEFAULT_REGION = "us-central1";

const icons: Record<string, string> = {
  document: "📄",
  transcript: "📝",
  image: "🖼️",
  audio: "🔊",
  video: "🎬",
};

function toPercent(score: number) {
  return `${Math.round(score * 100)}%`;
}

function statusLabel(status: StepStatus) {
  switch (status) {
    case "working":
      return "Working";
    case "done":
      return "Complete";
    case "error":
      return "Needs attention";
    default:
      return "Queued";
  }
}

async function resizeImage(file: File) {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read image"));
    reader.readAsDataURL(file);
  });

  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Invalid image"));
    image.src = dataUrl;
  });

  const scale = Math.min(1, MAX_DIMENSION / Math.max(img.width, img.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    throw new Error("Canvas not supported");
  }
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

  const resized = canvas.toDataURL("image/jpeg", 0.9);
  const base64 = resized.split(",")[1];
  return { preview: resized, base64 };
}

export default function App() {
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadCategory, setUploadCategory] = useState("docs");
  const [uploadStatus, setUploadStatus] = useState<StepStatus>("idle");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadedUri, setUploadedUri] = useState("");
  const [manualUri, setManualUri] = useState("");
  const [indexStatus, setIndexStatus] = useState<StepStatus>("idle");
  const [indexError, setIndexError] = useState<string | null>(null);
  const [reloadStatus, setReloadStatus] = useState<StepStatus>("idle");
  const [reloadError, setReloadError] = useState<string | null>(null);
  const [hasQueried, setHasQueried] = useState(false);
  const [queryText, setQueryText] = useState("");
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<QueryHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");

  const queryUrl = useMemo(() => {
    return import.meta.env.VITE_QUERY_URL || DEFAULT_QUERY_URL;
  }, []);

  const queryBase = useMemo(() => {
    return queryUrl.replace(/\/query\/?$/, "");
  }, [queryUrl]);

  const reloadUrl = useMemo(() => {
    return (
      import.meta.env.VITE_RELOAD_URL || `${queryBase}/admin/reload-snapshot`
    );
  }, [queryBase]);

  const uploadUrl = import.meta.env.VITE_UPLOAD_URL || "";
  const rawBucket = import.meta.env.VITE_RAW_BUCKET || "";
  const rawPrefix = import.meta.env.VITE_RAW_PREFIX || DEFAULT_RAW_PREFIX;
  const indexUrl = import.meta.env.VITE_INDEX_URL || "";
  const indexJob = import.meta.env.VITE_INDEX_JOB || DEFAULT_INDEX_JOB;
  const region = import.meta.env.VITE_REGION || DEFAULT_REGION;
  const indexCommand =
    import.meta.env.VITE_INDEX_COMMAND ||
    `gcloud run jobs execute ${indexJob} --region ${region}`;

  const uploadCommand = useMemo(() => {
    const fileName = uploadFile?.name || "<file>";
    const prefix = rawPrefix.replace(/\/$/, "");
    const bucket = rawBucket || "<raw-bucket>";
    return `gsutil cp ${fileName} gs://${bucket}/${prefix}/${uploadCategory}/${fileName}`;
  }, [rawBucket, rawPrefix, uploadCategory, uploadFile]);

  useEffect(() => {
    const stored = localStorage.getItem("retikon_api_key");
    if (stored) {
      setApiKey(stored);
    }
  }, []);

  useEffect(() => {
    if (apiKey) {
      localStorage.setItem("retikon_api_key", apiKey);
    }
  }, [apiKey]);

  const addActivity = (message: string, tone: ActivityItem["tone"]) => {
    setActivity((prev) => [
      { time: new Date().toLocaleTimeString(), message, tone },
      ...prev,
    ].slice(0, 6));
  };

  const handleUpload = async () => {
    if (!uploadFile) {
      setUploadError("Choose a file before uploading.");
      setUploadStatus("error");
      return;
    }
    if (!uploadUrl) {
      setUploadError("Upload URL is not configured.");
      setUploadStatus("error");
      return;
    }
    setUploadError(null);
    setUploadStatus("working");
    addActivity("Uploading asset to the raw bucket...", "info");

    const body = new FormData();
    body.append("file", uploadFile);
    body.append("category", uploadCategory);
    try {
      const resp = await fetch(uploadUrl, {
        method: "POST",
        headers: apiKey ? { "X-API-Key": apiKey } : undefined,
        body,
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Upload failed");
      }
      let uri = "";
      try {
        const data = (await resp.json()) as Record<string, unknown>;
        uri =
          (data.uri as string) ||
          (data.gcs_uri as string) ||
          (data.object_uri as string) ||
          (data.objectUri as string) ||
          "";
      } catch {
        uri = "";
      }
      if (uri) {
        setUploadedUri(uri);
      }
      setUploadStatus("done");
      addActivity("Upload complete. Ready to build the index.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setUploadError(message);
      setUploadStatus("error");
      addActivity(message, "error");
    }
  };

  const applyManualUri = () => {
    if (!manualUri.trim()) {
      setUploadError("Paste the GCS object URI.");
      setUploadStatus("error");
      return;
    }
    setUploadError(null);
    setUploadedUri(manualUri.trim());
    setUploadStatus("done");
    addActivity("Using provided GCS object URI.", "success");
  };

  const triggerIndex = async () => {
    if (!indexUrl) {
      setIndexError("Index trigger URL is not configured.");
      setIndexStatus("error");
      return;
    }
    setIndexError(null);
    setIndexStatus("working");
    addActivity("Index build started.", "info");
    try {
      const resp = await fetch(indexUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-API-Key": apiKey } : {}),
        },
        body: JSON.stringify({ source_uri: uploadedUri || null }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Index build failed");
      }
      setIndexStatus("done");
      addActivity("Index build finished.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setIndexError(message);
      setIndexStatus("error");
      addActivity(message, "error");
    }
  };

  const reloadSnapshot = async () => {
    if (!apiKey) {
      setReloadError("API key required to reload snapshot.");
      setReloadStatus("error");
      return;
    }
    setReloadError(null);
    setReloadStatus("working");
    addActivity("Reloading query snapshot...", "info");
    try {
      const resp = await fetch(reloadUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey,
        },
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Snapshot reload failed");
      }
      setReloadStatus("done");
      addActivity("Snapshot reloaded.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setReloadError(message);
      setReloadStatus("error");
      addActivity(message, "error");
    }
  };

  const handleImageChange = async (file: File | null) => {
    if (!file) {
      setImageBase64(null);
      setImagePreview(null);
      return;
    }
    try {
      const resized = await resizeImage(file);
      setImageBase64(resized.base64);
      setImagePreview(resized.preview);
    } catch (err) {
      setQueryError((err as Error).message);
    }
  };

  const handleSubmit = async () => {
    setQueryError(null);
    setLoading(true);
    setResults([]);
    setHasQueried(true);

    const payload: Record<string, unknown> = {
      top_k: topK,
    };
    if (queryText.trim()) {
      payload.query_text = queryText.trim();
    }
    if (imageBase64) {
      payload.image_base64 = imageBase64;
    }

    try {
      const resp = await fetch(queryUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-API-Key": apiKey } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Query failed");
      }

      const data = (await resp.json()) as QueryResponse;
      setResults(data.results || []);
      addActivity("Query completed.", "success");
    } catch (err) {
      setQueryError((err as Error).message);
      addActivity((err as Error).message, "error");
    } finally {
      setLoading(false);
    }
  };

  const curlCommand = () => {
    const payload: Record<string, unknown> = { top_k: topK };
    if (queryText.trim()) {
      payload.query_text = queryText.trim();
    }
    if (imageBase64) {
      payload.image_base64 = imageBase64;
    }

    const headers = ["-H 'Content-Type: application/json'"];
    if (apiKey) {
      headers.push(`-H 'X-API-Key: ${apiKey}'`);
    }
    return `curl -X POST ${queryUrl} ${headers.join(" ")} -d '${JSON.stringify(
      payload,
    )}'`;
  };

  const copyCurl = async () => {
    await navigator.clipboard.writeText(curlCommand());
  };

  const copyUploadCommand = async () => {
    await navigator.clipboard.writeText(uploadCommand);
    addActivity("Upload command copied.", "info");
  };

  const copyIndexCommand = async () => {
    await navigator.clipboard.writeText(indexCommand);
    addActivity("Index command copied.", "info");
  };

  return (
    <div className="app">
      <header className="hero">
        <p className="eyebrow">Retikon Dev Console</p>
        <h1>Ingest. Index. Query.</h1>
        <p className="subtitle">
          Walk a file through the full pipeline, then interrogate the graph with
          text or image queries.
        </p>
        <div className="hero-tags">
          <span>Upload</span>
          <span>Index Build</span>
          <span>Query</span>
        </div>
      </header>

      <section className="pipeline">
        <aside className="steps">
          {[
            {
              title: "Upload",
              detail: "Push assets into raw storage.",
              status: uploadStatus,
            },
            {
              title: "Index",
              detail: "Build the snapshot + HNSW.",
              status: indexStatus,
            },
            {
              title: "Query",
              detail: "Search across modalities.",
              status: loading ? "working" : hasQueried ? "done" : "idle",
            },
          ].map((step) => (
            <div key={step.title} className={`step-card ${step.status}`}>
              <div>
                <p className="step-title">{step.title}</p>
                <p className="step-detail">{step.detail}</p>
              </div>
              <span className="step-status">{statusLabel(step.status)}</span>
            </div>
          ))}
        </aside>

        <div className="workspace">
          <section className="panel step-panel">
            <div className="panel-header">
              <h2>Step 1 — Upload</h2>
              <span className="status-dot" aria-hidden="true" />
            </div>

            <div className="step-grid">
              <div>
                <label className="field">
                  <span>Asset</span>
                  <input
                    type="file"
                    onChange={(event) =>
                      setUploadFile(event.target.files?.[0] ?? null)
                    }
                  />
                </label>
                <label className="field">
                  <span>Category</span>
                  <select
                    value={uploadCategory}
                    onChange={(event) => setUploadCategory(event.target.value)}
                  >
                    <option value="docs">Docs</option>
                    <option value="images">Images</option>
                    <option value="audio">Audio</option>
                    <option value="videos">Videos</option>
                  </select>
                </label>

                <div className="actions">
                  <button
                    onClick={handleUpload}
                    disabled={!uploadUrl || uploadStatus === "working"}
                  >
                    {uploadStatus === "working"
                      ? "Uploading..."
                      : "Upload to raw bucket"}
                  </button>
                  <button className="ghost" onClick={copyUploadCommand}>
                    Copy gsutil
                  </button>
                </div>
                <p className="hint">
                  {uploadUrl
                    ? "Upload runs through the configured dev uploader."
                    : "No upload endpoint configured. Use the gsutil command."}
                </p>
                {uploadError && <p className="error">{uploadError}</p>}
              </div>

              <div className="helper-card">
                <h3>Manual upload</h3>
                <p className="hint">
                  After uploading manually, paste the object URI so the console
                  can track it.
                </p>
                <code className="command">{uploadCommand}</code>
                <input
                  type="text"
                  placeholder="gs://retikon-raw.../raw/docs/your-file.pdf"
                  value={manualUri}
                  onChange={(event) => setManualUri(event.target.value)}
                />
                <button className="ghost" onClick={applyManualUri}>
                  Save URI
                </button>
                {uploadedUri && (
                  <div className="uploaded">
                    <span>Tracking</span>
                    <p>{uploadedUri}</p>
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="panel step-panel">
            <div className="panel-header">
              <h2>Step 2 — Index</h2>
              <span className="status-dot" aria-hidden="true" />
            </div>

            <div className="step-grid">
              <div>
                <p className="hint">
                  Kick off the Cloud Run index builder, then reload the snapshot
                  for queries.
                </p>
                <div className="actions">
                  <button
                    onClick={triggerIndex}
                    disabled={!indexUrl || indexStatus === "working"}
                  >
                    {indexStatus === "working"
                      ? "Building..."
                      : "Trigger index build"}
                  </button>
                  <button className="ghost" onClick={copyIndexCommand}>
                    Copy gcloud
                  </button>
                </div>
                {indexError && <p className="error">{indexError}</p>}
              </div>

              <div className="helper-card">
                <h3>Reload snapshot</h3>
                <p className="hint">
                  Use the query service admin endpoint after the index job
                  finishes.
                </p>
                <code className="command">{indexCommand}</code>
                <button
                  onClick={reloadSnapshot}
                  disabled={reloadStatus === "working"}
                >
                  {reloadStatus === "working" ? "Reloading..." : "Reload now"}
                </button>
                <p className="endpoint">Endpoint: {reloadUrl}</p>
                {reloadError && <p className="error">{reloadError}</p>}
              </div>
            </div>
          </section>

          <section className="panel step-panel">
            <div className="panel-header">
              <h2>Step 3 — Query</h2>
              <span className="status-dot" aria-hidden="true" />
            </div>

            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault();
                handleSubmit();
              }}
            >
              <label className="field">
                <span>API key</span>
                <input
                  type="password"
                  placeholder="Paste your X-API-Key"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                />
              </label>

              <label className="field">
                <span>Text prompt</span>
                <textarea
                  placeholder="Search for launch sequences, applause, or slide themes"
                  value={queryText}
                  onChange={(event) => setQueryText(event.target.value)}
                  rows={3}
                />
              </label>

              <label className="field">
                <span>Reference image</span>
                <div className="file-row">
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(event) =>
                      handleImageChange(event.target.files?.[0] ?? null)
                    }
                  />
                  {imagePreview && (
                    <img src={imagePreview} alt="Preview" />
                  )}
                </div>
              </label>

              <label className="field">
                <span>Top K</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={topK}
                  onChange={(event) => setTopK(Number(event.target.value))}
                />
              </label>
            </form>

            <div className="actions">
              <button onClick={handleSubmit} disabled={loading}>
                {loading ? "Querying..." : "Run query"}
              </button>
              <button className="ghost" onClick={copyCurl}>
                Copy curl
              </button>
            </div>

            {queryError && <p className="error">{queryError}</p>}
          </section>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Results</h2>
          <span className="counter">{results.length} hits</span>
        </div>

        <div className="results">
          {results.length === 0 && (
            <div className="empty">
              <p>
                {hasQueried
                  ? "No results yet. Upload data, build the index, then query again."
                  : "No results yet. Upload data, build the index, then query."}
              </p>
            </div>
          )}
          {results.map((item, idx) => (
            <article className="result-card" key={`${item.uri}-${idx}`}>
              <div className="result-meta">
                <span className="result-icon">{icons[item.modality] ?? "🔍"}</span>
                <div>
                  <h3>{item.modality}</h3>
                  <p className="score">{toPercent(item.score)}</p>
                </div>
              </div>
              <div className="result-body">
                <p className="uri">{item.uri}</p>
                {item.snippet && <p className="snippet">{item.snippet}</p>}
                {item.timestamp_ms !== null && item.timestamp_ms !== undefined && (
                  <p className="timestamp">@ {item.timestamp_ms} ms</p>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="panel activity-panel">
        <div className="panel-header">
          <h2>Activity</h2>
          <span className="counter">{activity.length} events</span>
        </div>
        {activity.length === 0 ? (
          <p className="hint">Actions you take will appear here.</p>
        ) : (
          <ul className="activity-list">
            {activity.map((item, idx) => (
              <li key={`${item.time}-${idx}`} className={item.tone}>
                <span>{item.time}</span>
                <p>{item.message}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="footer">
        <div>
          <h4>Endpoint</h4>
          <p>{queryUrl}</p>
        </div>
        <div>
          <h4>Pipeline notes</h4>
          <p>Upload → index → reload snapshot → query.</p>
        </div>
      </footer>
    </div>
  );
}
