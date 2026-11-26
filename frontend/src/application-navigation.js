/* Connect the browser controls to the saved manual and the work a reader requests.

This file switches pages, refreshes progress and sends explicit uploads,
questions, analysis requests and saved review notes. It keeps navigation separate
from creating new AI-generated content. */
import { createViews as resourceViews } from "./page_renderers/manual-sources-and-search-index.js";
import { navigateTree } from "./page_renderers/troubleshooting-and-faq.js";
import { $, esc, num, api, notice, sourceLink } from "./browser-helpers.js";
import { createViews as workflowViews } from "./page_renderers/import-and-analysis-progress.js";
import { createViews as resultViews } from "./page_renderers/results-overview-and-reference.js";
import { createViews as reviewViews } from "./page_renderers/uncertainty-review.js";
import { createViews as activityViews } from "./page_renderers/model-activity-log.js";
/* Staged document UI. Source/model strings are escaped; polling never starts model work. */
let jobId = null,
  current = null,
  currentPage = 1,
  activeTab = "import",
  signature = "",
  polling = false;
let priorAvailability = null,
  unread = new Set(),
  asked = false,
  questionGeneration = 0,
  uploading = false,
  startingAnalysis = false;
const pageTitles = {
  import: "PDF parsing",
  extraction: "Fact extraction",
  aids: "FAQ and troubleshooting steps",
  analysis: "Agentic guides",
  troubleshooting: "Results · Troubleshooting",
  installation: "Results · Installation",
  maintenance: "Results · Maintenance",
  faq: "Results · FAQ",
  reference: "Results · Reference",
  overview: "Results",
  sources: "Sources and outline",
  knowledge: "Knowledge base",
  questions: "Results · Ask a question",
  review: "Results · Needs review",
  audit: "Activity",
};
const resultTabs = new Set([
  "overview",
  "troubleshooting",
  "installation",
  "maintenance",
  "questions",
  "faq",
  "reference",
  "review",
  "knowledge",
]);
let returnTab = "overview";
const statusNames = {
  queued: "Import queued",
  parsing: "Reading PDF",
  parsed: "Imported",
  analyzing: "Analyzing",
  failed: "Stopped",
  paused: "Paused",
  interrupted: "Interrupted",
  ready: "Analysis complete",
  partial: "Partially complete",
};

const context = {
  get uploading() {
    return uploading;
  },
  get current() {
    return current;
  },
  get currentPage() {
    return currentPage;
  },
  evidence,
  showPage,
  get jobId() {
    return jobId;
  },
};
const { renderImport, renderAnalysis, updateElapsed } = workflowViews(context);
const { renderResults } = resultViews(context);
const { renderReview } = reviewViews(context);
const { renderAudit } = activityViews(context);
const { renderSources, renderKnowledge } = resourceViews(context);

/**
 * Render document navigation.
 *
 * Args:
 *   none.
 * Returns:
 *   promise after a read-only library refresh.
 */
async function library() {
  const jobs = await api("/api/jobs");
  $("jobs").innerHTML = jobs
    .map(
      (j) =>
        /* HTML */ `<button
          class="job ${j.id === jobId ? "active" : ""}"
          data-job="${j.id}"
        >
          ${esc(j.name)}<small
            >${esc(statusNames[j.status] || j.status)} · ${num(j.pages)}
            pages</small
          >
        </button>`,
    )
    .join("");
}

/** Choose the processing panel from persisted phase status, without starting work.
 * Args:
 *   data — selected job detail with optional workflow phases.
 * Returns:
 *   extraction, aids or analysis; completed facts do not imply guides are complete.
 */
function workflowPanel(data) {
  const phases = data.workflow?.phases || [];
  if (!phases.some((p) => p.id === "extract" && p.status === "complete"))
    return "extraction";
  if (
    phases.some(
      (p) =>
        ["faq", "troubleshooting"].includes(p.id) && p.status !== "complete",
    )
  )
    return "aids";
  return "analysis";
}

/**
 * Select a document.
 *
 * Args:
 *   id — job identifier; preferred — optional starting page.
 * Returns:
 *   promise; restores its stage without starting work. A confirmed missing job
 *   resets stale navigation to Import; other errors leave the selected ID intact.
 */
async function selectJob(id, preferred = null) {
  questionGeneration += 1;
  asked = false;
  jobId = id;
  current = null;
  currentPage = 1;
  signature = "";
  priorAvailability = null;
  unread.clear();
  history.replaceState(null, "", `#${id}`);
  $("answer").innerHTML = "";
  $("evidence-search").value = "";
  notice("");
  let d;
  try {
    d = await api(`/api/jobs/${id}`);
  } catch (error) {
    if (error.status === 404 && jobId === id) {
      newDocument();
      notice(
        "This analysis was removed. Choose a saved manual or import a PDF.",
      );
      return;
    }
    throw error;
  }
  if (jobId !== id) return;
  current = d;
  activeTab =
    preferred ||
    (!d.document
      ? "import"
      : d.state.status === "parsed"
        ? "extraction"
        : d.profile && ["ready", "partial"].includes(d.state.status)
          ? "overview"
          : workflowPanel(d));
  if (preferred === "import" && d.document) activeTab = "extraction";
  signature = JSON.stringify([
    d.state,
    d.audit.length,
    d.workflow?.guide_progress,
    d.illustrations,
  ]);
  render();
  await library();
}

/** Advance a viewed processing panel when its saved completion first arrives.
 * Args:
 *   previous — prior job snapshot.
 *   next — newly fetched snapshot of the same job.
 *   selected — current panel; source, result and manually revisited panels stay put.
 * Returns:
 *   next panel name. Both FAQ and troubleshooting generation must finish before
 *   Agentic guides opens. Fast successive completions may cross multiple panels;
 *   navigation never submits work and an already-completed panel is not a trigger.
 */
function advanceCompletedPanel(previous, next, selected) {
  const complete = (data, ids) =>
    ids.every((id) =>
      data?.workflow?.phases?.some(
        (phase) => phase.id === id && phase.status === "complete",
      ),
    );
  let advancing = false;
  if (selected === "import" && !previous?.document && next.document) {
    selected = "extraction";
    advancing = true;
  }
  if (
    selected === "extraction" &&
    complete(next, ["extract"]) &&
    (advancing || !complete(previous, ["extract"]))
  ) {
    selected = "aids";
    advancing = true;
  }
  if (
    selected === "aids" &&
    complete(next, ["faq", "troubleshooting"]) &&
    (advancing || !complete(previous, ["faq", "troubleshooting"]))
  )
    selected = "analysis";
  return selected;
}

/**
 * Poll saved progress without overlapping requests or applying an old document's response.
 *
 * Args:
 *   none.
 * Returns:
 *   promise; failures are shown and incomplete requests do not trigger model calls.
 */
async function refresh() {
  if (!jobId || polling) return;
  polling = true;
  const id = jobId;
  try {
    const d = await api(`/api/jobs/${id}`);
    if (id !== jobId) return;
    const next = JSON.stringify([
      d.state,
      d.audit.length,
      d.workflow?.guide_progress,
      d.illustrations,
    ]);
    if (next !== signature) {
      const oldStatus = current?.state.status;
      activeTab = advanceCompletedPanel(current, d, activeTab);
      current = d;
      signature = next;
      render();
      if (oldStatus !== d.state.status) await library();
    }
  } catch (e) {
    notice(e.message);
  } finally {
    polling = false;
  }
}

/**
 * Compute available views from real artifacts.
 *
 * Args:
 *   none.
 * Returns:
 *   per-view booleans; incomplete outputs stay disabled.
 */
function availability() {
  const d = current;
  return {
    import: true,
    extraction: !!d?.document,
    aids: !!d?.document,
    analysis: !!d?.document,
    overview: !!d?.profile,
    troubleshooting: !!d?.profile,
    installation: !!d?.profile,
    maintenance: !!d?.profile,
    faq: !!d?.profile,
    reference: !!d?.profile,
    sources: !!d?.document,
    knowledge: !!d?.chunks,
    questions:
      !!d?.chunks &&
      (["ready", "partial"].includes(d?.state.status) ||
        d?.state.results_available),
    review: !!d?.profile || !!d?.state.review.length,
    audit: !!d,
  };
}

/**
 * Update navigation with one-time new-content indicators.
 *
 * Args:
 *   none.
 * Returns:
 *   nothing; disabled controls remain visible with explanations.
 */
function navigation() {
  const available = availability();
  const inResults = resultTabs.has(activeTab);
  $("tabs").hidden = !inResults;
  $("results-product").hidden = !inResults;
  $("browse-reference").hidden = !inResults;
  $("context-tools").hidden = !current?.document;
  $("result-tools").hidden = !inResults;
  $("return-context").hidden = !["sources", "knowledge", "audit"].includes(
    activeTab,
  );
  $("return-context").textContent =
    "← Back to " + (pageTitles[returnTab] || "Results");
  for (const [key, yes] of Object.entries(available)) {
    if (
      priorAvailability &&
      yes &&
      !priorAvailability[key] &&
      key !== activeTab
    )
      unread.add(key);
  }
  priorAvailability = available;
  document.querySelectorAll("button[data-tab]").forEach((b) => {
    const name = b.dataset.tab;
    b.disabled = !available[name];
    const selected =
      name === activeTab ||
      (b.closest("#flow-nav") &&
        ((name === "overview" && inResults) ||
          (name === "analysis" && activeTab === "audit")));
    const runningPanel = ["queued", "parsing"].includes(current?.state.status)
      ? "import"
      : current?.state.status === "analyzing"
        ? workflowPanel(current)
        : null;
    const running = !!b.closest("#flow-nav") && name === runningPanel;
    b.classList.toggle("is-running", running);
    b.setAttribute(
      "aria-label",
      b.textContent.trim() + (running ? " — Working" : ""),
    );
    b.classList.toggle("active", !!selected);
    b.classList.toggle("has-new", unread.has(name));
    b.setAttribute("aria-current", selected ? "page" : "false");
    b.title = available[name]
      ? unread.has(name)
        ? "New information is available"
        : ""
      : name === "analysis" || name === "sources"
        ? "Available after PDF import"
        : "Available when this output has been generated";
  });
}

/**
 * Change page without discarding input.
 *
 * Args:
 *   name — known view name.
 * Returns:
 *   nothing; unavailable views cannot be selected.
 */
function tab(name) {
  if (!availability()[name]) return;
  if (
    ["sources", "knowledge", "audit"].includes(name) &&
    !["sources", "knowledge", "audit"].includes(activeTab)
  )
    returnTab = activeTab;
  activeTab = name;
  unread.delete(name);
  $("page-title").textContent = pageTitles[name];
  document.querySelectorAll(".tab").forEach((e) => (e.hidden = e.id !== name));
  navigation();
  renderActive();
}

/**
 * Display a physical source page.
 *
 * Args:
 *   page — one-based page number.
 * Returns:
 *   nothing; avoids reloading an unchanged image during polling.
 */
function showPage(page) {
  currentPage = Math.max(1, Math.min(page, current?.state.pages || 1));
  $("page-label").textContent =
    `PDF page ${currentPage} / ${current?.state.pages || "—"}`;
  const url = `/api/jobs/${jobId}/pages/${currentPage}`;
  if ($("page-image").getAttribute("src") !== url) $("page-image").src = url;
  $("original").href = `/api/jobs/${jobId}/source#page=${currentPage}`;
}

/**
 * Filter local source items.
 *
 * Args:
 *   none.
 * Returns:
 *   nothing; searches text without paid requests.
 */
function evidence() {
  const q = $("evidence-search").value.toLowerCase();
  $("evidence").innerHTML = (current?.document?.items || [])
    .filter((i) => i.text.toLowerCase().includes(q))
    .map(
      (i) =>
        /* HTML */ `<article class="card">
          <span class="tag">${esc(i.label)}</span>${sourceLink(i.page, i.id)}
          <p>${esc(i.text)}</p>
        </article>`,
    )
    .join("");
}

/**
 * Render only the selected resource view.
 *
 * Args:
 *   none.
 * Returns:
 *   nothing; hidden large source lists are not rebuilt during processing.
 */
function renderActive() {
  if (activeTab === "import") {
    renderImport();
    return;
  }
  if (!current) return;
  if (["extraction", "aids", "analysis"].includes(activeTab)) {
    $(activeTab).append($("workflow-panel-content"));
    renderAnalysis(activeTab);
    return;
  }
  if (resultTabs.has(activeTab)) renderResults(activeTab);
  if (activeTab === "sources") renderSources();
  if (activeTab === "knowledge") renderKnowledge();
  if (activeTab === "review") renderReview();
  if (activeTab === "audit") renderAudit();
  $("ask-button").disabled = asked || !availability().questions;
}

/**
 * Refresh visible status after polling has advanced any newly completed processing panel.
 *
 * Args:
 *   none.
 * Returns:
 *   nothing; announces meaningful status changes.
 */
function render() {
  const s = current?.state;
  $("document-bar").hidden = !s;
  if (s) {
    $("title").textContent = s.name;
    $("status").textContent = statusNames[s.status] || s.status;
    $("live-status").textContent = current.workflow?.current.message || s.stage;
  }
  if (!availability()[activeTab]) activeTab = "import";
  tab(activeTab);
}

/**
 * Upload a PDF.
 *
 * Args:
 *   event — file input change.
 * Returns:
 *   promise; stays on parsing until a document is available, then shows fact extraction.
 *   Navigation never submits an additional analysis request.
 */
async function upload(event) {
  const file = event.target.files[0];
  if (!file || uploading || current) return;
  uploading = true;
  renderImport();
  notice("Uploading the PDF and checking that it can be opened…");
  const form = new FormData();
  form.append("file", file);
  try {
    const j = await api("/api/jobs", { method: "POST", body: form });
    await selectJob(j.id, "import");
    notice("");
  } catch (e) {
    notice(e.message);
  } finally {
    event.target.value = "";
    uploading = false;
    if (activeTab === "import") renderImport();
  }
}

/**
 * Start analysis explicitly.
 *
 * Args:
 *   none.
 * Returns:
 *   promise; rejected preflight leaves the PDF and usage unchanged.
 */
async function analyze() {
  if (startingAnalysis || current?.state.status !== "parsed") return;
  startingAnalysis = true;
  $("continue-analysis").disabled = true;
  $("analyze").disabled = true;
  try {
    await api(`/api/jobs/${jobId}/analyze`, { method: "POST" });
    notice("");
    await refresh();
  } catch (e) {
    notice(e.message);
  } finally {
    startingAnalysis = false;
    $("analyze").disabled = false;
    navigation();
  }
}

/**
 * Resume a supported stopped analysis.
 *
 * Args:
 *   none.
 * Returns:
 *   promise; authorizes another bounded work slice and reuses compatible saved responses.
 */
async function resume() {
  $("resume").disabled = true;
  try {
    await api(`/api/jobs/${jobId}/resume`, { method: "POST" });
    notice("");
    await refresh();
  } catch (e) {
    notice(e.message);
  } finally {
    $("resume").disabled = false;
  }
}

/**
 * Ask a source-grounded question.
 *
 * Args:
 *   event — submit event.
 * Returns:
 *   promise; renders cited claims or insufficient evidence.
 */
async function ask(event) {
  event.preventDefault();
  if (asked || !jobId) return;
  const requestJob = jobId;
  const requestGeneration = ++questionGeneration;
  // A manual switch invalidates success, error and cleanup from this request,
  // including a switch away and back to the same manual while it is pending.
  const stillCurrent = () =>
    requestJob === jobId && requestGeneration === questionGeneration;
  asked = true;
  $("ask-button").disabled = true;
  $("answer").textContent =
    "Searching this manual for relevant passages, then checking whether they answer your question…";
  try {
    const r = await api(`/api/jobs/${requestJob}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: $("question").value }),
    });
    if (!stillCurrent()) return;
    $("answer").innerHTML =
      (r.insufficient
        ? '<div class="notice">The manual does not provide enough evidence to answer this question.</div>'
        : "") +
      r.claims
        .map(
          (c) =>
            /* HTML */ `<article class="card">
              <p>${esc(c.statement)}</p>
              ${sourceLink(c.page, c.evidence_id)}
              <div class="quote">${esc(c.quote)}</div>
            </article>`,
        )
        .join("");
    if (r.related_guides?.length) {
      $("answer").insertAdjacentHTML(
        "beforeend",
        `<section class="card"><h3>Related guides</h3><p>Matching saved guidance—not a diagnosis.</p>${r.related_guides.map((g) => `<button data-artifact-kind="${esc(g.kind)}" data-artifact-id="${esc(g.id)}">${esc(g.title)}${g.status === "needs_review" ? " · has information to check" : ""}</button>`).join("")}</section>`,
      );
    }
    await refresh();
  } catch (e) {
    if (stillCurrent()) $("answer").textContent = e.message;
  } finally {
    if (stillCurrent()) {
      asked = false;
      $("ask-button").disabled = !availability().questions;
    }
  }
}

/**
 * Handle navigation and review controls.
 *
 * Args:
 *   event — click.
 * Returns:
 *   promise; performs only the selected action. Saved installation links select
 *   the matching guide and its first step through the existing local selector.
 */
async function click(event) {
  const b = event.target.closest("button");
  if (!b || b.disabled) return;
  try {
    if (b.dataset.nextNode !== undefined || b.dataset.previewNode !== undefined)
      navigateTree(b);
    if (b.dataset.repairGuideReviews) {
      b.disabled = true;
      try {
        await api(`/api/jobs/${jobId}/repair-guide-reviews`, { method: "POST" });
        await refresh();
        tab("analysis");
      } finally {
        b.disabled = false;
      }
    }
    if (b.dataset.buildGuides) {
      b.disabled = true;
      try {
        await api(`/api/jobs/${jobId}/procedure-guides`, { method: "POST" });
        await refresh();
        tab("analysis");
      } finally {
        b.disabled = false;
      }
    }
    if (b.dataset.artifactKind) {
      tab(b.dataset.artifactKind);
      const id = b.dataset.artifactId;
      const section = $(b.dataset.artifactKind);
      if (id.startsWith("tree-")) {
        section.querySelector('[data-entry="all"]')?.click();
        section
          .querySelector(`[data-symptom="${Number(id.slice(5))}"]`)
          ?.click();
      } else if (b.dataset.artifactKind === "installation") {
        const selection = section.querySelector("[data-installation-guide]");
        if (
          selection &&
          [...selection.options].some((option) => option.value === id)
        ) {
          selection.value = id;
          selection.dispatchEvent(new Event("change"));
        }
      } else {
        const button = section.querySelector(
          `[data-guide-id="${CSS.escape(id)}"]`,
        );
        const details = button?.closest("details");
        if (details) details.open = true;
        button?.click();
      }
    }
    if (b.dataset.job) await selectJob(b.dataset.job);
    if (b.dataset.tab) tab(b.dataset.tab);
    if (b.dataset.startAnalysis && current?.state.status === "parsed")
      await analyze();
    if (b.dataset.page) {
      tab("sources");
      showPage(Number(b.dataset.page));
    }
    if (b.dataset.review !== undefined) {
      const i = Number(b.dataset.review);
      await api(`/api/jobs/${jobId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          index: i,
          status: $(`review-status-${i}`).value,
          note: $(`review-note-${i}`).value,
        }),
      });
      b.focus();
      await refresh();
      notice("Review saved.");
    }
  } catch (e) {
    notice(e.message);
  }
}

/**
 * Open an import page without discarding existing jobs.
 *
 * Args:
 *   none.
 * Returns:
 *   nothing; clears the selected document, not stored data.
 */
function newDocument() {
  questionGeneration += 1;
  asked = false;
  $("answer").innerHTML = "";
  jobId = null;
  current = null;
  signature = "";
  priorAvailability = null;
  unread.clear();
  activeTab = "import";
  history.replaceState(null, "", location.pathname);
  notice("");
  render();
  library().catch((e) => notice(e.message));
}

/**
 * Restore fragment navigation.
 *
 * Args:
 *   none.
 * Returns:
 *   promise; ignores invalid or unchanged IDs.
 */
async function navigateHash() {
  const id = location.hash.slice(1);
  if (/^[a-f0-9]{32}$/.test(id) && id !== jobId) await selectJob(id);
}

/**
 * Initialize the staged UI.
 *
 * Args:
 *   none.
 * Returns:
 *   promise; starts read-only polling and restores the selected job.
 */
async function boot() {
  window.addEventListener("hashchange", navigateHash);
  $("new-document").addEventListener("click", newDocument);
  $("return-context").onclick = () => tab(returnTab);
  $("file").addEventListener("change", upload);
  $("analyze").addEventListener("click", analyze);
  $("resume").addEventListener("click", resume);
  $("ask-form").addEventListener("submit", ask);
  document.addEventListener("click", click);
  $("evidence-search").addEventListener("input", evidence);
  $("prev").onclick = () => showPage(currentPage - 1);
  $("next").onclick = () => showPage(currentPage + 1);
  render();
  await library();
  await navigateHash();
  setInterval(refresh, 2000);
  setInterval(updateElapsed, 1000);
}
boot().catch((e) => notice(e.message));
