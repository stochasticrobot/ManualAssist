/* Display saved troubleshooting diagrams, independent checks and searchable FAQs.

Readers can follow supported branches, filter questions and open the quotations
behind an answer. The controls browse existing material; they do not generate new
diagnoses or treat independent checks as a required sequence. */
import { referenceIllustrations } from "./source-reference-illustrations.js";
import { esc, sourceLink } from "../browser-helpers.js";

const kinds = {
  check: "Decision",
  action: "Action",
  stop: "Stop",
  unresolved: "Missing information",
};

/**
 * Render collapsible supporting passages without treating citations as safety approval.
 * Args:
 *   records — saved page-qualified citations.
 * Returns:
 *   escaped details element containing original quotations and page links.
 */
export function citations(records) {
  return `${referenceIllustrations(records)}<details class="supporting-source"><summary>Supporting source</summary>${records
    .map(
      (c) =>
        `${sourceLink(c.page, c.evidence_id)}<blockquote class="quote">${esc(c.quote)}</blockquote>`,
    )
    .join("")}</details>`;
}

/**
 * Draw all saved nodes and branches in topological columns using native SVG.
 * Args:
 *   tree — validated acyclic tree with root ID and node/branch text.
 * Returns:
 *   scrollable, keyboard-operable diagram HTML. Long labels have full-text tooltips;
 *   selecting a node displays its full content alongside the graph. Adds no branches.
 */
function diagram(tree) {
  const nodes = new Map(tree.nodes.map((n) => [n.id, n]));
  const depth = new Map([[tree.root, 0]]);
  // Repeated relaxation handles shared descendants without requiring a layout library.
  for (let pass = 0; pass < tree.nodes.length; pass++) {
    for (const node of tree.nodes) {
      if (!depth.has(node.id)) continue;
      for (const branch of node.branches)
        depth.set(
          branch.next_node,
          Math.max(depth.get(branch.next_node) || 0, depth.get(node.id) + 1),
        );
    }
  }
  const levels = new Map();
  for (const node of tree.nodes) {
    const level = depth.get(node.id) || 0;
    if (!levels.has(level)) levels.set(level, []);
    levels.get(level).push(node);
  }
  const maxRows = Math.max(
    ...[...levels.values()].map((group) => group.length),
  );
  const height = Math.max(160, maxRows * 150);
  const width = levels.size * 310 - 60;
  const positions = new Map();
  for (const [level, group] of levels)
    group.forEach((node, index) =>
      positions.set(node.id, {
        x: level * 310 + 10,
        y: (height / group.length) * (index + 0.5) - 50,
      }),
    );
  const edges = tree.nodes
    .flatMap((node) =>
      node.branches.map((branch) => {
        const a = positions.get(node.id),
          b = positions.get(branch.next_node);
        if (!a || !b || !nodes.has(branch.next_node)) return "";
        const x1 = a.x + 220,
          y1 = a.y + 50,
          x2 = b.x,
          y2 = b.y + 50;
        return `<g data-edge-from="${esc(node.id)}" data-edge-to="${esc(branch.next_node)}">
      <title>${esc(branch.condition)}</title>
      <path d="M ${x1} ${y1} C ${x1 + 42} ${y1}, ${x2 - 42} ${y2}, ${x2} ${y2}" />
      <text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 8}" text-anchor="middle">${esc(branch.condition.slice(0, 12))}${branch.condition.length > 12 ? "…" : ""}</text>
    </g>`;
      }),
    )
    .join("");
  const boxes = tree.nodes
    .map((node) => {
      const pos = positions.get(node.id);
      return `<foreignObject x="${pos.x}" y="${pos.y}" width="220" height="105">
      <div xmlns="http://www.w3.org/1999/xhtml" class="diagram-box">
        <button data-preview-node="${esc(node.id)}" title="${esc(node.text)}" aria-label="Inspect ${esc(kinds[node.kind])}: ${esc(node.text)}">
          <small>${esc(kinds[node.kind])}</small><span>${esc(node.text)}</span>
        </button>
      </div></foreignObject>`;
    })
    .join("");
  return `<div class="tree-diagram" tabindex="0" aria-label="Troubleshooting diagram; scroll horizontally for wide paths">
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-label="Nodes and decision branches">${edges}${boxes}</svg></div>`;
}

/**
 * Build a single symptom's diagram, prerequisites and full step descriptions.
 * Args:
 *   tree — saved diagnostic tree.
 * Returns:
 *   escaped HTML; prerequisites remain visible regardless of selected step.
 */
export function treePanel(tree) {
  return `<article class="diagnostic-tree card" data-root="${esc(tree.root)}">
    <h2>${esc(tree.symptom)}</h2><p>Applies to: ${esc(tree.applies_to)}</p>
    ${
      tree.prerequisites.length
        ? `<section class="tree-prerequisites"><h3>Before you begin</h3>${tree.prerequisites
            .map(
              (p) =>
                `<div><strong>${esc(p.question)}</strong><p>${esc(p.answer)}</p>${citations(p.citations)}</div>`,
            )
            .join("")}</section>`
        : ""
    }
    <p class="fine">Select a box to inspect a step. Use the choices below to follow a decision path. Check the manual’s safety instructions before taking action.</p>
    ${diagram(tree)}
    <p class="tree-path fine"></p>
    ${tree.nodes
      .map(
        (
          node,
        ) => `<section class="current-tree-step" data-node="${esc(node.id)}" ${node.id === tree.root ? "" : "hidden"}>
      <span class="tag">${esc(kinds[node.kind])}</span><h3>${esc(node.text)}</h3>
      ${citations(node.citations)}
      <div class="branch-choices">${node.branches.map((branch) => `<div><button data-next-node="${esc(branch.next_node)}" data-from-node="${esc(node.id)}">${esc(branch.condition)}</button>${citations(branch.citations)}</div>`).join("")}</div>
      ${node.branches.length ? "" : '<p class="fine">End of this generated path.</p>'}
    </section>`,
      )
      .join("")}
    <button class="secondary" data-next-node="${esc(tree.root)}" data-reset-tree="true">Start over</button>
  </article>`;
}

/**
 * Show one searchable symptom list and one selected diagram, not every tree at once.
 * Args:
 *   target — troubleshooting section element.
 *   profile — saved analysis profile.
 * Returns:
 *   nothing; installs local search/selection handlers with no API or model calls.
 */
export function renderTroubleshooting(target, profile) {
  if (!Object.hasOwn(profile, "troubleshooting")) {
    target.innerHTML =
      "<h2>Troubleshooting</h2><p>This earlier analysis did not generate troubleshooting paths.</p>";
    return;
  }
  const trees = [
    ...(profile.troubleshooting || []),
    ...(profile.troubleshooting_checks || []),
  ];
  target.innerHTML = `<h2>Troubleshooting</h2><p>Choose the symptom that matches your problem.</p>
    <div class="troubleshooting-layout"><div class="symptom-picker"><label>Find a symptom<input id="symptom-search" type="search" placeholder="Drain, door, noise, error code…"></label>
    <p id="symptom-count" class="fine"></p><div id="symptom-list"></div></div>
    <div id="selected-tree"><div class="card"><h3>Select a symptom</h3><p>Documented checks or a supported diagnostic path will appear here.</p></div></div></div>`;
  let selected = null;
  /**
   * Filter symptom labels and applicability while keeping selection independent.
   * Args:
   *   none; reads local search text.
   * Returns:
   *   nothing; preserves selected tree and displays a useful empty state.
   */
  function filter() {
    const query = target.querySelector("#symptom-search").value.toLowerCase();
    const matches = trees
      .map((tree, index) => ({ tree, index }))
      .filter(({ tree }) =>
        (tree.symptom + " " + tree.applies_to).toLowerCase().includes(query),
      );
    target.querySelector("#symptom-count").textContent =
      `${matches.length} of ${trees.length} symptoms`;
    target.querySelector("#symptom-list").innerHTML =
      matches
        .map(
          ({ tree, index }) =>
            `<button class="symptom-option ${index === selected ? "selected" : ""}" data-symptom="${index}" aria-pressed="${index === selected}">${esc(tree.symptom)}<small>${tree.nodes ? `${tree.nodes.length} steps` : "Documented check"}</small></button>`,
        )
        .join("") || "<p>No matching symptoms.</p>";
  }
  target.querySelector("#symptom-search").oninput = filter;
  target.querySelector("#symptom-list").onclick = (event) => {
    const button = event.target.closest("[data-symptom]");
    if (!button) return;
    selected = Number(button.dataset.symptom);
    if (!trees[selected].nodes) {
      target.querySelector("#selected-tree").innerHTML = independentChecks([
        trees[selected],
      ]);
      filter();
      return;
    }
    target.querySelector("#selected-tree").innerHTML = treePanel(
      trees[selected],
    );
    const panel = target.querySelector(".diagnostic-tree");
    panel.dataset.path = JSON.stringify([trees[selected].root]);
    highlightTree(panel, trees[selected].root);
    filter();
    const heading = panel.querySelector("h2");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    if (window.innerWidth < 900) panel.scrollIntoView({ block: "start" });
  };
  filter();
}

/**
 * Highlight the inspected node separately from the route chosen through answers.
 * Args:
 *   panel — selected tree container.
 *   selected — inspected node ID.
 * Returns:
 *   nothing; updates SVG controls, chosen edges and path status without inference.
 */
function highlightTree(panel, selected) {
  const path = JSON.parse(panel.dataset.path || "[]");
  panel.querySelectorAll("[data-preview-node]").forEach((button) => {
    button.classList.toggle(
      "selected",
      button.dataset.previewNode === selected,
    );
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.previewNode === selected),
    );
  });
  panel.querySelectorAll("[data-edge-from]").forEach((edge) => {
    edge.classList.toggle(
      "chosen",
      path.some(
        (id, index) =>
          id === edge.dataset.edgeFrom &&
          path[index + 1] === edge.dataset.edgeTo,
      ),
    );
  });
  panel.querySelector(".tree-path").textContent =
    path.at(-1) === selected
      ? `Following your path · step ${path.length}`
      : "Inspecting a step outside your selected path";
}

/**
 * Follow an explicit choice or inspect a diagram node without making model calls.
 * Args:
 *   button — diagram, branch or restart button within the selected tree.
 * Returns:
 *   nothing; shows full text, tracks only explicitly chosen edges and focuses the step.
 *   Inspection outside the current route starts a new route if a choice is then made.
 */
export function navigateTree(button) {
  const panel = button.closest(".diagnostic-tree");
  if (!panel) return;
  const selected = button.dataset.previewNode ?? button.dataset.nextNode;
  let path = JSON.parse(panel.dataset.path || "[]");
  if (button.dataset.resetTree) path = [selected];
  else if (button.dataset.nextNode !== undefined) {
    const from = button.dataset.fromNode;
    const at = path.indexOf(from);
    path = at >= 0 ? path.slice(0, at + 1) : [from];
    path.push(selected);
  }
  panel.dataset.path = JSON.stringify(path);
  panel.querySelectorAll("[data-node]").forEach((node) => {
    node.hidden = node.dataset.node !== selected;
    if (!node.hidden) {
      node.tabIndex = -1;
      node.focus({ preventScroll: true });
    }
  });
  highlightTree(panel, selected);
}

/**
 * Group and search FAQs using topics of their cited source facts, not invented tags.
 * Args:
 *   target — FAQ section element.
 *   profile — saved FAQ entries and extracted facts.
 *   topicFor — mapping from original fact category to reader-facing topic.
 *   document — retained optional argument for callers; the shared Results header owns identity.
 * Returns:
 *   nothing; renders twenty matches at a time with full answers and source links.
 *   Unmatched citations stay under Other information; grouping is browsing assistance.
 */
export function renderFAQ(target, profile, topicFor, document = null) {
  if (!Object.hasOwn(profile, "faq")) {
    target.innerHTML =
      "<h2>FAQ</h2><p>This earlier analysis did not generate FAQ entries.</p>";
    return;
  }
  const sourceTopics = new Map();
  for (const fact of profile.facts || []) {
    if (!sourceTopics.has(fact.evidence_id))
      sourceTopics.set(fact.evidence_id, new Set());
    sourceTopics.get(fact.evidence_id).add(topicFor(fact.category));
  }
  const entries = (profile.faq || []).map((entry) => ({
    ...entry,
    topics: [
      ...new Set(
        entry.citations.flatMap((c) => [
          ...(sourceTopics.get(c.evidence_id) || []),
        ]),
      ),
    ],
  }));
  for (const entry of entries)
    if (!entry.topics.length) entry.topics = ["Other information"];
  const topics = [...new Set(entries.flatMap((entry) => entry.topics))].sort();
  target.innerHTML = `<h2>Frequently asked questions</h2><p>Browse generated answers. Topics are based on the facts cited by each answer.</p>
    <div class="result-filters"><label>Topic<select id="faq-topic"><option value="">All topics</option>${topics.map((t) => `<option>${esc(t)}</option>`).join("")}</select></label>
    <label>Search questions and answers<input id="faq-search" type="search" placeholder="Search FAQ…"></label></div>
    <p id="faq-count" class="fine"></p><div id="faq-items"></div><button id="faq-more" class="secondary">Show more</button>`;
  let limit = 20;
  /**
   * Display the bounded set matching the selected source topic and text query.
   * Args:
   *   reset — whether to return to the first twenty matches.
   * Returns:
   *   nothing; all saved FAQ entries remain accessible through search and Show more.
   */
  function filter(reset = true) {
    if (reset) limit = 20;
    const topic = target.querySelector("#faq-topic").value;
    const query = target.querySelector("#faq-search").value.toLowerCase();
    const matches = entries.filter(
      (e) =>
        (!topic || e.topics.includes(topic)) &&
        (e.question + " " + e.answer + " " + e.applies_to)
          .toLowerCase()
          .includes(query),
    );
    target.querySelector("#faq-items").innerHTML =
      matches
        .slice(0, limit)
        .map(
          (entry) =>
            `<details class="card"><summary>${esc(entry.question)}</summary><p>${esc(entry.answer)}</p><small>Applies to: ${esc(entry.applies_to)}</small>${citations(entry.citations)}</details>`,
        )
        .join("") || "<p>No matching questions.</p>";
    target.querySelector("#faq-count").textContent =
      `Showing ${Math.min(limit, matches.length)} of ${matches.length} matching questions`;
    target.querySelector("#faq-more").hidden = limit >= matches.length;
  }
  target.querySelector("#faq-topic").onchange = () => filter();
  target.querySelector("#faq-search").oninput = () => filter();
  target.querySelector("#faq-more").onclick = () => {
    limit += 20;
    filter(false);
  };
  filter();
}

/** Render independent documented checks without suggesting an order or flowchart.
 * Args:
 *   checks — saved symptom, applicability, instruction and source records.
 * Returns:
 *   escaped cards with source links; no branches or implied next actions are added.
 */
export function independentChecks(checks = []) {
  return checks
    .map(
      (check) =>
        `<article class="card"><h4>${esc(check.symptom)}</h4><p>${esc(check.applies_to)}</p><p>${esc(check.instruction)}</p>${citations(check.citations)}</article>`,
    )
    .join("");
}
