from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class WebRichTextTests(unittest.TestCase):
    def test_render_safe_rich_text_decodes_escaped_markup(self) -> None:
        script = textwrap.dedent(
            """
            import { pathToFileURL } from 'node:url';

            const moduleUrl = pathToFileURL(`${process.cwd()}/apps/web/site/rich-text.js`).href;
            const { renderSafeRichText } = await import(moduleUrl);

            const ENTITY_MAP = {
              amp: '&',
              lt: '<',
              gt: '>',
              quot: '"',
              '#39': "'",
            };

            function decodeEntities(value) {
              return String(value ?? '').replace(/&(?:amp|lt|gt|quot|#39);/g, (match) => ENTITY_MAP[match.slice(1, -1)] || match);
            }

            function escapeText(value) {
              return String(value ?? '')
                .replaceAll('&', '&amp;')
                .replaceAll('<', '&lt;')
                .replaceAll('>', '&gt;')
                .replaceAll('"', '&quot;')
                .replaceAll("'", '&#39;');
            }

            function createFragment() {
              return {
                nodeType: 11,
                childNodes: [],
                appendChild(node) {
                  this.childNodes.push(node);
                  return node;
                },
              };
            }

            function serializeNode(node) {
              if (node.nodeType === 3) {
                return escapeText(node.textContent);
              }
              if (node.nodeType === 1) {
                const tag = node.tagName.toLowerCase();
                return `<${tag}>${node.childNodes.map(serializeNode).join('')}</${tag}>`;
              }
              return '';
            }

            function parseHtml(html, documentLike) {
              const fragment = createFragment();
              const stack = [fragment];
              const tokens = String(html ?? '').match(/<\\/?[^>]+>|[^<]+/g) || [];

              for (const token of tokens) {
                if (token.startsWith('</')) {
                  const closingTag = token.slice(2, -1).trim().toLowerCase();
                  const current = stack[stack.length - 1];
                  if (current?.tagName?.toLowerCase() === closingTag) {
                    stack.pop();
                  }
                  continue;
                }

                if (token.startsWith('<')) {
                  const match = /^<([a-zA-Z0-9-]+)/.exec(token);
                  if (!match) continue;
                  const element = documentLike.createElement(match[1]);
                  stack[stack.length - 1].appendChild(element);
                  if (!token.endsWith('/>')) {
                    stack.push(element);
                  }
                  continue;
                }

                stack[stack.length - 1].appendChild(documentLike.createTextNode(decodeEntities(token)));
              }

              return fragment;
            }

            class FakeTextNode {
              constructor(text) {
                this.nodeType = 3;
                this.textContent = text;
              }
            }

            class FakeElement {
              constructor(tagName, documentLike) {
                this.nodeType = 1;
                this.tagName = String(tagName).toUpperCase();
                this.childNodes = [];
                this._documentLike = documentLike;
                if (this.tagName === 'TEXTAREA') {
                  this.value = '';
                }
                if (this.tagName === 'TEMPLATE') {
                  this.content = createFragment();
                }
              }

              appendChild(node) {
                this.childNodes.push(node);
                return node;
              }

              get innerHTML() {
                return this.childNodes.map(serializeNode).join('');
              }

              set innerHTML(html) {
                if (this.tagName === 'TEXTAREA') {
                  this.value = decodeEntities(html);
                  return;
                }
                if (this.tagName === 'TEMPLATE') {
                  this.content = parseHtml(html, this._documentLike);
                  return;
                }
                this.childNodes = parseHtml(html, this._documentLike).childNodes;
              }
            }

            const documentLike = {
              createElement(tagName) {
                return new FakeElement(tagName, documentLike);
              },
              createTextNode(text) {
                return new FakeTextNode(text);
              },
            };

            const output = renderSafeRichText('&lt;p&gt;Build &lt;strong&gt;R&amp;amp;D&lt;/strong&gt; pipelines&lt;/p&gt;', documentLike, {
              TEXT_NODE: 3,
              ELEMENT_NODE: 1,
            });

            if (output !== '<p>Build <strong>R&amp;D</strong> pipelines</p>') {
              throw new Error(`Unexpected output: ${output}`);
            }
            """
        )

        subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
