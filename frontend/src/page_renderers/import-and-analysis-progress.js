/* Show what happened to an uploaded PDF and how its analysis is progressing.

The browser displays parsing results, stage status, measured usage and estimated
work so readers can distinguish running, paused and failed work. Drawing these
views does not itself start or continue model requests. */
import { manualSummary } from "./manual-summary.js";
import { renderGuideProgress } from "./guide-investigation-progress.js";
import { createFactTicker } from "./analysis-progress-ticker.js";
import { $, esc, num, sourceLink, metrics } from "../browser-helpers.js";

/**
 * Create the import and analysis progress displays.
 *
 * Args:
 *   context — live document state.
 * Returns:
 *   renderImport, renderAnalysis and updateElapsed; these render saved state without API writes.
 */
export function createViews(context) {
  const factTicker = createFactTicker();
  /**
   * Render the import page.
   *
   * Args:
   *   none.
   * Returns:
   *   nothing; explains actual import state and shows discovered document structure.
   */
  function renderImport() {
    const { current, jobId } = context;
    const s = current?.state,
      d = current?.document;
    $("file").disabled = !!s || context.uploading;
    $("choose-pdf").classList.toggle("disabled", $("file").disabled);
    $("choose-pdf").setAttribute("aria-disabled", String($("file").disabled));
    $("choose-pdf-text").textContent = d
      ? "Completed"
      : s
        ? "PDF selected"
        : context.uploading
          ? "Uploading…"
          : "Choose PDF";
    $("import-bar").hidden = !s;
    $("import-bar").removeAttribute("value");
    if (d) {
      $("import-bar").max = 1;
      $("import-bar").value = 1;
    }
    if (s && !d && !["queued", "parsing"].includes(s.status))
      $("import-bar").hidden = true;
    $("import-elapsed").textContent = "";
    $("continue-analysis").textContent = "View fact extraction →";
    $("import-progress").hidden = !s;
    $("import-actions").hidden = !d;
    $("import-stats").innerHTML = "";
    $("import-summary").innerHTML = "";
    if (!s) return;
    let title, message;
    if (d) {
      title = "PDF import completed";
      message = `Read ${num(s.pages)} pages and detected ${num(s.tables)} tables and ${num(s.figures)} graphics. You can inspect the sources and outline or view analysis progress.`;
      $("import-stats").innerHTML = metrics([
        ["Pages", s.pages],
        ["Tables", s.tables],
        ["Graphics detected", s.figures],
        ["Outline headings", d.outline.length],
      ]);
      $("import-summary").innerHTML = /* HTML */ `<div class="card">
        <h3>Document contents</h3>
        ${current.workflow?.inspection_preview
          ? `<p>Estimated allowance for a new inspection: <strong>${num(current.workflow.inspection_preview.action_allowance)} actions</strong>. Estimated from pages, tables, figure pages, text density and sparse visual pages. The agent may finish earlier; finish does not consume an inspection action. The separate two-image-call limit still applies.</p>`
          : ""}
        <p>${num(d.items.length)} text, table and graphic items extracted.</p>
        <p class="fine">
          Graphic counts are parser detections; vector drawings may not be
          counted as separate graphics.
        </p>
        ${current.workflow?.preflight?.blocker
          ? /* HTML */ `<p class="inline-error">
              <strong>Analysis size limit:</strong> ${esc(
                current.workflow.preflight.blocker,
              )}
            </p>`
          : ""}
      </div>`;
    } else if (s.status === "parsing") {
      title = "Reading the PDF";
      message =
        "Extracting text and identifying sections, tables and graphics. Scanned text is being read with OCR. Document counts will appear when this finishes.";
    } else if (s.status === "queued") {
      title = "PDF uploaded";
      message =
        "Waiting for PDF processing to start. Other documents are processed one at a time.";
    } else {
      title = "PDF import stopped";
      message =
        s.message ||
        "The PDF could not be read. Check Activity for the failure details.";
    }
    $("import-title").textContent = title;
    $("import-message").textContent = message;
    updateElapsed();
  }

  /**
   * Render only the selected processing panel's progress and outputs.
   *
   * Args:
   *   panel — extraction, aids or analysis; selects facts, non-agentic aids or guide work.
   * Returns:
   *   nothing; displays saved state and document-wide measured usage, never starts work.
   *   Hides activity from other panels rather than presenting it as this panel's progress.
   *   Shows the extraction bar only while extraction is running, paused or blocked;
   *   later stages retain its completed count in the stage list instead.
   */
  function renderAnalysis(panel = "analysis") {
    const { current, jobId } = context;
    if (!current) return;
    const s = current.state;
    const original = current.workflow;
    if (!original) {
      $("stage").textContent = "Loading analysis status";
      return;
    }
    const ids =
      panel === "extraction"
        ? ["extract"]
        : panel === "aids"
          ? ["faq", "troubleshooting"]
          : ["procedures", "publish", "index", "validate"];
    const phases = original.phases.filter((p) => ids.includes(p.id));
    const active = original.phases.find((p) =>
      ["running", "blocked", "paused"].includes(p.status),
    );
    const ownsActivity = !!active && ids.includes(active.id);
    const complete =
      phases.length > 0 && phases.every((p) => p.status === "complete");
    const titles = {
      extraction: "Fact extraction",
      aids: "FAQ and troubleshooting steps",
      analysis: "Agentic guides",
    };
    const description = {
      extraction: "Extract source-linked facts from the parsed PDF.",
      aids: "Generate FAQ answers and independent troubleshooting steps from source passages. This stage does not run guide investigations.",
      analysis:
        "Investigate installation, troubleshooting and maintenance tasks in parallel, retrieve related passages and review the resulting guides.",
    };
    const idleMessage = complete
      ? "This stage has finished. Its saved outputs remain available."
      : "This stage will run when the preceding work finishes.";
    const w = {
      ...original,
      phases,
      current: ownsActivity
        ? original.current
        : {
            title: `${titles[panel]}${complete ? " complete" : ""}`,
            message: idleMessage,
          },
      pending_call: ownsActivity ? original.pending_call : null,
      task_progress: ownsActivity ? original.task_progress : null,
      blocker: ownsActivity ? original.blocker : null,
      activity_focus:
        panel === "extraction"
          ? {
              kind: "facts",
              title: "Recently extracted facts",
              scope: "extraction-panel",
            }
          : ownsActivity
            ? original.activity_focus
            : {
                kind: "status",
                title: titles[panel],
                scope: panel,
                items: [{ name: titles[panel], value: idleMessage }],
              },
    };
    $("panel-description").textContent = description[panel];
    const nextPanel =
      panel === "extraction"
        ? "aids"
        : panel === "aids"
          ? "analysis"
          : "overview";
    $("next-workflow-panel").dataset.tab = nextPanel;
    $("next-workflow-panel").textContent =
      panel === "extraction"
        ? "View FAQ and troubleshooting steps →"
        : panel === "aids"
          ? "View agentic guides →"
          : "View results →";
    $("next-workflow-panel").hidden = panel === "analysis";
    $("panel-outputs").hidden =
      panel === "extraction" || (panel === "analysis" && !!w.guide_progress);
    $("guide-investigation-progress").hidden = panel !== "analysis";
    if (panel === "analysis")
      renderGuideProgress($("guide-investigation-progress"), current);
    $("panel-outputs").innerHTML =
      panel === "aids"
        ? `${manualSummary(current.profile || {}, current.document)}<h3>Generated outputs</h3><p>${num(current.profile?.faq?.length || 0)} FAQ answers · ${num(current.profile?.troubleshooting_checks?.length || 0)} documented troubleshooting steps saved.</p>${current.profile ? '<div class="page-actions"><button data-tab="faq">View FAQ</button><button data-tab="troubleshooting">View troubleshooting steps</button></div>' : ""}`
        : panel === "analysis"
          ? `<h3>Guide investigations</h3><p>Separate tasks run in parallel, with up to six investigations at once. Saved drafts may still need review.</p>${[
              ["installation", "Installation"],
              ["troubleshooting", "Troubleshooting"],
              ["maintenance", "Maintenance"],
            ]
              .map(([kind, label]) => {
                const guides = (current.profile?.procedure_guides || []).filter(
                  (g) => g.kind === kind,
                );
                const available = guides.filter(
                  (g) => g.status !== "unfinished",
                );
                return `<p><strong>${label}:</strong> ${available.length} saved guide${available.length === 1 ? "" : "s"}${guides.some((g) => g.status === "unfinished") ? ` · ${guides.filter((g) => g.status === "unfinished").length} unfinished` : ""}${current.profile ? ` <button data-tab="${kind}">View ${label.toLowerCase()}</button>` : ""}</p>`;
              })
              .join("")}`
          : "";
    $("stage").textContent = w.current.title;
    $("message").textContent = w.current.message;
    if (
      ownsActivity &&
      s.status === "analyzing" &&
      s.active_model_calls?.length
    ) {
      const count = s.active_model_calls.length;
      $("message").textContent +=
        ` ${count} model request${count === 1 ? "" : "s"} in flight.`;
    }
    if (
      ["allowance_reached", "unfinished"].includes(
        w.inspection_result?.inspection_status,
      )
    ) {
      $("message").textContent +=
        " Preliminary inspection remains unfinished: " +
        (w.inspection_result.remaining_questions || []).join("; ");
    }
    $("analysis-status").classList.toggle("blocked", !!w.blocker);
    $("analyze").hidden = panel !== "extraction" || !w.can_analyze;
    $("resume").hidden = !ownsActivity || !w.can_resume;
    $("show-results").hidden = !current.profile;
    $("token-metrics").innerHTML = metrics([
      ["Input tokens used", s.input_tokens],
      ["Output tokens used", s.output_tokens],
      ["Total model calls", s.calls],
      [
        panel === "extraction"
          ? "Facts extracted"
          : panel === "aids"
            ? "Saved FAQ answers"
            : "Saved guides",
        panel === "extraction"
          ? w.progress.accepted_facts
          : panel === "aids"
            ? (current.profile?.faq || []).length
            : (current.profile?.procedure_guides || []).length,
      ],
    ]);
    $("usage-note").textContent =
      (s.unknown_usage_calls
        ? `${s.unknown_usage_calls} request(s) have unknown usage; totals are incomplete. `
        : "") +
      "Token and call totals cover the whole document, including all stages and questions—not just this panel. Counts update when a model request finishes.";
    $("usage-note").textContent +=
      ` Each Run or Resume authorizes up to ${w.allowance.calls} new calls and ${num(w.allowance.input_tokens)} input tokens. Completed calls use reported input usage; pending calls and unknown usage use estimates.`;
    if (w.input_allowance) {
      const a = w.input_allowance;
      $("usage-note").textContent +=
        ` Current Run/Resume: ${num(a.reported)} reported input + ${num(a.reserved)} reserved for pending calls + ${num(a.unknown_estimate)} estimated for unknown usage, against ${num(a.limit)} input tokens.`;
    }
    const e = w.estimate,
      range = (v) => (v ? `${num(v[0])}–${num(v[1])}` : "Not yet estimable");
    // This estimate covers extraction only. Once extraction is done, retaining a
    // zero-valued panel would misrepresent the work still happening in later stages.
    $("estimate").hidden =
      panel !== "extraction" ||
      e.remaining_batches === 0 ||
      w.phases.some(
        (phase) => phase.id === "extract" && phase.status === "complete",
      );
    $("estimate").innerHTML = /* HTML */ `<h3>
        Estimated remaining extraction tokens
      </h3>
      ${w.blocker
        ? /* HTML */ `<p>${esc(e.note)}</p>`
        : /* HTML */ `<div class="estimate-values">
              <p><strong>${range(e.input_range)}</strong> input</p>
              <p><strong>${range(e.output_range)}</strong> output</p>
            </div>
            <p>
              ${num(e.remaining_batches)} extraction batches remain. Uncertainty
              review, FAQ generation and troubleshooting generation are not
              included.
            </p>
            <details>
              <summary>How this estimate is calculated</summary>
              <p class="fine">${esc(e.note)}</p>
            </details>`}`;
    $("analysis-plan").innerHTML = w.phases
      .map(
        (p) =>
          /* HTML */ `<li class="phase ${p.status}">
            <div>
              <strong>${esc(p.title)}</strong
              ><span class="tag"
                >${esc(
                  {
                    complete: "Complete",
                    running: "In progress",
                    blocked: "Blocked",
                    paused: "Paused",
                    pending: "Not started",
                  }[p.status],
                )}</span
              >
            </div>
            <p>${esc(p.description)}</p>
            ${p.id === "extract" && w.progress.total_batches
              ? /* HTML */ `<small
                  >${num(w.progress.completed_batches)} of
                  ${num(w.progress.total_batches)} batches completed</small
                >`
              : ""}
          </li>`,
      )
      .join("");
    const activePhase = w.phases.find((phase) =>
      ["running", "blocked", "paused"].includes(phase.status),
    );
    // The fallback keeps older running servers from displaying stale facts when the
    // current phase has already changed; the new backend supplies actual checks.
    const focus =
      w.activity_focus ||
      (activePhase?.id === "extract"
        ? { kind: "facts", title: "Recently extracted facts", scope: "facts" }
        : {
            kind: "status",
            title: w.current.title,
            scope: w.current.title,
            items: [
              {
                name: w.current.title,
                value: w.current.message,
                pages: w.task_progress?.pages || [],
              },
            ],
          });
    factTicker.update(
      focus.kind === "facts" ? w.recent_facts || [] : focus.items || [],
      context.jobId,
      focus,
    );
    const last = w.latest_decision;
    const inspecting =
      s.status === "analyzing" && activePhase?.id === "inspect";
    $("inspection-heading").textContent = "Current activity";
    $("current-inspection").innerHTML =
      inspecting && last
        ? /* HTML */ `<h3>${esc(last.title)}</h3>
            <p>${esc(last.target)} ${last.page ? sourceLink(last.page) : ""}</p>
            <h4>Agent’s stated reason</h4>
            <p>${esc(last.reason)}</p>`
        : /* HTML */ `<h3>${esc(w.current.title)}</h3>
            <p>${esc(w.current.message)}</p>`;
    if (w.pending_call) {
      $("current-inspection").innerHTML += /* HTML */ `<p class="running-note">
          Waiting for the ${w.pending_call.role === "vision" ? "image" : "text"}
          model’s response.
        </p>
        <p id="request-elapsed" class="fine"></p>`;
    }
    updateElapsed();
    const task = w.task_progress;
    if (task?.pages?.length && w.pending_call) {
      $("current-inspection").innerHTML += /* HTML */ `<p>
        Current sources:
        ${task.pages.map((page) => sourceLink(page)).join(" · ")}
      </p>`;
    }
    if (task && task.task !== "facts") {
      $("current-inspection").innerHTML += /* HTML */ `<h4>
          ${task.task === "procedures"
            ? "Latest investigation update"
            : "Current task progress"}
        </h4>
        <progress
          max="${task.total || 1}"
          value="${task.completed}"
          aria-label="Current task source groups completed"
        ></progress>
        <p>
          ${num(task.completed)} / ${num(task.total)}
          ${task.task === "procedures"
            ? "planning decisions"
            : "source groups completed"}.
          ${task.output_allowance
            ? `Output allowance: ${num(task.output_allowance)} tokens per request.`
            : ""}
        </p>`;
    }
    const p = w.progress;
    // Completed extraction stays in the stage history, not beside ongoing guides.
    const showExtractionProgress =
      panel === "extraction" && p.total_batches > 0;
    $("batch-progress").hidden = !showExtractionProgress;
    $("batch-progress").innerHTML = showExtractionProgress
      ? /* HTML */ `<h3>Extraction progress</h3>
          <progress
            max="${p.total_batches}"
            value="${p.completed_batches}"
            aria-label="Extraction batches completed"
          ></progress>
          <p>
            ${p.completed_batches} / ${p.total_batches} batches ·
            ${p.accepted_facts} source-matched facts · ${p.rejected_facts}
            rejected proposals
          </p>`
      : "";
    $("decision-history").closest("section").hidden =
      panel !== "analysis" || !w.decisions.length;
    $("current-inspection").closest("section").hidden =
      panel === "extraction" ? false : !ownsActivity;
    $("current-inspection").hidden = panel === "extraction" && !ownsActivity;
    $("inspection-heading").hidden = panel === "extraction" && !ownsActivity;
    $("decision-history").innerHTML = w.decisions.length
      ? w.decisions
          .slice()
          .reverse()
          .map(
            (d) =>
              /* HTML */ `<details class="decision">
                <summary>
                  ${esc(d.title)}${d.target ? " — " + esc(d.target) : ""}
                </summary>
                <p>${esc(d.reason)}</p>
                ${d.page ? sourceLink(d.page) : ""}<small
                  >${esc(new Date(d.time).toLocaleTimeString())}</small
                >
              </details>`,
          )
          .join("")
      : "<p>Inspection decisions will appear here when analysis starts.</p>";
  }

  /**
   * Update elapsed-time labels without repainting user inputs or claiming percent progress.
   * Args:
   *   none.
   * Returns:
   *   nothing; uses saved upload/request timestamps and the browser clock only.
   */
  function updateElapsed() {
    factTicker.tick();
    const state = context.current?.state;
    if (!state) return;
    const elapsed = (timestamp) =>
      Math.max(0, Math.floor((Date.now() - Date.parse(timestamp)) / 1000));
    if (
      ["queued", "parsing"].includes(state.status) &&
      !context.current.document
    ) {
      $("import-elapsed").textContent =
        `${elapsed(state.created)} seconds since upload. ${state.status === "queued" ? "Waiting for the local parser." : "Local text, layout and OCR processing is running."} Page-level completion is not reported by the parser.`;
    }
    const request = context.current.workflow?.pending_call;
    if (request && $("request-elapsed")) {
      $("request-elapsed").textContent =
        `${elapsed(request.time)} seconds since this request started. Usage and results appear when its response arrives.`;
    }
  }

  return { renderImport, renderAnalysis, updateElapsed };
}
