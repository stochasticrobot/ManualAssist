/* Display selected original PDF pictures with their source captions and links.

Only pictures already approved for reference use are shown. Their placement helps
readers recognize relevant parts; it does not claim that a picture demonstrates
the generated instruction or create a replacement illustration. */
import { esc } from "../browser-helpers.js";
let current = { jobId: "", images: [] };

/** Set the current document's accepted image catalogue without triggering work.
 * Args:
 *   jobId — current job; manifest — read-only accepted source image metadata.
 * Returns:
 *   Nothing; replaces the local catalogue to prevent cross-document image leakage.
 */
export function setIllustrations(jobId, manifest) {
  current = { jobId, images: manifest?.images || [] };
}

/** Render a bounded source-linked reference image, never a generated action caption.
 * Args:
 *   image — backend-approved figure with original heading and page.
 * Returns:
 *   Escaped figure HTML with lazy loading and a link to the original manual page.
 */
function figure(image) {
  const base = `/api/jobs/${encodeURIComponent(current.jobId)}`;
  return `<figure class="reference-illustration"><a href="${base}/source#page=${Number(image.page)}" target="_blank" rel="noopener"><img loading="lazy" src="${base}/illustrations/${encodeURIComponent(image.id)}.png" alt="${esc(image.heading)} — original manual illustration"></a><figcaption>Reference illustration · ${esc(image.heading)} · <a href="${base}/source#page=${Number(image.page)}" target="_blank" rel="noopener">Page ${Number(image.page)}</a></figcaption></figure>`;
}

/** Match images to exact source records, not page proximity or generated text.
 * Args:
 *   records — citations attached to the currently displayed step, check or fact.
 * Returns:
 *   Up to two contextual source illustrations; no match produces no empty panel.
 */
export function referenceIllustrations(records = []) {
  const ids = new Set(records.map((r) => r.evidence_id));
  const matches = current.images.filter((image) =>
    image.source_ids.some((id) => ids.has(id)),
  );
  return matches.length
    ? `<div class="reference-illustrations">${matches.slice(0, 2).map(figure).join("")}</div>`
    : "";
}

/** Show source-labelled overview images independently of individual instruction claims.
 * Args:
 *   None.
 * Returns:
 *   Up to four broad front/interior/product views; no accepted views yields nothing.
 */
export function productIllustrations() {
  const images = current.images.filter(
    (i) => /view$/i.test(i.heading) || /overview$/i.test(i.heading),
  );
  return images.length
    ? `<div class="reference-illustrations">${images.slice(0, 4).map(figure).join("")}</div>`
    : "";
}
