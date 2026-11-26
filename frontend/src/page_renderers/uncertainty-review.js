/* Show unresolved questions and the controls for recording a reader’s review notes.

Readers need to distinguish the application’s findings from their own decisions.
This file builds that display and the editable fields; a separate explicit save
action sends changes to the server. */
import { $, esc, num, sourceLink, metrics } from "../browser-helpers.js";

/**
 * Create the findings-and-review-notes renderer.
 *
 * Args:
 *   context — live document state.
 * Returns:
 *   renderReview, which preserves a focused note while refreshed state arrives; no API writes.
 */
export function createViews(context) {
  /**
   * Render review controls without destroying a note the user is typing.
   *
   * Args:
   *   none.
   * Returns:
   *   nothing; focused review inputs are preserved until submission.
   */
  function renderReview() {
    const { current, jobId } = context;
    if (
      $("review").contains(document.activeElement) &&
      document.activeElement.matches("input,select")
    )
      return;
    const entries = current.state.review;
    $("review").innerHTML = entries.length
      ? entries
          .map(
            (r, i) =>
              /* HTML */ `<article class="card">
                <span class="tag">${esc(r.severity)} · ${esc(r.status)}</span>
                <p><strong>Extraction finding:</strong> ${esc(r.issue)}</p>
                ${r.review_reason
                  ? /* HTML */ `<div class="quote">
                      <strong>Whole-document check:</strong> ${esc(
                        r.review_reason,
                      )}
                    </div>`
                  : ""}
                <p class="fine">${esc(r.evidence_ids.join(", "))}</p>
                <div class="review-controls">
                  <select id="review-status-${i}">
                    ${["open", "resolved", "deferred"]
                      .map(
                        (v) =>
                          /* HTML */ `<option
                            ${r.status === v ? "selected" : ""}
                          >
                            ${v}
                          </option>`,
                      )
                      .join("")}</select
                  ><input
                    id="review-note-${i}"
                    maxlength="1500"
                    placeholder="Review note"
                    value="${esc(r.note)}"
                  /><button data-review="${i}">Save review</button>
                </div>
              </article>`,
          )
          .join("")
      : "<p>No review findings were recorded.</p>";
  }

  return { renderReview };
}
