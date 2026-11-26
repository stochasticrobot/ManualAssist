/* Provide small display and request helpers shared by the browser pages.

Counts, source-page links and server responses need consistent handling. Text is
escaped before being inserted into a page so manual content is displayed as text,
not executed as browser code. These helpers do not analyse manuals. */
/**
 * Find an element.
 *
 * Args:
 *   id — DOM identifier.
 * Returns:
 *   matching element or null.
 */
export function $(id) {
  return document.getElementById(id);
}

/**
 * Escape content.
 *
 * Args:
 *   value — display value.
 * Returns:
 *   safe HTML text.
 */
export function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}

/**
 * Format a count.
 *
 * Args:
 *   value — numeric count.
 * Returns:
 *   localized text or an em dash for unknown.
 */
export function num(value) {
  return value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString();
}

/**
 * Fetch JSON.
 *
 * Args:
 *   path — API path; options — fetch settings.
 * Returns:
 *   parsed response or a readable HTTP error carrying its status code.
 *   Network failures propagate without a fabricated HTTP status.
 */
export async function api(path, options = {}) {
  const r = await fetch(path, options),
    b = await r.json();
  if (!r.ok) {
    const error = new Error(
      typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail),
    );
    error.status = r.status;
    throw error;
  }
  return b;
}

/**
 * Display a transient action result.
 *
 * Args:
 *   text — message, or empty string.
 * Returns:
 *   nothing; updates status region.
 */
export function notice(text) {
  $("notice").className = text ? "notice" : "";
  $("notice").textContent = text;
}

/**
 * Render a source link.
 *
 * Args:
 *   page — physical page; id — optional evidence label.
 * Returns:
 *   escaped source-navigation button.
 */
export function sourceLink(page, id = "") {
  return /* HTML */ `<button class="source-link" data-page="${Number(page)}">
    PDF p. ${Number(page)} ${esc(id)}
  </button>`;
}

/**
 * Render count cards.
 *
 * Args:
 *   pairs — label/value pairs.
 * Returns:
 *   HTML for observed counts only.
 */
export function metrics(pairs) {
  return pairs
    .map(
      ([label, value]) =>
        /* HTML */ `<div class="metric">
          <strong>${num(value)}</strong><small>${esc(label)}</small>
        </div>`,
    )
    .join("");
}
