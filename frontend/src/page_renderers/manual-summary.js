/* Build the shared product heading and a short description from saved manual
information.

The Results pages need consistent identity and context without another AI request.
This file selects existing text and facts; it does not invent a product name or
new specifications. */
import { esc, sourceLink } from "../browser-helpers.js";

/** Render cover wording, product/model identity and selected high-level details.
 * Args:
 *   profile — saved source-linked facts; no unsupported identity values are invented.
 *   document — optional parsed PDF supplying literal cover headings and source links.
 *   productOnly — show product identity without the general manual-topic overview.
 * Returns:
 *   escaped summary HTML, or an honest short empty state. Cover wording is labelled
 *   separately from extracted identity facts; component model numbers retain their
 *   original field names and applicability. Selection is a preview, not full coverage.
 */
export function manualSummary(profile, document = null, productOnly = false) {
  const facts = profile.facts || [];
  const cover = (document?.items || [])
    .filter(
      (item) =>
        item.page === 1 &&
        ["title", "section_header"].includes(item.label) &&
        item.text.length <= 200,
    )
    .slice(0, 3);
  const identity = facts.filter(
    (f) =>
      /^(product|model|identity|document|document_type|purpose)$/i.test(
        f.category,
      ) ||
      /^(manufacturer|brand|product|document|manual) (name|title|type|purpose)$/i.test(
        f.name,
      ),
  );
  const seen = new Set();
  const selected = identity
    .filter((f) => {
      const key =
        (/model/i.test(f.name) ? "model" : f.name.toLowerCase()) +
        ":" +
        f.value;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 8);
  const details = facts
    .filter(
      (f) =>
        /^(specification|feature|capability|purpose)$/i.test(f.category) &&
        !selected.includes(f),
    )
    .slice(0, 4);
  const coverage = [
    ...new Set(
      facts
        .map((f) => {
          const category = String(f.category).toLowerCase();
          if (/installation|assembly|quick_start/.test(category))
            return "setup";
          if (/operation|cycle/.test(category)) return "operation";
          if (/maintenance|cleaning/.test(category)) return "maintenance";
          if (/troubleshoot|error_code/.test(category))
            return "troubleshooting";
          if (/safety|warning/.test(category)) return "safety";
          if (/specification|power/.test(category)) return "specifications";
          return null;
        })
        .filter(Boolean),
    ),
  ];
  return `<section class="card manual-summary"><h2>${productOnly ? "Product information" : "Manual summary"}</h2>
    ${cover.length ? `<p><strong>On the cover:</strong> ${cover.map((item) => `${esc(item.text)} ${sourceLink(item.page, item.id)}`).join(" · ")}</p>` : ""}
    ${selected.length ? `<dl>${selected.map((f) => `<dt><strong>${esc(f.name)}</strong></dt><dd>${esc(f.value)}${f.applies_to ? ` <small>(${esc(f.applies_to)})</small>` : ""} ${sourceLink(f.page, f.evidence_id)}</dd>`).join("")}</dl>` : "<p>Product and model details have not been established from the extracted facts.</p>"}
    ${!productOnly && coverage.length ? `<p><strong>Topics found in the manual:</strong> ${esc(coverage.join(", "))}.</p>` : ""}
    ${!productOnly && details.length ? `<details><summary>High-level details</summary><ul>${details.map((f) => `<li><strong>${esc(f.name)}:</strong> ${esc(f.value)} ${sourceLink(f.page, f.evidence_id)}</li>`).join("")}</ul></details>` : ""}
  </section>`;
}

/** Render one compact product identity shared by every Results page.
 * Args:
 *   profile — saved facts; the first named product is used without inventing identity.
 *   document — parsed manual supplying a cover title only when no product name exists.
 * Returns:
 *   escaped, link-free product title with supporting detail collapsed by default.
 *   If neither source establishes a title, uses the neutral label Manual guide.
 */
export function resultsProductHeader(profile, document = null) {
  const product = (profile.facts || []).find(
    (f) =>
      /^(product name|product title)$/i.test(f.name) &&
      f.value?.trim() &&
      !/^(unknown|not specified)$/i.test(f.value.trim()),
  );
  const cover = (document?.items || []).find(
    (item) =>
      item.page === 1 &&
      item.label === "title" &&
      item.text?.length <= 160 &&
      !/^(owner.?s? manual|user manual|instruction manual)$/i.test(
        item.text.trim(),
      ),
  );
  const title = product?.value || cover?.text || "Manual guide";
  return `<div class="product-heading"><span class="product-mark" aria-hidden="true">▤</span><h2>${esc(title)}</h2></div><details class="product-details"><summary>Product details</summary>${manualSummary(profile, document)}</details>`;
}
