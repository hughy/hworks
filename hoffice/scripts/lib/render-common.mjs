import { realpathSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, resolve, relative } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseDocument, isMap, isScalar } from 'yaml';

export async function loadMarked() {
  const { marked } = process.env.MARKED_PATH
    ? await import(pathToFileURL(resolve(process.env.MARKED_PATH)).href)
    : await import('marked');
  marked.use({ gfm: true });
  return marked;
}

export function repoInfo(cwd = process.cwd()) {
  const sh = (...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  const root = sh('rev-parse', '--show-toplevel');
  const webBase = sh('remote', 'get-url', 'origin')
    .replace(/^[^@]+@([^:]+):/, 'https://$1/')
    .replace(/^ssh:\/\/[^@]+@([^/]+)\//, 'https://$1/')
    .replace(/\.git$/, '');
  let branch = 'main';
  try {
    branch = sh('symbolic-ref', '--short', 'refs/remotes/origin/HEAD').replace(/^origin\//, '');
  } catch {
    // Instances without a remote HEAD use the launchers' default base.
  }
  return { root, webBase, blobBase: `${webBase}/blob/${branch}/`, treeBase: `${webBase}/tree/${branch}/` };
}

export function parseFrontmatter(text, { legacyScalars = false } = {}) {
  const m = text.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!m) throw new Error('missing frontmatter');
  // Published documents allow unquoted scoped authority values containing ': '.
  if (legacyScalars) {
    const fm = {};
    for (const line of m[1].split('\n')) {
      if (!/^[A-Za-z_][\w-]*:/.test(line)) continue;
      const i = line.indexOf(':');
      const rawValue = line.slice(i + 1).trim();
      const value = (rawValue.startsWith('[') ? rawValue : rawValue.replace(/\s+#.*$/, '')).trim().replace(/^"|"$/g, '');
      fm[line.slice(0, i).trim()] = value;
    }
    return { fm, body: m[2] };
  }
  const doc = parseDocument(m[1]);
  if (doc.errors.length) throw new Error(`invalid frontmatter: ${doc.errors[0].message}`);
  if (doc.contents && !isMap(doc.contents)) throw new Error('frontmatter must be a YAML map');
  const fm = doc.toJS() ?? {};
  // Renderer callers expect top-level scalars (including booleans and dates) as text.
  for (const { key, value } of doc.contents?.items ?? []) {
    if (isScalar(value)) fm[key.value] = typeof value.value === 'string' ? value.value : (value.source ?? '');
  }
  return { fm, body: m[2] };
}

// Preserve anchors while resolving source-relative paths against the instance remote.
export function rewriteRelativeLinks(markdown, srcFile, { root, blobBase }) {
  const srcDir = realpathSync(dirname(resolve(srcFile)));
  const repoRoot = realpathSync(root);
  return markdown.replace(/\]\((\.\.?\/[^)#\s]+)/g, (_, rel) => `](${blobBase}${relative(repoRoot, resolve(srcDir, rel))}`);
}

export const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

export const css = `
    :root { color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #111; background: #faf9f6; }
    body { max-width: 1040px; margin: 0 auto; padding: 48px 54px 100px; font-size: 16px; line-height: 1.45; }
    h1 { margin: 22px 0 8px; font-size: 32px; font-weight: 500; line-height: 1.2; }
    h2 { margin: 38px 0 10px; padding-top: 8px; font-size: 27px; font-weight: 500; }
    h3 { margin: 25px 0 8px; font-size: 22px; font-weight: 500; color: #555; }
    p { margin: 9px 0; }
    ul, ol { margin-top: 8px; }
    a { color: #315c85; }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.92em; }
    pre { padding: 12px 14px; border-radius: 8px; background: #f3f4f5; overflow-x: auto; }
    .muted, .meta { color: #717886; }
    .meta { margin: 0 0 24px; font-size: 14px; }
    .chip { display: inline-block; padding: 2px 10px; border-radius: 8px; background: #eef0f3; white-space: nowrap; font-size: 14px; }
    .chip.base { background: #315c85; color: #fff; }
    table { width: 100%; border-collapse: collapse; margin: 14px 0 24px; }
    th, td { border: 1px solid #aaa; padding: 9px 10px; text-align: left; vertical-align: top; }
    th { font-weight: 700; background: #eef0f3; }

    .fig { margin: 18px 0 26px; padding: 0; }
    .fig figcaption { margin-top: 8px; font-size: 14px; color: #5b616e; }
    .flow { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
    .stack { display: flex; flex-direction: column; gap: 6px; }
    .stack > .flow { align-items: center; }
    .node { flex: 1 1 130px; min-width: 110px; padding: 8px 10px; border: 1px solid #b1b7c3; border-radius: 6px; background: #fff; font-size: 14px; line-height: 1.3; }
    .node b { font-weight: 700; }
    .node small { display: block; margin-top: 2px; font-size: 12px; color: #5b616e; }
    .node.base { background: #315c85; border-color: #315c85; color: #fff; }
    .node.base small { color: #dee1e7; }
    .node.ext { background: #eef0f3; }
    .node.chain { border-style: dashed; }
    .stack > .node { flex: 0 0 auto; }
    .label { flex: 0 0 84px; min-width: 0; font-size: 13px; color: #5b616e; text-transform: uppercase; letter-spacing: 0.04em; }
    .arrow { flex: 0 0 auto; padding: 0 2px; color: #717886; font-size: 18px; line-height: 1; }
    .lane { margin: 8px 0; padding: 8px 0 8px 12px; border-left: 3px solid #dee1e7; }
    .lane-title { margin-bottom: 6px; font-size: 12px; color: #717886; text-transform: uppercase; letter-spacing: 0.06em; }
    .between { margin: 2px 0 2px 15px; font-size: 13px; color: #5b616e; }
    .legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 8px; font-size: 12px; color: #5b616e; }
    .legend span::before { content: ""; display: inline-block; width: 12px; height: 12px; margin-right: 5px; vertical-align: -2px; border: 1px solid #b1b7c3; border-radius: 3px; background: #fff; }
    .legend .base::before { background: #315c85; border-color: #315c85; }
    .legend .ext::before { background: #eef0f3; }
    .legend .chain::before { border-style: dashed; }
    .bar { display: flex; width: 100%; overflow: hidden; border: 1px solid #b1b7c3; border-radius: 6px; }
    .seg { flex: 1 1 0; padding: 8px 6px; border-right: 1px solid #b1b7c3; font-size: 13px; line-height: 1.3; }
    .seg:last-child { border-right: 0; }
    .seg.out { flex: 3 1 0; }
    .seg.base { background: #315c85; color: #fff; }
    .seg small { display: block; margin-top: 2px; font-size: 12px; color: #5b616e; }
    .seg.base small { color: #dee1e7; }
    .timeline { list-style: none; margin: 4px 0 0; padding: 0 0 0 18px; border-left: 2px solid #dee1e7; }
    .timeline li { position: relative; margin: 0 0 10px; padding-left: 12px; font-size: 14px; line-height: 1.35; }
    .timeline li::before { content: ""; position: absolute; left: -25px; top: 5px; width: 9px; height: 9px; border-radius: 50%; border: 2px solid #717886; background: #fff; }
    .timeline li.base::before { border-color: #315c85; background: #315c85; }
    .timeline time { display: block; font-size: 12px; color: #5b616e; }
    @media (max-width: 700px) {
      body { padding: 28px 18px 64px; }
      table { display: block; overflow-x: auto; }
      .label { flex-basis: 100%; }
      .bar { flex-direction: column; }
      .seg { border-right: 0; border-bottom: 1px solid #b1b7c3; }
      .seg:last-child { border-bottom: 0; }
    }
`;

export function page({ title, meta, body, extraCss = '' }) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>${css}${extraCss}</style>
</head>
<body>
<h1>${esc(title)}</h1>
<p class="meta">${meta}</p>
${body}
</body>
</html>
`;
}
