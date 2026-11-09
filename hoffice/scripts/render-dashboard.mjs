#!/usr/bin/env node
import { pathToFileURL } from 'node:url';
import { renderDashboard } from './lib/dashboard.mjs';

const args = process.argv.slice(2);
const rosterIndex = args.indexOf('--roster');
const roster = rosterIndex === -1 ? undefined : args.splice(rosterIndex, 2)[1];
if (args.length !== 3 || args[0] !== '--instance' || (rosterIndex !== -1 && (!roster || roster.startsWith('--')))) {
  console.error('usage: render-dashboard.mjs --instance <instance-root> <output-directory> [--roster <file>]');
  process.exit(2);
}
try {
  const result = renderDashboard({ instance: args[1], out: args[2], roster });
  console.log(`${pathToFileURL(result.index).href}: ${result.projects} projects`);
} catch (error) { console.error(`render-dashboard: ${error.message}`); process.exitCode = 1; }
