/* Pure helpers for the composer's slash palette. No DOM, testable in Node. */

(function (global) {
  "use strict";

  /** Find a slash token immediately before the caret, anywhere in the text. */
  function findSlashToken(value, caret) {
    const text = String(value == null ? "" : value);
    const position = Math.max(0, Math.min(Number(caret) || 0, text.length));
    const before = text.slice(0, position);
    const match = before.match(/(^|\s)\/([^\s/]*)$/);
    if (!match) return null;
    return {
      start: position - match[2].length - 1,
      end: position,
      query: match[2],
    };
  }

  function replaceSlashToken(value, token, replacement) {
    if (!token) return String(value == null ? "" : value);
    const text = String(value == null ? "" : value);
    return text.slice(0, token.start) + String(replacement == null ? "" : replacement) + text.slice(token.end);
  }

  const api = { findSlashToken, replaceSlashToken };
  global.atlasSlash = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
