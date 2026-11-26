/* Display installation and maintenance guides as steps a reader can browse.

The view shows saved instructions, warnings, checks and documented intervals, with
source links and expandable limitations. Previous and Next change the displayed
step; they do not verify that physical work was completed or generate new advice. */
import { esc } from "../browser-helpers.js";
import { citations, independentChecks } from "./troubleshooting-and-faq.js";

/** Render cited preparations, warnings or completion checks as readable instructions.
 * Args:
 *   records — saved text and source quotations for one instruction group.
 * Returns:
 *   escaped HTML; an empty list produces no instructions.
 */
export function instructionList(records = []) {
  return records
    .map(
      (r) =>
        `<div class="guide-instruction"><p>${esc(r.text)}</p>${citations(r.citations)}</div>`,
    )
    .join("");
}

/** Keep guide limitations available in a compact, initially collapsed note.
 * Args:
 *   guide — saved procedure, including unanswered questions and review issues.
 * Returns:
 *   escaped expandable note with all limitations, or an empty string when none exist.
 */
export function guideGaps(guide) {
  const gaps = [
    ...(guide.unanswered_questions || []),
    ...(guide.review_issues || []),
  ];
  return gaps.length
    ? `<details class="guide-review-note"><summary>Information to check before using this guide</summary><ul>${gaps.map((g) => `<li>${esc(g)}</li>`).join("")}</ul></details>`
    : "";
}

/** Explain how an older saved manual can obtain the new procedure outputs.
 * Args:
 *   none.
 * Returns:
 *   button for an explicit bounded generation action, never automatic model work.
 */
export function guideBuildControl() {
  return `<div class="card"><p>Procedure guides have not been generated for this saved analysis. Build them from its original sources without repeating fact extraction.</p><button data-build-guides="true">Generate procedure guides</button></div>`;
}

/** Render a graphical sequence and an expanded, source-linked step for one procedure.
 * Args:
 *   target — guide detail element owned by the selected Results page.
 *   guide — saved installation or maintenance guide with stable step IDs.
 * Returns:
 *   nothing; installs local step/back/next navigation and preserves prerequisites.
 *   Missing steps stay visible as an unfinished guide, not a completed installation.
 */
function showProcedure(target, guide) {
  let position = 0;
  const installation = guide.kind === "installation";
  /** Refresh the selected step, showing shared installation preparations on step one only.
   * Args:
   *   none; reads the current position and saved guide in this view.
   * Returns:
   *   nothing; replaces only this guide's detail, without changing stored results.
   *   Review notes stay collapsed beneath the guide title; installation omits unrelated extra checks.
   *   Returning to step one restores its shared preparations; each step retains
   *   its own warnings and completion checks regardless of position.
   *   Displays partial outcomes, keeps the selected flow step horizontally visible,
   *   and retains a link to the separate troubleshooting navigator.
   */
  function render() {
    const step = guide.steps[position];
    const outcome = {
      partial: "Partial guide",
      stop: "Stop instruction",
      insufficient_evidence: "Insufficient source information",
    }[guide.outcome];
    target.innerHTML = `<article class="card"><h2>${esc(guide.title)}</h2>${guideGaps(guide)}${outcome ? `<p><strong>${outcome}</strong></p>` : ""}${installation ? `<details class="guide-context"><summary>Guide details</summary><p>Applies to: ${esc(guide.applies_to)}</p></details>` : `<p>Applies to: ${esc(guide.applies_to)}</p>`}
      ${(!installation || !guide.steps.length) && guide.prerequisites.length ? `<h3>Before you begin</h3>${instructionList(guide.prerequisites)}` : ""}
      ${guide.kind === "maintenance" ? `<h3>When to do this</h3>${guide.schedule ? instructionList([guide.schedule]) : "<p>Interval not specified in the inspected sources.</p>"}` : ""}
      <section class="procedure-steps"><h3>Steps</h3>
      <ol class="procedure-flow" aria-label="Procedure steps">${guide.steps.map((s, i) => `<li><button data-step="${i}" aria-current="${i === position ? "step" : "false"}"><small>Step ${i + 1}</small>${esc(s.title)}</button></li>`).join("")}</ol>
      ${
        step
          ? `<section class="procedure-current-step"><h3>Step ${position + 1}: ${esc(step.title)}</h3>${step.applies_when ? `<p><strong>Applies when:</strong> ${esc(step.applies_when)}</p>` : ""}
      ${installation && position === 0 && guide.prerequisites.length ? `<h4>Before you begin</h4>${instructionList(guide.prerequisites)}` : ""}
      <p>${esc(step.instruction)}</p>${citations(step.citations)}
      ${step.warnings.length ? `<h4>Warnings and gotchas</h4>${instructionList(step.warnings)}` : ""}
      ${step.checks.length ? `<h4>Check before continuing</h4>${instructionList(step.checks)}` : ""}
      <div class="page-actions"><button data-tab="troubleshooting">Find troubleshooting help</button><button data-step="${position - 1}" ${position === 0 ? "disabled" : ""}>Previous step</button><button data-step="${position + 1}" ${position === guide.steps.length - 1 ? "disabled" : ""}>Next step</button></div>
      <p class="fine">${position === guide.steps.length - 1 ? "End of this source-linked guide. Navigation does not verify that the work was completed." : "Follow the conditions and warnings before continuing."}</p></section>`
          : guide.independent_checks?.length
            ? ""
            : "<p>No usable steps were assembled.</p>"
      }
      </section>
      ${guide.independent_checks?.length ? `<details class="additional-checks" ${!guide.steps.length ? "open" : ""}><summary>Additional documented checks</summary>${independentChecks(guide.independent_checks)}</details>` : ""}
      </article>`;
    const flow = target.querySelector(".procedure-flow");
    const selected = flow.querySelector('[aria-current="step"]');
    if (selected && position > 0) {
      flow.scrollLeft =
        selected.getBoundingClientRect().left -
        flow.getBoundingClientRect().left +
        flow.scrollLeft -
        4;
    }
    target.querySelectorAll("[data-step]").forEach((button) => {
      button.onclick = () => {
        position = Number(button.dataset.step);
        render();
      };
    });
  }
  render();
}

/** Display installation guides or a maintenance schedule without hiding unspecified intervals.
 * Args:
 *   target — corresponding Results tab element.
 *   profile — saved analysis and optional procedure guides.
 *   kind — installation or maintenance.
 *   document — retained optional argument for existing callers; identity is in the shared header.
 * Returns:
 *   nothing; installation selects its first step; maintenance waits for an explicit
 *   topic selection before showing schedule, steps and collapsed additional checks.
 *   Model content is escaped and no task is marked physically completed by browsing.
 */
export function renderProcedureGuides(target, profile, kind, document = null) {
  const title =
    kind === "installation" ? "Installation assistant" : "Maintenance guide";

  if (!Object.hasOwn(profile, "procedure_guides")) {
    target.innerHTML = `<h2>${title}</h2>${guideBuildControl()}`;
    return;
  }
  const guides = profile.procedure_guides.filter((g) => g.kind === kind);
  const selector =
    kind === "installation"
      ? `<label class="installation-task-selector" ${guides.length < 2 ? "hidden" : ""}>Installation task <select data-installation-guide>${guides.map((g) => `<option value="${esc(g.id)}">${esc(g.title)}</option>`).join("")}</select></label>`
      : `<div class="guide-task-list">${guides.map((g) => `<button data-guide-id="${esc(g.id)}"><strong>${esc(g.title)}</strong><span>${esc(g.schedule?.text || "Interval not specified")}</span><small>${g.status === "unfinished" ? "Planning unfinished" : g.status === "needs_review" ? "Has information to check" : `${g.steps.length} source-linked steps`}</small></button>`).join("")}</div>`;
  target.innerHTML = `${kind === "installation" ? "" : `<h2>${title}</h2>`}${guides.length ? `${selector}<div class="selected-procedure"></div>` : profile.procedure_generation_pending ? "<p>Guide investigation is still running. Finished guides will appear here as they become available.</p>" : "<p>No source-supported procedures were identified for this category. This does not prove the manual contains none.</p>"}`;
  if (kind === "installation" && guides.length) {
    const selection = target.querySelector("[data-installation-guide]");
    if (selection)
      selection.onchange = () =>
        showProcedure(
          target.querySelector(".selected-procedure"),
          guides.find((g) => g.id === selection.value),
        );
    showProcedure(target.querySelector(".selected-procedure"), guides[0]);
  }

  const unassigned = (profile.procedure_discovery?.unassigned || []).filter(
    (item) => item.lead.kind === kind,
  );
  if (kind !== "installation" && unassigned.length) {
    target.insertAdjacentHTML(
      "beforeend",
      `<details class="card"><summary>Source material not assigned to a guide (${unassigned.length})</summary>${unassigned.map((item) => `<h3>${esc(item.lead.title)}</h3><p>${esc(item.reason)}</p>${citations(item.lead.citations)}`).join("")}</details>`,
    );
  }
  target.querySelectorAll("[data-guide-id]").forEach((button) => {
    button.onclick = () =>
      showProcedure(
        target.querySelector(".selected-procedure"),
        guides.find((g) => g.id === button.dataset.guideId),
      );
  });
}
