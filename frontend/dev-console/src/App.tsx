import { useEffect, useMemo, useState } from "react";

type QueryHit = {
  modality: string;
  uri: string;
  snippet?: string | null;
  timestamp_ms?: number | null;
  thumbnail_uri?: string | null;
  score: number;
  media_asset_id?: string | null;
  media_type?: string | null;
};

type QueryResponse = {
  results: QueryHit[];
};

type UploadInfo = {
  uri: string;
  run_id: string;
  bucket: string;
  name: string;
  generation: string;
  size_bytes: number;
  content_type?: string | null;
};

type IngestStatus = {
  status: string;
  doc_id?: string;
  bucket?: string;
  name?: string;
  generation?: string;
  firestore?: Record<string, unknown> | null;
};

type ManifestFile = {
  uri: string;
  rows: number;
  bytes_written: number;
  sha256: string;
};

type ManifestData = {
  manifest_uri?: string;
  pipeline_version?: string;
  schema_version?: string;
  started_at?: string;
  completed_at?: string;
  counts?: Record<string, number>;
  files?: ManifestFile[];
};

type ParquetPreview = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  preview_count: number;
  row_count?: number | null;
};

type KeyframePreview = {
  frame_index?: number | null;
  timestamp_ms?: number | null;
  thumbnail_uri?: string | null;
  width_px?: number | null;
  height_px?: number | null;
};

type SnapshotStatus = {
  snapshot_uri: string;
  metadata?: Record<string, unknown>;
};

type IndexStatus = {
  job_name: string;
  latest_execution?: string | null;
  completion_status?: string | null;
  completion_time?: string | null;
};

type StepStatus = "idle" | "working" | "done" | "error";
type ConsoleTab = "console" | "settings";

type ActivityItem = {
  time: string;
  message: string;
  tone: "info" | "success" | "error";
};

const DEFAULT_QUERY_URL = "http://localhost:8080/query";
const DEFAULT_RAW_PREFIX = "raw";
const DEFAULT_INDEX_JOB = "retikon-index-builder-dev";
const DEFAULT_REGION = "us-central1";
const MAX_DIMENSION = 640;
const SEGMENT_PREVIEW_SECONDS = 5;

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
  const [uploadInfo, setUploadInfo] = useState<UploadInfo | null>(null);
  const [uploadedUri, setUploadedUri] = useState("");
  const [manualUri, setManualUri] = useState("");
  const [ingestStatus, setIngestStatus] = useState<IngestStatus | null>(null);
  const [ingestStatusState, setIngestStatusState] = useState<StepStatus>("idle");
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [manifest, setManifest] = useState<ManifestData | null>(null);
  const [manifestStatus, setManifestStatus] = useState<StepStatus>("idle");
  const [manifestError, setManifestError] = useState<string | null>(null);
  const [manifestUri, setManifestUri] = useState("");
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [parquetPreview, setParquetPreview] = useState<ParquetPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [keyframes, setKeyframes] = useState<KeyframePreview[]>([]);
  const [keyframeError, setKeyframeError] = useState<string | null>(null);
  const [snapshotStatus, setSnapshotStatus] = useState<SnapshotStatus | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [reloadStatus, setReloadStatus] = useState<StepStatus>("idle");
  const [reloadError, setReloadError] = useState<string | null>(null);
  const [autoIndexBuild, setAutoIndexBuild] = useState(true);
  const [autoReloadSnapshot, setAutoReloadSnapshot] = useState(true);
  const [autoIndexTriggered, setAutoIndexTriggered] = useState(false);
  const [autoReloadTriggered, setAutoReloadTriggered] = useState(false);
  const [assetPreviewUrl, setAssetPreviewUrl] = useState<string | null>(null);
  const [assetPreviewType, setAssetPreviewType] = useState<string | null>(null);
  const [hasQueried, setHasQueried] = useState(false);
  const [queryText, setQueryText] = useState("");
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<QueryHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [activeTab, setActiveTab] = useState<ConsoleTab>("console");
  const [devApiOverride, setDevApiOverride] = useState("");
  const [queryUrlOverride, setQueryUrlOverride] = useState("");
  const [thumbUrls, setThumbUrls] = useState<Record<string, string>>({});
  const [videoUrls, setVideoUrls] = useState<Record<string, string>>({});
  const [videoLoading, setVideoLoading] = useState<Record<string, boolean>>({});

  const queryUrl = useMemo(() => {
    return (
      queryUrlOverride ||
      import.meta.env.VITE_QUERY_URL ||
      DEFAULT_QUERY_URL
    );
  }, [queryUrlOverride]);

  const devApiUrl = useMemo(() => {
    return (
      devApiOverride ||
      import.meta.env.VITE_DEV_API_URL ||
      ""
    );
  }, [devApiOverride]);

  const queryBase = useMemo(() => {
    return queryUrl.replace(/\/query\/?$/, "");
  }, [queryUrl]);

  const reloadUrl = useMemo(() => {
    if (devApiUrl) {
      return `${devApiUrl}/dev/snapshot-reload`;
    }
    return import.meta.env.VITE_RELOAD_URL || `${queryBase}/admin/reload-snapshot`;
  }, [devApiUrl, queryBase]);

  const uploadUrl =
    import.meta.env.VITE_UPLOAD_URL ||
    (devApiUrl ? `${devApiUrl}/dev/upload` : "");
  const ingestStatusUrl = devApiUrl ? `${devApiUrl}/dev/ingest-status` : "";
  const manifestUrl = devApiUrl ? `${devApiUrl}/dev/manifest` : "";
  const parquetPreviewUrl = devApiUrl ? `${devApiUrl}/dev/parquet-preview` : "";
  const snapshotUrl = devApiUrl ? `${devApiUrl}/dev/snapshot-status` : "";
  const graphObjectUrl = devApiUrl ? `${devApiUrl}/dev/graph-object` : "";
  const indexUrl =
    import.meta.env.VITE_INDEX_URL ||
    (devApiUrl ? `${devApiUrl}/dev/index-build` : "");
  const indexStatusUrl = devApiUrl ? `${devApiUrl}/dev/index-status` : "";
  const objectUrl = devApiUrl ? `${devApiUrl}/dev/object` : "";

  const rawBucket = import.meta.env.VITE_RAW_BUCKET || "";
  const rawPrefix = import.meta.env.VITE_RAW_PREFIX || DEFAULT_RAW_PREFIX;
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
    const devOverride = localStorage.getItem("retikon_dev_api_url");
    if (devOverride) {
      setDevApiOverride(devOverride);
    }
    const queryOverride = localStorage.getItem("retikon_query_url");
    if (queryOverride) {
      setQueryUrlOverride(queryOverride);
    }
  }, []);

  useEffect(() => {
    if (apiKey) {
      localStorage.setItem("retikon_api_key", apiKey);
    }
  }, [apiKey]);

  useEffect(() => {
    if (devApiOverride) {
      localStorage.setItem("retikon_dev_api_url", devApiOverride);
    } else {
      localStorage.removeItem("retikon_dev_api_url");
    }
  }, [devApiOverride]);

  useEffect(() => {
    if (queryUrlOverride) {
      localStorage.setItem("retikon_query_url", queryUrlOverride);
    } else {
      localStorage.removeItem("retikon_query_url");
    }
  }, [queryUrlOverride]);


  const addActivity = (message: string, tone: ActivityItem["tone"]) => {
    setActivity((prev) => [
      { time: new Date().toLocaleTimeString(), message, tone },
      ...prev,
    ].slice(0, 6));
  };

  const devHeaders = () => {
    return apiKey ? { "X-API-Key": apiKey } : {};
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
        headers: devHeaders(),
        body,
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Upload failed");
      }
      const data = (await resp.json()) as UploadInfo;
      setUploadInfo(data);
      setUploadedUri(data.uri);
      setIngestStatus(null);
      setManifest(null);
      setKeyframes([]);
      setIndexStatus(null);
      setSnapshotStatus(null);
      setResults([]);
      setAutoIndexTriggered(false);
      setAutoReloadTriggered(false);
      setUploadStatus("done");
      addActivity("Upload complete. Ready to check ingest status.", "success");
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
    setIngestStatus(null);
    setManifest(null);
    setKeyframes([]);
    setIndexStatus(null);
    setSnapshotStatus(null);
    setResults([]);
    setAutoIndexTriggered(false);
    setAutoReloadTriggered(false);
    setUploadStatus("done");
    addActivity("Using provided GCS object URI.", "success");
  };

  const fetchIngestStatus = async () => {
    if (!ingestStatusUrl) {
      setIngestError("Dev API is not configured.");
      setIngestStatusState("error");
      return;
    }
    const uri = uploadedUri || manualUri.trim();
    if (!uri) {
      setIngestError("Upload or paste a GCS URI first.");
      setIngestStatusState("error");
      return;
    }
    setIngestError(null);
    setIngestStatusState("working");
    addActivity("Checking ingest status...", "info");
    try {
      const resp = await fetch(`${ingestStatusUrl}?uri=${encodeURIComponent(uri)}`, {
        headers: devHeaders(),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Failed to read status");
      }
      const data = (await resp.json()) as IngestStatus;
      setIngestStatus(data);
      setIngestStatusState(data.status === "COMPLETED" ? "done" : "working");
      addActivity(`Ingest status: ${data.status}`, "success");
    } catch (err) {
      const message = (err as Error).message;
      setIngestError(message);
      setIngestStatusState("error");
      addActivity(message, "error");
    }
  };

  const fetchManifest = async () => {
    if (!manifestUrl) {
      setManifestError("Dev API is not configured.");
      setManifestStatus("error");
      return;
    }
    const uri = manifestUri || (ingestStatus?.firestore?.manifest_uri as string);
    if (!uri) {
      setManifestError("Provide a manifest URI or complete ingestion.");
      setManifestStatus("error");
      return;
    }
    setManifestError(null);
    setManifestStatus("working");
    addActivity("Loading GraphAr manifest...", "info");
    try {
      const resp = await fetch(
        `${manifestUrl}?manifest_uri_value=${encodeURIComponent(uri)}`,
        { headers: devHeaders() },
      );
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Manifest load failed");
      }
      const data = (await resp.json()) as ManifestData;
      setManifest(data);
      setKeyframes([]);
      setManifestStatus("done");
      addActivity("Manifest loaded.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setManifestError(message);
      setManifestStatus("error");
      addActivity(message, "error");
    }
  };

  const fetchParquetPreview = async (path: string) => {
    if (!parquetPreviewUrl) {
      setPreviewError("Dev API is not configured.");
      return;
    }
    setPreviewError(null);
    setPreviewPath(path);
    setParquetPreview(null);
    addActivity("Loading parquet preview...", "info");
    try {
      const resp = await fetch(
        `${parquetPreviewUrl}?path=${encodeURIComponent(path)}&limit=5`,
        { headers: devHeaders() },
      );
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Preview failed");
      }
      const data = (await resp.json()) as ParquetPreview;
      setParquetPreview(data);
      addActivity("Preview loaded.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setPreviewError(message);
      addActivity(message, "error");
    }
  };

  const fetchKeyframes = async () => {
    if (!parquetPreviewUrl) {
      setKeyframeError("Dev API is not configured.");
      return;
    }
    if (!manifest?.files?.length) {
      setKeyframeError("Load a manifest first.");
      return;
    }
    const imageCore = manifest.files.find((file) =>
      file.uri.includes("/vertices/ImageAsset/core/"),
    );
    if (!imageCore) {
      setKeyframeError("No ImageAsset core file found in manifest.");
      return;
    }
    setKeyframeError(null);
    addActivity("Loading keyframe previews...", "info");
    try {
      const resp = await fetch(
        `${parquetPreviewUrl}?path=${encodeURIComponent(imageCore.uri)}&limit=25`,
        { headers: devHeaders() },
      );
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Keyframe preview failed");
      }
      const data = (await resp.json()) as ParquetPreview;
      const rows = (data.rows || []) as KeyframePreview[];
      setKeyframes(rows);
      addActivity("Keyframes loaded.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setKeyframeError(message);
      addActivity(message, "error");
    }
  };

  const fetchSnapshotStatus = async () => {
    if (!snapshotUrl) {
      setSnapshotError("Dev API is not configured.");
      return;
    }
    setSnapshotError(null);
    addActivity("Loading snapshot metadata...", "info");
    try {
      const resp = await fetch(snapshotUrl, { headers: devHeaders() });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Snapshot status failed");
      }
      const data = (await resp.json()) as SnapshotStatus;
      setSnapshotStatus(data);
      addActivity("Snapshot metadata loaded.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setSnapshotError(message);
      addActivity(message, "error");
    }
  };

  const triggerIndex = async () => {
    if (!indexUrl) {
      setIndexError("Index trigger URL is not configured.");
      return;
    }
    setIndexError(null);
    addActivity("Index build started.", "info");
    try {
      const resp = await fetch(indexUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...devHeaders(),
        },
        body: JSON.stringify({ source_uri: uploadedUri || null }),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Index build failed");
      }
      await fetchIndexStatus();
      addActivity("Index build triggered.", "success");
    } catch (err) {
      const message = (err as Error).message;
      setIndexError(message);
      addActivity(message, "error");
    }
  };

  const fetchIndexStatus = async () => {
    if (!indexStatusUrl) {
      return;
    }
    try {
      const resp = await fetch(indexStatusUrl, { headers: devHeaders() });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Index status failed");
      }
      const data = (await resp.json()) as IndexStatus;
      setIndexStatus(data);
    } catch (err) {
      setIndexError((err as Error).message);
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

  const previewObject = async (uri: string) => {
    if (!objectUrl) {
      addActivity("Dev API is not configured for previews.", "error");
      return;
    }
    try {
      const resp = await fetch(`${objectUrl}?uri=${encodeURIComponent(uri)}`, {
        headers: devHeaders(),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Preview failed");
      }
      const contentType = resp.headers.get("content-type");
      const blob = await resp.blob();
      const preview = URL.createObjectURL(blob);
      if (assetPreviewUrl) {
        URL.revokeObjectURL(assetPreviewUrl);
      }
      setAssetPreviewUrl(preview);
      setAssetPreviewType(contentType);
      addActivity("Preview loaded.", "success");
    } catch (err) {
      addActivity((err as Error).message, "error");
    }
  };

  const fetchGraphObject = async (uri: string) => {
    if (!graphObjectUrl) {
      addActivity("Dev API is not configured for graph previews.", "error");
      return null;
    }
    if (!apiKey) {
      return null;
    }
    if (thumbUrls[uri]) {
      return thumbUrls[uri];
    }
    try {
      const resp = await fetch(`${graphObjectUrl}?uri=${encodeURIComponent(uri)}`, {
        headers: devHeaders(),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Graph preview failed");
      }
      const blob = await resp.blob();
      const preview = URL.createObjectURL(blob);
      setThumbUrls((prev) => ({ ...prev, [uri]: preview }));
      return preview;
    } catch (err) {
      addActivity((err as Error).message, "error");
      return null;
    }
  };

  const loadVideoPreview = async (uri: string) => {
    if (!objectUrl) {
      addActivity("Dev API is not configured for previews.", "error");
      return;
    }
    if (!apiKey) {
      addActivity("API key required to load video previews.", "error");
      return;
    }
    if (videoUrls[uri] || videoLoading[uri]) {
      return;
    }
    setVideoLoading((prev) => ({ ...prev, [uri]: true }));
    try {
      const resp = await fetch(`${objectUrl}?uri=${encodeURIComponent(uri)}`, {
        headers: devHeaders(),
      });
      if (!resp.ok) {
        const detail = await resp.text();
        throw new Error(detail || "Video preview failed");
      }
      const blob = await resp.blob();
      const preview = URL.createObjectURL(blob);
      setVideoUrls((prev) => ({ ...prev, [uri]: preview }));
      addActivity("Video preview loaded.", "success");
    } catch (err) {
      addActivity((err as Error).message, "error");
    } finally {
      setVideoLoading((prev) => ({ ...prev, [uri]: false }));
    }
  };

  useEffect(() => {
    keyframes.forEach((frame) => {
      if (frame.thumbnail_uri) {
        void fetchGraphObject(frame.thumbnail_uri);
      }
    });
  }, [keyframes]);

  useEffect(() => {
    results.forEach((item) => {
      if (item.thumbnail_uri) {
        void fetchGraphObject(item.thumbnail_uri);
      }
    });
  }, [results]);

  useEffect(() => {
    if (!autoIndexBuild || autoIndexTriggered) {
      return;
    }
    if (ingestStatus?.status === "COMPLETED") {
      setAutoIndexTriggered(true);
      void triggerIndex();
    }
  }, [autoIndexBuild, autoIndexTriggered, ingestStatus]);

  useEffect(() => {
    if (!autoReloadSnapshot || autoReloadTriggered) {
      return;
    }
    if (indexStatus?.completion_status === "SUCCEEDED") {
      setAutoReloadTriggered(true);
      void reloadSnapshot();
    }
  }, [autoReloadSnapshot, autoReloadTriggered, indexStatus]);

  const handleSubmit = async () => {
    setQueryError(null);
    setLoading(true);
    setResults([]);
    setHasQueried(true);
    setVideoUrls({});
    setVideoLoading({});

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

  const steps = [
    {
      title: "Upload",
      detail: "Push assets into raw storage.",
      status: uploadStatus,
    },
    {
      title: "Ingest",
      detail: "Wait for pipelines + Firestore.",
      status: ingestStatusState,
    },
    {
      title: "GraphAr",
      detail: "Inspect manifests + parquet outputs.",
      status: manifestStatus,
    },
    {
      title: "Index",
      detail: "Build snapshot + reload.",
      status: indexStatus ? "done" : "idle",
    },
    {
      title: "Query",
      detail: "Search across modalities.",
      status: loading ? "working" : hasQueried ? "done" : "idle",
    },
  ];

  return (
    <div className="app">
      <header className="hero">
        <p className="eyebrow">Retikon Dev Console</p>
        <h1>Ingest. Inspect. Index. Query.</h1>
        <p className="subtitle">
          Drive a file through the pipeline, verify model outputs, and validate
          the final query layer.
        </p>
        <div className="hero-tags">
          <span>Upload</span>
          <span>Ingest</span>
          <span>GraphAr</span>
          <span>Index</span>
          <span>Query</span>
        </div>
      </header>

      <div className="tabs">
        <button
          className={`tab ${activeTab === "console" ? "active" : ""}`}
          type="button"
          onClick={() => setActiveTab("console")}
        >
          Console
        </button>
        <button
          className={`tab ${activeTab === "settings" ? "active" : ""}`}
          type="button"
          onClick={() => setActiveTab("settings")}
        >
          Settings
        </button>
      </div>

      {activeTab === "settings" && (
        <section className="panel settings-panel">
          <div className="panel-header">
            <h2>Configuration</h2>
            <span className="status-dot" aria-hidden="true" />
          </div>
          <p className="panel-help">
            These settings apply to every step. Changes are saved locally in
            your browser.
          </p>
          <div className="settings-grid">
            <label className="field">
              <span>API key</span>
              <input
                type="password"
                placeholder="Paste your X-API-Key"
                value={apiKey}
                autoComplete="new-password"
                onChange={(event) => setApiKey(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Dev API URL</span>
              <input
                type="url"
                placeholder="https://retikon-dev-console-...run.app"
                value={devApiOverride}
                onChange={(event) => setDevApiOverride(event.target.value)}
              />
              <small>
                Default: {import.meta.env.VITE_DEV_API_URL || "none"}
              </small>
            </label>
            <label className="field">
              <span>Query API URL</span>
              <input
                type="url"
                placeholder="https://retikon-query-...run.app/query"
                value={queryUrlOverride}
                onChange={(event) => setQueryUrlOverride(event.target.value)}
              />
              <small>
                Default: {import.meta.env.VITE_QUERY_URL || DEFAULT_QUERY_URL}
              </small>
            </label>
          </div>
        </section>
      )}

      {activeTab === "console" && (
      <section className="pipeline">
        <aside className="steps">
          {steps.map((step) => (
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
                    ? "Upload runs through the dev console API."
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
                {uploadInfo && (
                  <div className="meta-grid">
                    <p>Run ID: {uploadInfo.run_id}</p>
                    <p>Size: {uploadInfo.size_bytes} bytes</p>
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="panel step-panel">
            <div className="panel-header">
              <h2>Step 2 — Ingest Status</h2>
              <span className="status-dot" aria-hidden="true" />
            </div>

            <div className="step-grid">
              <div>
                <p className="hint">
                  Pull Firestore ingestion state for this object.
                </p>
                <div className="actions">
                  <button onClick={fetchIngestStatus}>Refresh status</button>
                </div>
                {ingestError && <p className="error">{ingestError}</p>}
              </div>
              <div className="helper-card">
                <h3>Status</h3>
                <p className="hint">
                  {ingestStatus
                    ? `Status: ${ingestStatus.status}`
                    : "No status loaded yet."}
                </p>
                {ingestStatus && (
                  <div className="meta-grid">
                    <p>Doc ID: {ingestStatus.doc_id}</p>
                    <p>Generation: {ingestStatus.generation}</p>
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="panel step-panel">
            <div className="panel-header">
              <h2>Step 3 — GraphAr + Model Outputs</h2>
              <span className="status-dot" aria-hidden="true" />
            </div>

            <div className="step-grid">
              <div>
                <label className="field">
                  <span>Manifest URI</span>
                  <input
                    type="text"
                    placeholder="gs://retikon-graph.../manifests/<run-id>/manifest.json"
                    value={manifestUri}
                    onChange={(event) => setManifestUri(event.target.value)}
                  />
                </label>
                <div className="actions">
                  <button onClick={fetchManifest}>Load manifest</button>
                </div>
                {manifestError && <p className="error">{manifestError}</p>}
              </div>
              <div className="helper-card">
                <h3>Manifest summary</h3>
                {manifest ? (
                  <div className="meta-grid">
                    <p>Pipeline: {manifest.pipeline_version}</p>
                    <p>Schema: {manifest.schema_version}</p>
                    <p>Started: {manifest.started_at}</p>
                    <p>Completed: {manifest.completed_at}</p>
                  </div>
                ) : (
                  <p className="hint">No manifest loaded yet.</p>
                )}
              </div>
            </div>

            {manifest?.files && (
              <div className="artifact-grid">
                {manifest.files.map((file) => (
                  <div className="artifact-card" key={file.uri}>
                    <p className="uri">{file.uri}</p>
                    <p className="hint">Rows: {file.rows}</p>
                    <button onClick={() => fetchParquetPreview(file.uri)}>
                      Preview rows
                    </button>
                  </div>
                ))}
              </div>
            )}

            {previewPath && (
              <div className="preview-panel">
                <h3>Preview: {previewPath}</h3>
                {previewError && <p className="error">{previewError}</p>}
                {parquetPreview ? (
                  <pre className="preview-json">
                    {JSON.stringify(parquetPreview, null, 2)}
                  </pre>
                ) : (
                  <p className="hint">Loading preview...</p>
                )}
              </div>
            )}

            {manifest && (
              <div className="preview-panel">
                <div className="panel-header">
                  <h3>Keyframes</h3>
                  <div className="actions">
                    <button onClick={fetchKeyframes}>Load keyframes</button>
                  </div>
                </div>
                {keyframeError && <p className="error">{keyframeError}</p>}
                {keyframes.length === 0 ? (
                  <p className="hint">
                    Load keyframes to preview what the model indexed from video
                    frames.
                  </p>
                ) : (
                  <div className="keyframe-grid">
                    {keyframes.map((frame, idx) => {
                      const thumb =
                        frame.thumbnail_uri &&
                        thumbUrls[frame.thumbnail_uri];
                      const timestamp =
                        frame.timestamp_ms !== null &&
                        frame.timestamp_ms !== undefined
                          ? `${Math.round(frame.timestamp_ms / 1000)}s`
                          : "n/a";
                      return (
                        <figure className="keyframe-card" key={`kf-${idx}`}>
                          {thumb ? (
                            <img src={thumb} alt={`Frame ${idx}`} />
                          ) : (
                            <div className="placeholder">Loading...</div>
                          )}
                          <figcaption>
                            <span>Frame {frame.frame_index ?? idx}</span>
                            <span>{timestamp}</span>
                          </figcaption>
                        </figure>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="panel step-panel">
            <div className="panel-header">
              <h2>Step 4 — Index + Snapshot</h2>
              <span className="status-dot" aria-hidden="true" />
            </div>

            <div className="step-grid">
              <div>
                <p className="hint">
                  Trigger the index build, then reload the snapshot for queries.
                </p>
                <div className="actions">
                  <button onClick={triggerIndex} disabled={!indexUrl}>
                    Trigger index build
                  </button>
                  <button className="ghost" onClick={copyIndexCommand}>
                    Copy gcloud
                  </button>
                  <button className="ghost" onClick={fetchIndexStatus}>
                    Refresh index status
                  </button>
                </div>
                <div className="automation">
                  <label>
                    <input
                      type="checkbox"
                      checked={autoIndexBuild}
                      onChange={(event) => setAutoIndexBuild(event.target.checked)}
                    />
                    Auto-build index after ingest completes
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={autoReloadSnapshot}
                      onChange={(event) =>
                        setAutoReloadSnapshot(event.target.checked)
                      }
                    />
                    Auto-reload snapshot after index completes
                  </label>
                </div>
                {indexError && <p className="error">{indexError}</p>}
              </div>

              <div className="helper-card">
                <h3>Snapshot</h3>
                <p className="hint">Reload snapshot after index completes.</p>
                <div className="actions">
                  <button
                    onClick={reloadSnapshot}
                    disabled={reloadStatus === "working"}
                  >
                    {reloadStatus === "working" ? "Reloading..." : "Reload now"}
                  </button>
                  <button className="ghost" onClick={fetchSnapshotStatus}>
                    Refresh snapshot
                  </button>
                </div>
                {reloadError && <p className="error">{reloadError}</p>}
              </div>
            </div>

            {indexStatus && (
              <div className="meta-grid">
                <p>Job: {indexStatus.job_name}</p>
                <p>Status: {indexStatus.completion_status || "unknown"}</p>
                <p>Execution: {indexStatus.latest_execution}</p>
                <p>Completed: {indexStatus.completion_time}</p>
              </div>
            )}

            {snapshotStatus && (
              <div className="preview-panel">
                <h3>Snapshot metadata</h3>
                <pre className="preview-json">
                  {JSON.stringify(snapshotStatus, null, 2)}
                </pre>
                {snapshotError && <p className="error">{snapshotError}</p>}
              </div>
            )}
          </section>

          <section className="panel step-panel">
            <div className="panel-header">
              <h2>Step 5 — Query</h2>
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
                  {imagePreview && <img src={imagePreview} alt="Preview" />}
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
      )}

      <section className="panel">
        <div className="panel-header">
          <h2>Asset Preview</h2>
          <span className="counter">{assetPreviewUrl ? "1" : "0"} loaded</span>
        </div>
        <div className="actions">
          <button
            onClick={() => previewObject(uploadedUri || manualUri)}
            disabled={!uploadedUri && !manualUri}
          >
            Preview uploaded asset
          </button>
        </div>
        {assetPreviewUrl && assetPreviewType?.startsWith("image/") && (
          <img className="asset-preview" src={assetPreviewUrl} alt="Asset" />
        )}
        {assetPreviewUrl && assetPreviewType?.startsWith("audio/") && (
          <audio controls src={assetPreviewUrl} />
        )}
        {assetPreviewUrl && assetPreviewType?.startsWith("video/") && (
          <video controls src={assetPreviewUrl} />
        )}
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
                {item.thumbnail_uri && thumbUrls[item.thumbnail_uri] && (
                  <img
                    className="result-thumb"
                    src={thumbUrls[item.thumbnail_uri]}
                    alt="Keyframe thumbnail"
                  />
                )}
                {item.snippet && <p className="snippet">{item.snippet}</p>}
                {item.timestamp_ms !== null && item.timestamp_ms !== undefined && (
                  <p className="timestamp">@ {item.timestamp_ms} ms</p>
                )}
                {item.media_type === "video" &&
                  item.timestamp_ms !== null &&
                  item.timestamp_ms !== undefined && (
                    <div className="video-preview">
                      <button
                        className="ghost"
                        onClick={() => loadVideoPreview(item.uri)}
                        disabled={videoLoading[item.uri]}
                      >
                        {videoLoading[item.uri]
                          ? "Loading clip..."
                          : videoUrls[item.uri]
                            ? "Reload clip"
                            : "Load clip"}
                      </button>
                      {videoUrls[item.uri] && (
                        <video
                          controls
                          src={videoUrls[item.uri]}
                          onLoadedMetadata={(event) => {
                            const start = Math.max(
                              0,
                              item.timestamp_ms / 1000 -
                                SEGMENT_PREVIEW_SECONDS / 2,
                            );
                            event.currentTarget.currentTime = start;
                          }}
                          onTimeUpdate={(event) => {
                            const start = Math.max(
                              0,
                              item.timestamp_ms / 1000 -
                                SEGMENT_PREVIEW_SECONDS / 2,
                            );
                            const end = start + SEGMENT_PREVIEW_SECONDS;
                            if (event.currentTarget.currentTime > end) {
                              event.currentTarget.pause();
                            }
                          }}
                        />
                      )}
                    </div>
                  )}
                {objectUrl && (
                  <button
                    className="ghost"
                    onClick={() => previewObject(item.uri)}
                  >
                    Preview asset
                  </button>
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
          <h4>Dev API</h4>
          <p>{devApiUrl || "Not configured"}</p>
        </div>
        <div>
          <h4>Pipeline notes</h4>
          <p>Upload → ingest → manifest → index → reload snapshot → query.</p>
        </div>
      </footer>
    </div>
  );
}
