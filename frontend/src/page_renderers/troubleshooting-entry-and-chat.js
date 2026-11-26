/* Help readers choose a troubleshooting topic and follow its saved diagnostic path.

A conversational view and a diagram use the same stored steps. Typed descriptions
help find symptoms, while ambiguous choices require the reader to choose a branch.
Navigating these paths does not call an AI or invent an additional repair. */
import { esc } from "../browser-helpers.js";
import {
  renderTroubleshooting,
  treePanel,
  citations,
  independentChecks,
} from "./troubleshooting-and-faq.js";
import {
  guideGaps,
  instructionList,
  guideBuildControl,
} from "./procedure-guides-and-schedule.js";

/** Find candidate symptom titles from a description without claiming a diagnosis.
 * Args:
 *   text — reader's description or symptom query.
 *   options — saved diagnostic trees with their source-linked node text.
 * Returns:
 *   matching tree records in original order; empty text shows every saved option.
 *   Word overlap is a browsing aid, not a semantic or medical/safety judgment.
 */
function matchingSymptoms(text, options) {
  const words =
    text
      .toLowerCase()
      .match(/[a-z0-9]+/g)
      ?.filter(
        (w) =>
          w.length > 1 &&
          ![
            "the",
            "a",
            "is",
            "it",
            "my",
            "not",
            "does",
            "what",
            "how",
            "i",
          ].includes(w),
      ) || [];
  return options.filter(
    (option) =>
      !words.length ||
      words.some((word) =>
        (
          option.tree.symptom +
          " " +
          (option.tree.nodes?.map((n) => n.text).join(" ") ||
            option.tree.instruction ||
            "")
        )
          .toLowerCase()
          .includes(word),
      ),
  );
}

/** Render the troubleshooting entry, existing issue browser, expanded paths and guided chat.
 * Args:
 *   target — Troubleshooting Results section.
 *   profile — saved issue-specific trees and optional investigated procedure guides.
 * Returns:
 *   nothing; installs local navigation and chat history. A selected branch always
 *   comes from the saved tree, and prerequisites remain visible in both presentations.
 *   A top-level record without diagnostic choices is omitted from navigation; the
 *   Start here section remains available without an empty-flowchart explanation.
 */
export function renderTroubleshootingSystem(target, profile) {
  const planned = (profile.procedure_guides || []).filter(
    (g) =>
      g.kind === "troubleshooting" &&
      (g.independent_checks?.length ||
        (g.troubleshooting &&
          (g.scope !== "top_level" ||
            g.troubleshooting.nodes.some(
              (node) => node.kind === "check" && node.branches.length > 0,
            )))),
  );
  const options = [
    ...(profile.troubleshooting || []).map((tree, i) => ({
      id: `tree-${i}`,
      tree,
    })),
    ...(profile.troubleshooting_checks || []).map((check, i) => ({
      id: `check-${i}`,
      tree: check,
    })),
    ...planned.flatMap((g) =>
      (g.independent_checks || []).map((check, i) => ({
        id: `${g.id}-check-${i}`,
        tree: check,
        guide: g,
      })),
    ),
    ...planned
      .filter((g) => g.troubleshooting)
      .map((g) => ({ id: g.id, tree: g.troubleshooting, guide: g })),
  ];
  const startingGuide = planned.find(
    (g) =>
      g.scope === "top_level" &&
      g.troubleshooting?.nodes.some(
        (node) => node.kind === "check" && node.branches.length > 0,
      ),
  );
  target.innerHTML = `<h2>Troubleshooting</h2>
    ${planned.length ? `<details class="card"><summary>Investigated troubleshooting guides</summary><div class="guide-task-list">${planned.map((g) => `<button data-guide-id="${esc(g.id)}">${esc(g.title)}<small>${g.status === "source_checked" ? "Sources and model review checked" : "Has information to check"}</small></button>`).join("")}</div><div id="planned-tree"></div></details>` : Object.hasOwn(profile, "procedure_guides") ? "" : guideBuildControl()}
    ${startingGuide ? `<section class="card"><h3>Diagnose from the beginning</h3>${guideGaps(startingGuide)}${startingGuide.prerequisites.length ? `<h4>Before you begin</h4>${instructionList(startingGuide.prerequisites)}` : ""}${startingGuide.troubleshooting ? treePanel(startingGuide.troubleshooting) : "<p>No supported starting diagnostic path was assembled.</p>"}</section>` : ""}<section class="card troubleshooting-entry"><h3>Start here: what do you need help with?</h3>
    <div class="result-shortcuts"><button data-entry="error">An error message or code</button><button data-entry="symptom">Something is not working as expected</button><button data-tab="installation">Installing the product</button><button data-tab="maintenance">Maintenance or cleaning</button></div>
    <div class="page-actions"><button class="secondary utility-control" data-entry="all">Browse symptoms and checks</button><button class="secondary utility-control" data-entry="chat">Use guided chat</button></div></section>
    <div id="issue-specific-browser"></div>
    <section id="troubleshooting-chat" class="card" hidden><h3>Guided troubleshooting chat</h3><p>Describe your symptom, then choose from supported branches. This follows saved paths; it is not an open-ended AI repair conversation.</p>
    <div class="chat-prerequisites"></div><div class="chat-transcript" role="log" aria-live="polite"></div><div class="chat-choices"></div>
    <form class="chat-form"><label>Your symptom or answer<input class="chat-input" maxlength="500" autocomplete="off"></label><button>Send</button><button type="button" class="chat-reset secondary">Start over</button></form></section>`;
  const browser = target.querySelector("#issue-specific-browser");
  renderTroubleshooting(browser, {
    ...profile,
    troubleshooting_checks: profile.troubleshooting_checks || [],
  });
  browser.hidden = true;
  const chat = target.querySelector("#troubleshooting-chat");
  let chosen = null,
    node = null;
  const transcript = chat.querySelector(".chat-transcript");
  const choices = chat.querySelector(".chat-choices");

  /** Append a reader or guide message using escaped text and optional saved sources.
   * Args:
   *   who — visible speaker label.
   *   text — literal reader input or saved node text.
   *   sources — optional saved source citations for the guide message.
   * Returns:
   *   nothing; adds one message without rewriting or interpreting its instructions.
   */
  function message(who, text, sources = []) {
    transcript.insertAdjacentHTML(
      "beforeend",
      `<article class="chat-message"><strong>${esc(who)}</strong><p>${esc(text)}</p>${sources.length ? citations(sources) : ""}</article>`,
    );
  }

  /** Display choices from the current node; terminal nodes offer no invented next step.
   * Args:
   *   next — saved node reached through a selected, existing branch.
   * Returns:
   *   nothing; updates chat controls and announces the saved instruction with sources.
   */
  function showNode(next) {
    node = next;
    message("Guide", node.text, node.citations);
    choices.innerHTML =
      node.branches
        .map(
          (branch, i) =>
            `<div><button data-chat-branch="${i}">${esc(branch.condition)}</button>${citations(branch.citations)}</div>`,
        )
        .join("") ||
      "<p>End of this supported path. You can start over or check the linked manual.</p>";
    choices.querySelectorAll("[data-chat-branch]").forEach((button) => {
      button.onclick = () => {
        const branch = node.branches[Number(button.dataset.chatBranch)];
        message("You", branch.condition);
        showNode(chosen.tree.nodes.find((n) => n.id === branch.next_node));
      };
    });
  }

  /** Offer matching saved symptoms for explicit selection, never automatic diagnosis.
   * Args:
   *   text — symptom description, or an empty string to browse all paths.
   * Returns:
   *   nothing; selecting an option reveals prerequisites and starts at its root node.
   */
  function chooseSymptom(text = "") {
    chosen = null;
    node = null;
    const matches = matchingSymptoms(text, options);
    choices.innerHTML =
      matches
        .map(
          (option) =>
            `<button data-chat-symptom="${esc(option.id)}">${esc(option.tree.symptom)}</button>`,
        )
        .join("") ||
      "<p>No matching saved path. Try another symptom or use Ask a question.</p>";
    choices.querySelectorAll("[data-chat-symptom]").forEach((button) => {
      button.onclick = () => {
        chosen = options.find((o) => o.id === button.dataset.chatSymptom);
        message("You", chosen.tree.symptom);
        chat.querySelector(".chat-prerequisites").innerHTML =
          (chosen.guide
            ? guideGaps(chosen.guide) +
              instructionList(chosen.guide.prerequisites)
            : "") +
          (chosen.tree.prerequisites || [])
            .map(
              (p) =>
                `<div><strong>${esc(p.question)}</strong><p>${esc(p.answer)}</p>${citations(p.citations)}</div>`,
            )
            .join("");
        if (chosen.tree.nodes) {
          showNode(chosen.tree.nodes.find((n) => n.id === chosen.tree.root));
        } else {
          message("Guide", chosen.tree.instruction, chosen.tree.citations);
          choices.innerHTML =
            "<p>Documented check. Choose another symptom or check the linked manual.</p>";
        }
      };
    });
  }
  chat.querySelector("form").onsubmit = (event) => {
    event.preventDefault();
    const input = chat.querySelector(".chat-input"),
      text = input.value.trim();
    if (!text) return;
    input.value = "";
    message("You", text);
    if (!node) {
      chooseSymptom(text);
      return;
    }
    const branch = node.branches.find(
      (b) => b.condition.toLowerCase() === text.toLowerCase(),
    );
    if (branch)
      showNode(chosen.tree.nodes.find((n) => n.id === branch.next_node));
    else
      message(
        "Guide",
        "Please choose one of the displayed conditions. I will not infer a repair step from an ambiguous answer.",
      );
  };
  chat.querySelector(".chat-reset").onclick = () => {
    transcript.innerHTML = "";
    chat.querySelector(".chat-prerequisites").innerHTML = "";
    chooseSymptom();
  };
  target.querySelectorAll("[data-entry]").forEach((button) => {
    button.onclick = () => {
      const mode = button.dataset.entry;
      chat.hidden = mode !== "chat";
      browser.hidden = mode === "chat";
      if (mode === "chat") chooseSymptom();
      else {
        const input = browser.querySelector("#symptom-search");
        input.value = mode === "error" ? "error" : "";
        input.dispatchEvent(new Event("input"));
      }
    };
  });
  target.querySelectorAll("[data-guide-id]").forEach((button) => {
    button.onclick = () => {
      const guide = planned.find((g) => g.id === button.dataset.guideId);
      target.querySelector("#planned-tree").innerHTML =
        guideGaps(guide) +
        instructionList(guide.prerequisites) +
        independentChecks(guide.independent_checks) +
        (guide.troubleshooting ? treePanel(guide.troubleshooting) : "");
    };
  });
}
