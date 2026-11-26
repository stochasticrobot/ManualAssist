/* Organize a saved manual into the Results pages readers use to find practical
information.

This file fills the overview and reference views and connects the FAQ, guide and
troubleshooting displays. It preserves reader selections during progress updates
and does not start analysis or fill gaps in the manual. */
import {
  setIllustrations,
  referenceIllustrations,
  productIllustrations,
} from "./source-reference-illustrations.js";
import { resultsProductHeader } from "./manual-summary.js";
import { renderTroubleshootingSystem } from "./troubleshooting-entry-and-chat.js";
import { renderProcedureGuides } from "./procedure-guides-and-schedule.js";
import { renderFAQ } from "./troubleshooting-and-faq.js";
import { $, esc, sourceLink, api, notice } from "../browser-helpers.js";

/**
 * Group source facts into practical reading topics without changing their contents.
 * Args:
 *   category — original model-assigned category.
 * Returns:
 *   reader-facing topic; unknown categories remain available under Other information.
 */
export function factTopic(category) {
  const c = String(category).toLowerCase();
  if (/safety|risk|warning/.test(c)) return "Safety";
  if (/installation|assembly|reassembly|disassembly/.test(c))
    return "Installation";
  if (/maintenance|cleaning|inspection/.test(c)) return "Maintenance";
  if (/troubleshoot|error_code/.test(c)) return "Troubleshooting";
  if (/operation|cycle|quick_start|procedure/.test(c)) return "Operation";
  if (/specification|power|environment/.test(c)) return "Specifications";
  if (/product|model|part/.test(c)) return "Product & parts";
  if (/compliance|warranty/.test(c)) return "Compliance & warranty";
  return "Other information";
}

/**
 * Render one unchanged fact with supporting text collapsed to reduce clutter.
 * Args:
 *   fact — saved fact with original source ID, page and quotation.
 * Returns:
 *   escaped card HTML; never infers missing product information.
 */
function factCard(fact) {
  return `<article class="card reference-fact"><h3>${esc(fact.name)}</h3>
    <p>${esc(fact.value)}</p>${fact.applies_to ? `<small>Applies to: ${esc(fact.applies_to)}</small>` : ""}
    ${referenceIllustrations([fact])}<details><summary>Source · page ${esc(fact.page)}</summary>
    ${sourceLink(fact.page, fact.evidence_id)}<blockquote class="quote">${esc(fact.quote)}</blockquote></details></article>`;
}

/**
 * Create focused result views while retaining search and tree state across polling.
 * Args:
 *   context — selected document and its saved profile.
 * Returns:
 *   renderResults method; reads saved outputs only and sends no model requests.
 */
export function createViews(context) {
  const rendered = new Map();

  /**
   * Render only the requested result section when its saved profile changes.
   * Args:
   *   section — overview, troubleshooting, FAQ, reference or an existing output view.
   * Returns:
   *   nothing; builds local filters and downloads. Existing Q&A/review views stay intact.
   */
  function renderResults(section = "overview") {
    const { current, jobId } = context;
    const p = current?.profile;
    if (!p) return;
    setIllustrations(jobId, current.illustrations);
    const signature = jobId + JSON.stringify([p, current.illustrations]);
    if (rendered.get("product-header") !== signature) {
      $("results-product").innerHTML = resultsProductHeader(
        p,
        current.document,
      );
      rendered.set("product-header", signature);
    }
    const assets = [
      "report.html",
      "quick-start.html",
      "profile.json",
      "tables.json",
      "parts.csv",
      "maintenance.csv",
      "audit.jsonl",
    ];
    if (Object.hasOwn(p, "troubleshooting"))
      assets.push("troubleshooting.json", "faq.json");
    if (Object.hasOwn(p, "procedure_guides"))
      assets.push("procedure_guides.json");
    $("result-downloads").innerHTML = assets
      .map(
        (name) =>
          `<a href="/api/jobs/${jobId}/assets/${name}">${esc(name)} ↓</a>`,
      )
      .join("");
    const illustrationState =
      current.state?.illustration_status || current.illustrations?.status;
    if (
      ["ready", "partial"].includes(current.state?.status) &&
      ["not_prepared", "incomplete", "stale"].includes(illustrationState)
    ) {
      $("result-downloads").insertAdjacentHTML(
        "beforeend",
        '<button id="prepare-reference-illustrations" class="secondary">Prepare reference illustrations</button>',
      );
      $("prepare-reference-illustrations").onclick = async (event) => {
        event.currentTarget.disabled = true;
        try {
          await api(`/api/jobs/${jobId}/illustrations/prepare`, {
            method: "POST",
          });
          notice(
            "Preparing reference illustrations (up to 12 image checks). Text analysis will not restart.",
          );
        } catch (error) {
          notice(error.message);
        }
      };
    }
    if (illustrationState === "preparing")
      $("result-downloads").insertAdjacentHTML(
        "beforeend",
        "<span>Preparing reference illustrations…</span>",
      );
    if (rendered.get(section) === signature) return;
    rendered.set(section, signature);
    if (section === "troubleshooting") {
      renderTroubleshootingSystem($("troubleshooting"), p);
      return;
    }
    if (["installation", "maintenance"].includes(section)) {
      renderProcedureGuides($(section), p, section, current.document);
      return;
    }
    if (section === "faq") {
      renderFAQ($("faq"), p, factTopic, current.document);
      return;
    }
    const facts = p.facts || [];
    if (section === "reference") {
      const topics = [
        ...new Set(facts.map((f) => factTopic(f.category))),
      ].sort();
      $("reference").innerHTML =
        `<h2>Reference</h2><p>Browse the manual’s extracted information by topic. Expand a source to check the original wording.</p>
        <div class="result-filters"><label>Topic<select id="reference-topic"><option value="">All topics</option>
        ${topics.map((t) => `<option>${esc(t)}</option>`).join("")}</select></label>
        <label>Search reference<input id="reference-search" type="search" placeholder="Model, specification, instruction…"></label></div>
        <p id="reference-count" class="fine"></p><div id="reference-items"></div><button id="reference-more" class="secondary">Show more</button>`;
      let limit = 20;
      /**
       * Filter saved reference facts and render a bounded list.
       * Args:
       *   reset — whether a new filter should return to the first twenty matches.
       * Returns:
       *   nothing; displays exact matching/visible counts and preserves every saved fact.
       */
      function filter(reset = true) {
        if (reset) limit = 20;
        const topic = $("reference-topic").value;
        const query = $("reference-search").value.toLowerCase();
        const matches = facts.filter(
          (f) =>
            (!topic || factTopic(f.category) === topic) &&
            [f.name, f.value, f.category, f.applies_to]
              .join(" ")
              .toLowerCase()
              .includes(query),
        );
        $("reference-items").innerHTML =
          matches.slice(0, limit).map(factCard).join("") ||
          "<p>No matching information.</p>";
        $("reference-count").textContent =
          `Showing ${Math.min(limit, matches.length)} of ${matches.length} matching entries`;
        $("reference-more").hidden = limit >= matches.length;
      }
      $("reference-topic").onchange = () => filter();
      $("reference-search").oninput = () => filter();
      $("reference-more").onclick = () => {
        limit += 20;
        filter(false);
      };
      filter();
      return;
    }
    if (section !== "overview") return;
    const specs = facts
      .filter((f) => factTopic(f.category) === "Specifications")
      .sort(
        (a, b) =>
          Number(
            /electrical requirements|dimensions|water pressure|rated|battery|charging time|wi.?fi frequency/i.test(
              b.name,
            ),
          ) -
          Number(
            /electrical requirements|dimensions|water pressure|rated|battery|charging time|wi.?fi frequency/i.test(
              a.name,
            ),
          ),
      );
    const safety = facts
      .filter((f) => factTopic(f.category) === "Safety")
      .sort(
        (a, b) =>
          Number(/disconnect|do not|never|keep|contact/i.test(b.value)) -
          Number(/disconnect|do not|never|keep|contact/i.test(a.value)),
      );
    $("overview").innerHTML =
      `${productIllustrations()}${p.review_pending ? '<p class="notice">Guides and reference results are available. Uncertainty review is still pending or running; see Analysis for its status.</p>' : ""}<div class="overview-columns"><section class="overview-preview"><h2>Specification</h2>
        ${specs.slice(0, 3).map(factCard).join("") || "<p>No specification entries were extracted.</p>"}</section>
      <section class="overview-preview"><h2>Safety</h2>
        ${safety.slice(0, 3).map(factCard).join("") || "<p>Consult the manual for safety instructions.</p>"}</section></div>
      <p class="fine">Safety preview only. Consult the manual for complete safety instructions.</p>
      <p>Choose a task below, or browse the reference by topic.</p>
      <div class="result-shortcuts">
        <button data-tab="troubleshooting"><strong>Troubleshoot a problem</strong><span>Choose a symptom</span></button>
        <button data-tab="installation"><strong>Install the product</strong><span>Source-linked steps, preparations and checks</span></button>
        <button data-tab="maintenance"><strong>Maintain the product</strong><span>Documented intervals and procedures</span></button>
        <button data-tab="questions"><strong>Ask a question</strong><span>Answers linked to the manual</span></button>
        <button data-tab="faq"><strong>Browse FAQ</strong><span>${(p.faq || []).length} generated questions · search by topic</span></button>
        <button data-tab="reference"><strong>Find specifications and instructions</strong><span>Installation, operation, maintenance and more</span></button>
      </div>
      <details class="card"><summary>Analysis coverage and image observations</summary><p>${esc(p.coverage_note)}</p>
        ${(p.visual_observations || []).map((v) => `<p>${sourceLink(v.page)} ${esc(v.observation)} <small>Image interpretation requires review.</small></p>`).join("")}</details>`;
  }
  return { renderResults };
}
