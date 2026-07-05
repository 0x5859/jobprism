function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function decodeHtmlEntities(value, documentLike = document) {
  const text = String(value ?? "");
  const decoder = documentLike.createElement("textarea");

  let next = text;
  for (;;) {
    decoder.innerHTML = next;
    const current = decoder.value;
    if (current === next) break;
    next = current;
  }

  return next;
}

export function renderSafeRichText(value, documentLike = document, nodeCtor = Node) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";

  const looksLikeMarkup = /&lt;\/?[a-z][^&]*&gt;|<\/?[a-z][^>]*>/i.test(raw);
  if (!looksLikeMarkup) return escapeHtml(raw);

  const allowedTags = new Set(["p", "br", "strong", "em", "b", "i", "ul", "ol", "li", "code", "pre", "blockquote"]);
  const blockedTags = new Set(["script", "style", "template", "iframe", "object", "embed", "svg", "math", "noscript"]);

  const template = documentLike.createElement("template");
  template.innerHTML = decodeHtmlEntities(raw, documentLike);
  const wrapper = documentLike.createElement("div");

  const appendSanitized = (source, target) => {
    for (const node of source.childNodes) {
      if (node.nodeType === nodeCtor.TEXT_NODE) {
        target.appendChild(documentLike.createTextNode(node.textContent || ""));
        continue;
      }

      if (node.nodeType !== nodeCtor.ELEMENT_NODE) continue;

      const tag = node.tagName.toLowerCase();
      if (blockedTags.has(tag)) continue;

      if (!allowedTags.has(tag)) {
        appendSanitized(node, target);
        continue;
      }

      const el = documentLike.createElement(tag);
      appendSanitized(node, el);
      target.appendChild(el);
    }
  };

  appendSanitized(template.content, wrapper);
  return wrapper.innerHTML || escapeHtml(raw);
}
