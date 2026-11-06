#!/usr/bin/env node
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { renderDashboard } from './lib/dashboard.mjs';

const usage = 'usage: render-dashboard.mjs --instance <instance-root> [--variant <module.mjs>] <output-directory>';
const args = process.argv.slice(2);
const options = {};
while (args[0]?.startsWith('--') && args.length > 1) {
  const [flag, value] = args.splice(0, 2);
  if (!['--instance', '--variant'].includes(flag) || flag.slice(2) in options) { console.error(usage); process.exit(2); }
  options[flag.slice(2)] = value;
}
if (args.length !== 1 || !options.instance) {
  console.error(usage);
  process.exit(2);
}
try {
  const variant = options.variant ? await import(pathToFileURL(resolve(options.variant)).href) : {};
  const result = renderDashboard({ instance: options.instance, out: args[0], variant });
  console.log(`${pathToFileURL(result.index).href}: ${result.projects} projects, ${result.sourcePages} source pages`);
} catch (error) { console.error(`render-dashboard: ${error.message}`); process.exitCode = 1; }
