#!/usr/bin/env node
import { dirname, resolve } from 'node:path';
import { readFileSync, writeFileSync } from 'node:fs';
import { loadMarked, repoInfo, parseFrontmatter, rewriteRelativeLinks, esc, page } from './lib/render-common.mjs';

const [src, out] = process.argv.slice(2);
if (!src || !out) {
  console.error('usage: render-published.mjs <source.md> <out.html>');
  process.exit(2);
}

const repo = repoInfo(dirname(resolve(src)));
const { fm, body: raw } = parseFrontmatter(readFileSync(src, 'utf8'), { legacyScalars: true });
const body = rewriteRelativeLinks(raw.replace(/^# .*\n/m, ''), src, repo);
const marked = await loadMarked();

const html = page({
  title: fm.title,
  meta: `Audience: ${esc(fm.audience)}. Authority: ${esc(fm.authority)}.`,
  body: marked.parse(body),
});
writeFileSync(out, html);
console.log(`${out}: ${html.length} bytes, ${(html.match(/<h2>/g) || []).length} h2, ${(html.match(/<figure/g) || []).length} figures, ${(html.match(/<table>/g) || []).length} tables`);
