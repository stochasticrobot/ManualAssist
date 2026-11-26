/* Load the full saved instructions and source passages for one selected AI request.

Long request text is fetched only when opened, keeping routine progress updates
small. Opening or reopening the details reads saved records and never sends the
request to the AI again. */
import { api, esc, num } from "../browser-helpers.js";

/**
 * Keep expanded model requests readable while the Activity feed refreshes.
 * Args:
 *   none.
 * Returns:
 *   HTML and attachment helpers using a job/call-scoped request cache. Requests are
 *   read only on expansion; errors remain visible and can be retried by reopening.
 */
export function createModelRequestDetails() {
  const requests = new Map();

  /**
   * Render a saved request without interpreting or shortening its instructions.
   * Args:
   *   request — saved application request returned by the read-only API.
   * Returns:
   *   escaped HTML with full prompt/source text, system instructions and schema.
   *   Image metadata is shown without pretending hashes are the image contents.
   */
  function content(request) {
    const identity = request.identity || {};
    return `<p><strong>Model:</strong> ${esc(identity.provider || "Not recorded")} / ${esc(identity.model || "Not recorded")}
      · ${esc(request.role)} · maximum ${num(request.max_tokens)} output tokens</p>
      <h4>Prompt and supplied source text</h4><pre class="model-prompt">${esc(request.prompt || "No prompt recorded.")}</pre>
      <h4>System instructions</h4><pre class="model-prompt">${esc(request.system || "No system instructions recorded.")}</pre>
      <details><summary>Expected response fields (JSON schema)</summary><pre class="model-prompt">${esc(JSON.stringify(request.schema, null, 2))}</pre></details>
      ${request.image_sizes?.length ? `<h4>Supplied images</h4><p>${request.image_sizes.length} image(s). Sizes and hashes are recorded below; image bytes are not part of this text receipt.</p><pre class="model-prompt">${esc(JSON.stringify({ sizes: request.image_sizes, sha256: request.image_sha256 }, null, 2))}</pre>` : ""}
      <p class="fine">Saved application request. The provider adapter combines these instructions, schema and any images into its API request.</p>`;
  }

  /**
   * Add a collapsed request inspector to a call or replay event.
   * Args:
   *   event — audit entry identifying a numbered call or its saved replay source.
   *   key — stable, job-specific event key used to preserve its expanded state.
   * Returns:
   *   details markup, or an empty string when this event has no model request.
   */
  function markup(event, key) {
    const replay = /^call-(\d+)-request$/.exec(event.source_call || "");
    const call = event.call || (replay ? Number(replay[1]) : null);
    if (!call) return "";
    return `<details data-activity-key="${esc(key)}:request" data-model-call="${Number(call)}">
      <summary>View prompt and source text · call ${Number(call)}</summary>
      <div class="model-request-content"></div></details>`;
  }

  /**
   * Load the expanded call once, sharing in-flight reads across feed refreshes.
   * Args:
   *   root — newly rendered Activity container.
   *   jobId — document owning all request links in this render.
   * Returns:
   *   nothing; installs toggle handlers and fills already-open request panels.
   *   Detached old panels cannot overwrite a different job or a newer render.
   */
  function attach(root, jobId) {
    for (const details of root.querySelectorAll("[data-model-call]")) {
      if (details.dataset.requestBound) continue;
      details.dataset.requestBound = "true";
      const load = async () => {
        if (!details.open) return;
        const call = Number(details.dataset.modelCall);
        const key = `${jobId}:${call}`;
        const target = details.querySelector(".model-request-content");
        if (target.dataset.loaded) return;
        target.textContent = "Loading saved request…";
        if (!requests.has(key)) {
          requests.set(
            key,
            api(`/api/jobs/${jobId}/calls/${call}/request`).catch((error) => {
              requests.delete(key);
              throw error;
            }),
          );
        }
        try {
          const request = await requests.get(key);
          if (!details.isConnected) return;
          target.innerHTML = content(request);
          target.dataset.loaded = "true";
        } catch (error) {
          if (details.isConnected)
            target.textContent = `Could not load this request: ${error.message}. Close and reopen to retry.`;
        }
      };
      details.addEventListener("toggle", load);
      if (details.open) load();
    }
  }
  return { markup, attach };
}
