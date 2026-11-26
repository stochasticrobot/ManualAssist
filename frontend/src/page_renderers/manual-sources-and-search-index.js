/* Let readers inspect the original text and the saved passages available for search.

These views make it possible to check where generated results came from and what
text was actually extracted. They display existing records and links rather than
creating new facts or asking an AI for answers. */
import { $, esc, sourceLink } from "../browser-helpers.js";

/**
 * Create resource renderers.
 *
 * Args:
 *   context — live document state and source-view callbacks.
 * Returns:
 *   renderers that read saved data and never initiate model calls.
 */
export function createViews(context) {
  /**
   * Render headings and extracted source items.
   *
   * Args:
   *   none.
   * Returns:
   *   nothing; updates source DOM while preserving the selected physical page.
   */
  function renderSources() {
    const document = context.current.document;
    $("outline").innerHTML = document.outline.length
      ? document.outline
          .map(
            (heading) =>
              /* HTML */ `<button
                class="outline-link"
                data-page="${heading.page}"
                style="padding-left:${Math.min(heading.level, 6) * 10}px"
              >
                ${esc(heading.title)} · p. ${heading.page}
              </button>`,
          )
          .join("")
      : "<p>No headings were recovered.</p>";
    context.evidence();
    context.showPage(context.currentPage);
  }

  /**
   * Render saved searchable chunks.
   *
   * Args:
   *   none.
   * Returns:
   *   nothing; displays actual persisted text and a manifest download link.
   */
  function renderKnowledge() {
    const { current, jobId } = context;
    $("knowledge").innerHTML =
      /* HTML */ `<p>${current.chunks.length} searchable chunks saved.</p><a href="/api/jobs/${jobId}/assets/chunks.json">Download chunks</a>` +
      current.chunks
        .map(
          (chunk) =>
            /* HTML */ `<article class="card">
              ${sourceLink(chunk.page, chunk.evidence_id)}
              <p>${esc(chunk.text)}</p>
            </article>`,
        )
        .join("");
  }
  return { renderSources, renderKnowledge };
}
