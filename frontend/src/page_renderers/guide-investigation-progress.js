/* Show separate progress for installation, maintenance and troubleshooting guides.

Readers can inspect each task, its collected evidence and whether its review has
actually finished. The page also offers an explicit repair action for unresolved
reviews; merely drawing the progress display does not start that action. */
import { esc, num, sourceLink } from "../browser-helpers.js";

const titles = {
  installation: "Installation",
  troubleshooting: "Troubleshooting",
  maintenance: "Maintenance",
};
const labels = {
  discovering: "Discovering tasks",
  queued: "Queued",
  not_started: "Not started",
  no_tasks: "No tasks identified",
  working: "Working",
  investigating: "Investigating",
  checking_finish: "Finish proposed · checking draft",
  finished: "Finished",
  finished_with_gaps: "Finished with gaps",
  incomplete: "Incomplete",
  failed: "Failed",
  stopped: "Stopped",
  paused: "Paused",
  unfinished: "Unfinished",
  stopped_before_completion: "Stopped before completion",
  allowance_exhausted: "Stopped before completion",
  review_unresolved: "Review unresolved",
  saved_needs_review: "Guide saved · finish not confirmed",
  needs_review: "Needs review",
};

/** Render category totals, per-task finish signals, reported findings and linked facts.
 * Args:
 *   target — dedicated container in the Agentic panel.
 *   current — current job detail with read-only workflow guide_progress and saved facts.
 * Returns:
 *   nothing; renders only observed progress, preserves open details across polls and
 *   makes no requests. Facts are matched by collected source ID, not guessed category.
 */
export function renderGuideProgress(target, current) {
  const sameJob = target.dataset.job === current.state.id;
  const opened = new Set(
    sameJob
      ? [...target.querySelectorAll("details[open][data-progress-key]")].map(
          (d) => d.dataset.progressKey,
        )
      : [],
  );
  target.dataset.job = current.state.id;
  const groups = current.workflow?.guide_progress;
  if (!groups) {
    target.innerHTML =
      "<p>Per-investigation details will appear when the progress update is activated.</p>";
    return;
  }
  const facts = current.profile?.facts || [];
  const sources = new Map(
    (current.document?.items || []).map((item) => [item.id, item]),
  );
  const blocked = groups.reduce((count, group) => count + group.tasks.filter((task) => task.status === "review_unresolved").length, 0);
  const recovery = blocked && current.state.status === "ready"
    ? `<p><button data-repair-guide-reviews="true">Repair unresolved reviews (${blocked})</button></p>`
    : "";
  target.innerHTML = recovery + groups
    .map((group) => {
      const finished = ["finished", "finished_with_gaps"].includes(
        group.status,
      );
      const groupFacts = group.fact_indexes
        .map((i) => facts[i])
        .filter(Boolean);
      const found = group.tasks.flatMap((task) =>
        task.questions.map((q) => ({ ...q, task: task.title })),
      );
      return `<section class="card guide-progress-group"><h3>${esc(titles[group.kind])} <span class="tag ${finished ? "guide-finished" : ""}">${esc(labels[group.status] || group.status)}</span></h3>
      ${group.total !== null && group.total > 0 ? `<progress max="${group.total}" value="${group.finished}" aria-label="${esc(titles[group.kind])} investigations finished"></progress><p>${num(group.finished)} / ${num(group.total)} investigations finished · ${num(group.saved_guides)} guides saved</p>` : `<p>${group.total === 0 ? "No assigned investigations." : "Investigation total not established yet."}</p>`}
      <p>${num(groupFacts.length)} extracted facts from ${num(group.evidence_ids.length)} collected source passages.</p>
      <details data-progress-key="${group.kind}-facts"><summary>Facts and sources</summary>${groupFacts.length ? groupFacts.map((f) => `<article><strong>${esc(f.name)}</strong><p>${esc(f.value)}</p>${sourceLink(f.page, f.evidence_id)}</article>`).join("") : "<p>No extracted facts match the collected sources yet.</p>"}
      ${group.evidence_ids
        .map((id) => sources.get(id))
        .filter(Boolean)
        .map(
          (s) =>
            `<p>${sourceLink(s.page, s.id)} ${esc(s.text.slice(0, 180))}${s.text.length > 180 ? "…" : ""}</p>`,
        )
        .join("")}</details>
      <details data-progress-key="${group.kind}-findings"><summary>Reported findings (${found.length})</summary>${
        found
          .map(
            (q) =>
              `<article><strong>${esc(q.question)}</strong><span class="tag">${esc(q.status)}</span><p>${esc(q.answer)}</p><small>${esc(q.task)}</small><p>${(
                q.evidence_ids || []
              )
                .map((id) => sources.get(id))
                .filter(Boolean)
                .map((s) => sourceLink(s.page, s.id))
                .join(" · ")}</p></article>`,
          )
          .join("") || "<p>No findings recorded yet.</p>"
      }</details>
      ${group.tasks
        .map(
          (
            task,
          ) => `<details data-progress-key="task-${esc(task.id)}"><summary>${esc(task.title)} — ${esc(labels[task.status] || task.status)}</summary>
        ${task.finish_proposed ? `<p>Agent proposed finishing.${["finished", "finished_with_gaps"].includes(task.status) ? " Investigation concluded after review." : " This signal alone does not establish completion."}</p>` : ""}
        <p>${num(task.inspections)} source inspections · ${num(task.reviews)} reviews</p>
        ${task.latest_reason ? `<p>${esc(task.latest_reason)}</p>` : ""}
        ${[...task.gaps, ...task.issues].length ? `<ul>${[...new Set([...task.gaps, ...task.issues])].map((text) => `<li>${esc(text)}</li>`).join("")}</ul>` : ""}
        ${task.guide_saved ? `<button data-artifact-kind="${group.kind}" data-artifact-id="${esc(task.id)}">Open saved guide</button>` : ""}</details>`,
        )
        .join("")}
    </section>`;
    })
    .join("");
  target.querySelectorAll("details[data-progress-key]").forEach((d) => {
    d.open = opened.has(d.dataset.progressKey);
  });
}
