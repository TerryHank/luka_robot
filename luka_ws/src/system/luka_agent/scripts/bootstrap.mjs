import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const upstream = JSON.parse(await readFile(path.join(root, 'UPSTREAM.json'), 'utf8'));
const vendor = path.join(root, 'vendor');
const source = path.join(vendor, 'moss');
await mkdir(vendor, { recursive: true });
let installed = false;
try { await access(path.join(source, 'package.json')); installed = true; } catch {}
if (!installed) {
  const url = `https://codeload.github.com/D-Robotics/moss/tar.gz/${upstream.moss.commit}`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Moss source download failed: ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  if (upstream.moss.archive_sha256 && upstream.moss.archive_sha256 !== sha256) {
    throw new Error('Moss archive checksum mismatch');
  }
  const archive = path.join(vendor, 'moss-source.tgz');
  await writeFile(archive, bytes);
  await mkdir(source, { recursive: true });
  const extract = spawnSync('tar', ['-xzf', archive, '--strip-components=1', '-C', source], { stdio: 'inherit' });
  if (extract.status !== 0) throw new Error('Moss source extraction failed');
  await writeFile(path.join(vendor, 'source-receipt.json'), JSON.stringify({ url, commit: upstream.moss.commit, sha256 }, null, 2));
}
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
for (const args of [['ci', '--no-audit', '--no-fund'], ['run', 'build']]) {
  const result = spawnSync(npm, args, { cwd: source, stdio: 'inherit', shell: process.platform === 'win32' });
  if (result.status !== 0) throw new Error(`Moss build failed: npm ${args.join(' ')}`);
}
