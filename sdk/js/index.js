const DEFAULT_INGEST_URL = "http://localhost:8081";
const DEFAULT_QUERY_URL = "http://localhost:8080";
const DEFAULT_TIMEOUT_MS = 30000;

const ENV = typeof process !== "undefined" && process.env ? process.env : {};

function parseEnvInt(value) {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function resolveTimeoutMs(explicit) {
  if (explicit !== undefined && explicit !== null) return explicit;
  const ms = parseEnvInt(ENV.RETIKON_TIMEOUT_MS);
  if (ms !== null) return ms;
  const seconds = parseEnvInt(ENV.RETIKON_TIMEOUT_S);
  if (seconds !== null) return seconds * 1000;
  return DEFAULT_TIMEOUT_MS;
}

function resolveAuthToken(explicit) {
  if (explicit !== undefined && explicit !== null) return explicit;
  return ENV.RETIKON_AUTH_TOKEN || ENV.RETIKON_JWT || null;
}

export class RetikonClient {
  constructor(options = {}) {
  const ingestUrl =
    options.ingestUrl ?? ENV.RETIKON_INGEST_URL ?? DEFAULT_INGEST_URL;
  const queryUrl =
    options.queryUrl ?? ENV.RETIKON_QUERY_URL ?? DEFAULT_QUERY_URL;
    this.ingestUrl = ingestUrl;
    this.queryUrl = queryUrl;
    this.authToken = resolveAuthToken(options.authToken);
    this.timeoutMs = resolveTimeoutMs(options.timeoutMs);
  }

  _headers() {
    const headers = { "Content-Type": "application/json" };
    if (this.authToken) {
      headers.Authorization = `Bearer ${this.authToken}`;
    }
    return headers;
  }

  async _request(method, url, payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const resp = await fetch(url, {
        method,
        headers: this._headers(),
        body: payload ? JSON.stringify(payload) : undefined,
        signal: controller.signal,
      });
      const text = await resp.text();
      if (!resp.ok) {
        throw new Error(text || resp.statusText);
      }
      return text ? JSON.parse(text) : {};
    } finally {
      clearTimeout(timeout);
    }
  }

  ingest({ path, contentType }) {
    const payload = { path };
    if (contentType) payload.content_type = contentType;
    return this._request("POST", `${this.ingestUrl.replace(/\\/$/, "")}/ingest`, payload);
  }

  query({ queryText, imageBase64, topK = 5, mode, modalities, searchType, metadataFilters } = {}) {
    const payload = { top_k: topK };
    if (queryText) payload.query_text = queryText;
    if (imageBase64) payload.image_base64 = imageBase64;
    if (mode) payload.mode = mode;
    if (modalities) payload.modalities = modalities;
    if (searchType) payload.search_type = searchType;
    if (metadataFilters) payload.metadata_filters = metadataFilters;
    return this._request("POST", `${this.queryUrl.replace(/\\/$/, "")}/query`, payload);
  }

  health() {
    return this._request("GET", `${this.queryUrl.replace(/\\/$/, "")}/health`);
  }

  reloadSnapshot() {
    return this._request("POST", `${this.queryUrl.replace(/\\/$/, "")}/admin/reload-snapshot`);
  }
}
