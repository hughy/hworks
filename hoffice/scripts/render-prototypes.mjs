#!/usr/bin/env node
// Renders the dashboard once per variant module into <out>/<id>/ and writes <out>/prototypes.json,
// the manifest scripts/prototype-gallery.py turns into a lettered gallery.
import { readdirSync, statSync, lstatSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, join, basename, relative } from 'node:path';
import { pathToFileURL } from 'node:url';
import { renderDashboard } from './lib/dashboard.mjs';

const usage = 'usage: render-prototypes.mjs --instance <instance-root> --out <directory> [--baseline] [--title <text>] <variant.mjs | directory>...';
const args = process.argv.slice(2);
const options = { baseline: false, title: 'Dashboard prototypes' };
const inputs = [];
while (args.length) {
  const arg = args.shift();
  if (arg === '--baseline') options.baseline = true;
  else if (['--instance', '--out', '--title'].includes(arg) && args.length) options[arg.slice(2)] = args.shift();
  else if (arg.startsWith('--')) { console.error(usage); process.exit(2); }
  else inputs.push(arg);
}
if (!options.instance || !options.out || (!inputs.length && !options.baseline)) { console.error(usage); process.exit(2); }

// A directory contributes its *.mjs files in name order; files starting with _ are shared helpers.
const modules = inputs.flatMap(input => statSync(input).isDirectory()
  ? readdirSync(input).filter(n => n.endsWith('.mjs') && !n.startsWith('_')).sort().map(n => join(input, n))
  : [input]);
try {
  // Rendering checks that the output stays clear of the instance; with nothing to render that check never runs.
  if (!modules.length && !options.baseline) throw new Error(`no variant modules in ${inputs.join(', ')}`);
  const out = resolve(options.out);
  const manifest = join(out, 'prototypes.json');
  // The manifest is written last, so check it before any variant renders.
  try { if (lstatSync(manifest).isSymbolicLink()) throw new Error(`output destination must not be a symlink: ${manifest}`); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  mkdirSync(out, { recursive: true });
  const entries = [];
  const render = (id, variant, meta) => {
    if (!/^[a-z0-9][a-z0-9-]*$/.test(id)) throw new Error(`variant id must be lowercase letters, digits and dashes: ${id}`);
    if (entries.some(e => e.id === id)) throw new Error(`duplicate variant id: ${id}`);
    const result = renderDashboard({ instance: options.instance, out: join(out, id), variant });
    entries.push({ id, ...meta, entry: relative(out, result.index), dir: id });
    console.log(`${id}: ${result.pages} pages`);
  };
  if (options.baseline) render('baseline', {}, { title: 'Current dashboard', baseline: true,
    approach: 'The dashboard as it renders today, for comparison.', differences: [], features: [] });
  for (const path of modules) {
    const variant = await import(pathToFileURL(resolve(path)).href);
    const meta = variant.meta ?? {};
    render(meta.id ?? basename(path, '.mjs').replace(/^\d+-/, ''), variant, {
      title: meta.title ?? basename(path, '.mjs'), approach: meta.approach ?? '',
      differences: meta.differences ?? [], features: meta.features ?? [] });
  }
  writeFileSync(manifest, JSON.stringify({ title: options.title, prototypes: entries }, null, 2) + '\n');
  console.log(`${pathToFileURL(manifest).href}: ${entries.length} prototypes`);
} catch (error) { console.error(`render-prototypes: ${error.message}`); process.exitCode = 1; }
