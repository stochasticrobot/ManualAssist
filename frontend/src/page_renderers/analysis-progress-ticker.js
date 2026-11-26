/* Show one real example of current analysis work in the browser progress strip.

Cycling through saved facts, active questions or stage messages gives readers a
useful view of progress without overwhelming the page. The display uses received
work records and does not ask an AI to invent an update. */

import { $, esc, sourceLink } from "../browser-helpers.js";

/**
 * Show one current work item at a time: recent facts, active checks or stage status.
 * Args:
 *   none.
 * Returns:
 *   update and tick methods. Uses the existing app timer; makes no requests. Rotation
 *   pauses on demand, keyboard focus, hidden pages, or a reduced-motion preference.
 */
export function createFactTicker() {
  let facts = [],
    signature = "",
    job = null,
    index = 0,
    changed = 0,
    paused = false,
    focus = {
      kind: "facts",
      title: "Recently extracted facts",
      scope: "facts",
    };
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  /**
   * Render a fact, completed troubleshooting node or actual review proposal with its source pages and stage label.
   * Args:
   *   none.
   * Returns:
   *   nothing; escapes all model text and truncates only the displayed value preview.
   *   Full facts remain in the eventual report; the source link opens the PDF page.
   */
  function paint() {
    const target = $("fact-ticker");
    if (!target) return;
    target.setAttribute("aria-label", focus.title);
    if (!facts.length) {
      target.innerHTML =
        "<h3>Recently extracted facts</h3><p>The first source-checked facts will appear here when a group finishes.</p>";
      return;
    }
    const fact = facts[index];
    const value = String(fact.value || "");
    target.innerHTML = `<h3>${esc(focus.title)}</h3>
      <div class="fact-preview">${fact.category ? `<span class="tag">${esc(fact.category)}</span>` : ""}
      ${["facts", "troubleshooting"].includes(focus.kind) ? `<strong>${esc(fact.name)}</strong>` : ""}
      <p>${esc(value.length > 280 ? value.slice(0, 280) + "…" : value)}</p>
      <small>${esc(fact.applies_to || "")} ${fact.page ? sourceLink(fact.page) : ""}${fact.pages?.length ? ` · Source pages: ${fact.pages.map((page) => sourceLink(page)).join(" · ")}` : ""}</small></div>
      <div class="fact-controls"><small>${index + 1} of ${facts.length} ${focus.kind === "facts" ? "recent facts" : focus.kind === "troubleshooting" ? "recent steps" : "current checks"}</small>
      <button type="button" id="fact-pause" aria-pressed="${paused}">${paused ? "Resume rotation" : "Pause rotation"}</button>
      <button type="button" id="fact-next">Next ${focus.kind === "facts" ? "fact" : focus.kind === "troubleshooting" ? "step" : "check"}</button></div>`;
    target.querySelector(".fact-controls").hidden = focus.kind === "status";
    $("fact-pause").disabled = reducedMotion.matches || facts.length < 2;
    $("fact-pause").onclick = () => {
      paused = !paused;
      changed = Date.now();
      paint();
      $("fact-pause").focus();
    };
    $("fact-next").onclick = () => {
      index = (index + 1) % facts.length;
      changed = Date.now();
      paint();
      $("fact-next").focus();
    };
  }

  /**
   * Refresh the recent window only when accepted results or the selected job change.
   * Args:
   *   recent — up to eight persisted accepted facts, newest first.
   *   jobId — selected document ID, used to prevent facts leaking between views.
   *   activity — current stage title, kind and request scope; changing scope clears stale checks.
   * Returns:
   *   nothing; new results show the newest fact unless paused; a new task or source group
   *   always replaces stale content, even when the previous task was paused.
   *   Unchanged polling responses do not reset the selected fact or its timer.
   */
  function update(
    recent,
    jobId,
    activity = {
      kind: "facts",
      title: "Recently extracted facts",
      scope: "facts",
    },
  ) {
    if (
      job !== jobId ||
      focus.scope !== activity.scope ||
      focus.kind !== activity.kind
    ) {
      job = jobId;
      paused = false;
      signature = "";
      facts = [];
    }
    focus = activity;
    const next = JSON.stringify(recent);
    if (next === signature) return;
    // A paused card stays readable even when a newer accepted batch arrives.
    if (paused && facts.length) return;
    signature = next;
    facts = recent;
    index = 0;
    changed = Date.now();
    paint();
  }

  /**
   * Advance the visible fact every eight seconds while automatic rotation is allowed.
   * Args:
   *   none.
   * Returns:
   *   nothing; skips rotation while the card is hidden or focused so reading and
   *   source navigation are not disrupted. Does not announce recurring live alerts.
   */
  function tick() {
    const target = $("fact-ticker");
    if (
      !target ||
      !target.offsetParent ||
      document.hidden ||
      paused ||
      reducedMotion.matches ||
      target.contains(document.activeElement) ||
      facts.length < 2 ||
      Date.now() - changed < 8000
    )
      return;
    index = (index + 1) % facts.length;
    changed = Date.now();
    paint();
  }
  return { update, tick };
}
