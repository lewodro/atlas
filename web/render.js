/* Tiny offline markdown + maths renderer. No CDN, no dependency. */

(function (global) {
  "use strict";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  const SUP = { "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵",
    "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻", "=": "⁼",
    "(": "⁽", ")": "⁾", "n": "ⁿ" };
  const SUB = { "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅",
    "6": "₆", "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋", "=": "₌" };

  function superscript(text) {
    return [...text].map((c) => SUP[c] || `<sup>${c}</sup>`).join("");
  }
  function subscript(text) {
    return [...text].map((c) => SUB[c] || `<sub>${c}</sub>`).join("");
  }

  /* Convert common LaTeX into readable text/HTML. Input is already escaped. */
  function latexToText(tex) {
    let s = String(tex || "").trim();
    const named = {
      alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", theta: "θ",
      lambda: "λ", mu: "μ", pi: "π", sigma: "σ", phi: "φ", omega: "ω",
      Delta: "Δ", Sigma: "Σ", Omega: "Ω",
    };
    s = s.replace(/\\([A-Za-z]+)/g, (match, name) => {
      if (name in named) return named[name];
      const commands = {
        times: "×", cdot: "·", div: "÷", pm: "±", mp: "∓", leq: "≤", geq: "≥",
        neq: "≠", approx: "≈", sim: "∼", propto: "∝", to: "→", infty: "∞",
        sum: "∑", int: "∫", partial: "∂", sqrt: "√", perp: "⊥", angle: "∠",
        therefor: "∴", because: "∵", in: "∈", notin: "∉", subset: "⊂",
        cup: "∪", cap: "∩", emptyset: "∅", quad: " ", qquad: "  ",
      };
      if (name in commands) return commands[name];
      if (name === "frac") return match;
      if (name === "left" || name === "right" || name === "!" || name === ",") return "";
      return name;
    });
    s = s.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, "($1)/($2)");
    s = s.replace(/\\sqrt\{([^{}]*)\}/g, "√($1)");
    s = s.replace(/\^\{([^{}]+)\}/g, (m, x) => superscript(x));
    s = s.replace(/\^([A-Za-z0-9+=-])/g, (m, x) => superscript(x));
    s = s.replace(/_\{([^{}]+)\}/g, (m, x) => subscript(x));
    s = s.replace(/_([A-Za-z0-9+=-])/g, (m, x) => subscript(x));
    s = s.replace(/[{}]/g, "").replace(/\\/g, "");
    return s;
  }

  function safeLink(label, url) {
    const clean = String(url || "").trim();
    if (!/^https?:\/\//i.test(clean)) return label;
    return `<a href="${escapeHtml(clean)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  }

  function renderInline(raw) {
    const codes = [];
    let s = escapeHtml(raw);

    s = s.replace(/`([^`]+)`/g, (m, code) => {
      codes.push(code);
      return `\u0000C${codes.length - 1}\u0000`;
    });

    s = s.replace(/!\[[^\]]*\]\([^)]*\)/g, ""); // no fake/broken images
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, label, url) => safeLink(label, url));
    s = s.replace(/\\\((.+?)\\\)/g, (m, tex) =>
      `<span class="math">${latexToText(tex)}</span>`);
    s = s.replace(/\$\$([^$]+)\$\$/g, (m, tex) =>
      `<span class="math math-block-inline">${latexToText(tex)}</span>`);
    s = s.replace(/\$([^$\n]+)\$/g, (m, tex) =>
      `<span class="math">${latexToText(tex)}</span>`);

    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    s = s.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");

    s = s.replace(/\u0000C(\d+)\u0000/g, (m, i) =>
      `<code>${escapeHtml(codes[Number(i)] || "")}</code>`);
    return s;
  }

  function renderBlock(text) {
    const lines = String(text || "").split("\n");
    const out = [];
    let list = null;

    function closeList() {
      if (list) {
        out.push(`<${list.tag}>${list.items.map((i) => `<li>${renderInline(i)}</li>`).join("")}</${list.tag}>`);
        list = null;
      }
    }

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) { closeList(); continue; }

      const display = trimmed.match(/^\\\[(.+)\\\]$/) || trimmed.match(/^\$\$(.+)\$\$$/);
      if (display) { closeList(); out.push(`<div class="math-block">${latexToText(display[1])}</div>`); continue; }

      const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
      if (heading) { closeList(); const level = heading[1].length;
        out.push(`<h${level}>${renderInline(heading[2])}</h${level}>`); continue; }

      const bullet = trimmed.match(/^[-*]\s+(.+)$/);
      const numbered = trimmed.match(/^\d+[.)]\s+(.+)$/);
      if (bullet || numbered) {
        const tag = numbered ? "ol" : "ul";
        if (!list || list.tag !== tag) { closeList(); list = { tag, items: [] }; }
        list.items.push((bullet || numbered)[1]);
        continue;
      }

      if (/^>\s?/.test(trimmed)) { closeList(); out.push(`<blockquote>${renderInline(trimmed.replace(/^>\s?/, ""))}</blockquote>`); continue; }

      closeList();
      out.push(`<p>${renderInline(trimmed)}</p>`);
    }
    closeList();
    return out.join("");
  }

  function renderMarkdown(text) {
    const chunks = String(text || "").split(/```/);
    return chunks.map((part, index) => {
      if (index % 2) {
        const body = part.replace(/^[a-z]+\n/, "").replace(/^\n/, "");
        return `<pre><code>${escapeHtml(body)}</code></pre>`;
      }
      return renderBlock(part);
    }).join("");
  }

  const api = { escapeHtml, latexToText, renderInline, renderMarkdown };
  global.renderMarkdown = renderMarkdown;
  global.atlasRender = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
