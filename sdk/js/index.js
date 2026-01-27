export class RetikonClient {
  constructor({ ingestUrl = "http://localhost:8081", queryUrl = "http://localhost:8082", apiKey = null, timeoutMs = 30000 } = {}) {
    this.ingestUrl = ingestUrl;
    this.queryUrl = queryUrl;
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
  }

  _headers() {
    const headers = { "Content-Type": "application/json" };
    if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
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
