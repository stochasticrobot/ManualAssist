/* Display the recorded history of AI requests and document-reading actions.

Readers can inspect what was attempted and expand its saved inputs while new work
continues. Open details are preserved during refreshes. This is a view of recorded
activity, not a live explanation of the model’s private reasoning. */
import { createModelRequestDetails } from "./model-request-details.js";
import { $, esc, num, sourceLink, metrics } from "../browser-helpers.js";

/**
 * Create the Activity renderer for saved model calls and tool events.
 *
 * Args:
 *   context — live document state.
 * Returns:
 *   renderAudit, which reads saved events and request details without API writes.
 */
export function createViews(context) {
  const requestDetails = createModelRequestDetails();
  const expanded = new Set();
  /**
   * Summarize an audit event without requiring JSON inspection.
   *
   * Args:
   *   e — saved event.
   * Returns:
   *   plain descriptive event text.
   */
  function eventLabel(e) {
    const { current, jobId } = context;
    const taskNames = {
      "procedure-discovery": "Procedure discovery",
      facts: "Fact extraction",
      uncertainties: "Uncertainty discovery",
      faq: "FAQ generation",
      troubleshooting: "Troubleshooting generation",
      troubleshooting_checks: "Troubleshooting checks",
    };
    if (e.kind === "task_started")
      return `${taskNames[e.task] || e.task}: ${num(e.source_groups)} source groups; up to ${num(e.output_allowance)} output tokens per request.${e.restoring ? " Checking saved work before continuing." : ""}`;
    if (e.kind === "task_completed")
      return `${taskNames[e.task] || e.task} completed: ${num(e.groups)} source groups.`;
    if (e.kind === "task_split")
      return `${taskNames[e.task] || e.task}: a response reached its output limit. Its source group was divided into smaller requests; the incomplete response was not accepted.`;
    if (e.kind === "procedure_decision")
      return `${e.title}: ${e.reason} (${String(e.action).replaceAll("_", " ")})`;
    if (e.kind === "procedure_source_result")
      return `Procedure source inspection: ${(e.returned_ids || []).length} passages found; ${(e.omitted_ids || []).length} did not fit the planning context. ${e.note || ""}`;
    if (e.kind === "procedure_guides_completed")
      return `Saved ${num(e.guides)} procedure planning results, including any unfinished guides.`;
    if (e.kind === "agent_decision")
      return e.reason || "Selected the next inspection";
    if (e.kind === "workflow_error")
      return (
        e.message ||
        current.workflow?.blocker ||
        `Processing stopped (${e.error}).`
      );
    if (e.kind === "model_start")
      return `Requested a ${e.role} model response (up to ${num(e.max_output_tokens)} output tokens).`;
    if (e.kind === "model_result")
      return `${e.role} response received: ${num(e.input_tokens)} input / ${num(e.output_tokens)} output tokens. Stop reason: ${e.stop_reason}.`;
    if (e.kind === "validation")
      return `Batch ${e.batch} checked: ${e.accepted_total} source-matched facts and ${e.rejected_total} rejected proposals so far.`;
    if (e.kind === "tool_start")
      return `Started ${String(e.tool).replaceAll("_", " ")}${e.page ? " on PDF page " + e.page : ""}.`;
    if (e.kind === "tool_result" && e.tool === "write_vectors")
      return `Saved ${e.written} of ${e.total} searchable chunks.`;
    if (e.kind === "tool_result")
      return `Finished ${String(e.tool).replaceAll("_", " ")}.`;
    if (e.kind === "completed")
      return `Saved ${e.facts} facts and ${e.chunks} searchable chunks.`;
    if (e.kind === "model_replay")
      return "Reused a saved response; no new model call.";
    return String(e.kind).replaceAll("_", " ");
  }

  /**
   * Render recorded actions in reverse chronological order.
   *
   * Args:
   *   none.
   * Returns:
   *   nothing; preserves expanded events and shows optional saved request details.
   *   Request text is fetched on expansion only; no model calls or writes occur.
   */
  function renderAudit() {
    const root = $("audit");
    // Reuse request nodes so open schemas and scroll positions survive
    // new audit events. The surrounding event summaries can still refresh normally.
    const panels = new Map(
      [...root.querySelectorAll("[data-model-call]")].map((node) => [
        node.dataset.activityKey,
        node,
      ]),
    );
    const scrollPositions = [...root.querySelectorAll(".model-prompt")].map(
      (node) => ({ node, top: node.scrollTop, left: node.scrollLeft }),
    );
    const focused = root.contains(document.activeElement)
      ? document.activeElement
      : null;
    for (const details of root.querySelectorAll("[data-activity-key]")) {
      if (details.open) expanded.add(details.dataset.activityKey);
      else expanded.delete(details.dataset.activityKey);
    }
    root.innerHTML = context.current.audit
      .map((event, index) => ({ event, key: `${context.jobId}:${index}` }))
      .slice()
      .reverse()
      .map(
        ({ event, key }) =>
          /* HTML */ `<div class="activity">
            <time>${esc(new Date(event.time).toLocaleTimeString())}</time>
            <p>${esc(eventLabel(event))}</p>
            ${requestDetails.markup(event, key)}
            <details data-activity-key="${esc(key)}:technical">
              <summary>Technical details</summary>
              <pre>${esc(JSON.stringify(event, null, 2))}</pre>
            </details>
          </div>`,
      )
      .join("");
    for (const details of root.querySelectorAll("[data-activity-key]")) {
      details.open = expanded.has(details.dataset.activityKey);
    }
    for (const placeholder of root.querySelectorAll("[data-model-call]")) {
      const previous = panels.get(placeholder.dataset.activityKey);
      if (previous) placeholder.replaceWith(previous);
    }
    for (const position of scrollPositions) {
      if (position.node.isConnected) {
        position.node.scrollTop = position.top;
        position.node.scrollLeft = position.left;
      }
    }
    if (focused?.isConnected) focused.focus({ preventScroll: true });
    requestDetails.attach(root, context.jobId);
  }
  return { renderAudit };
}
