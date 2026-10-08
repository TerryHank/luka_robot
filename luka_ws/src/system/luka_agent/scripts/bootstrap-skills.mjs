import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, readdir, lstat, symlink, realpath, unlink } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const upstream = JSON.parse(await readFile(path.join(root, 'UPSTREAM.json'), 'utf8'));
const receipts = {};
for (const [name, spec] of Object.entries(upstream.skills)) {
  const target = path.join(root, 'vendor', name);
  const receiptFile = path.join(root, 'vendor', `${name}.receipt.json`);
  let receipt;
  try { receipt = JSON.parse(await readFile(receiptFile, 'utf8')); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (receipt && receipt.commit !== spec.commit) throw new Error(`Existing ${name} differs from pinned commit; refusing to overwrite`);
  if (receipt && spec.archive_sha256 && receipt.sha256 !== spec.archive_sha256) throw new Error(`Existing ${name} checksum differs from lock`);
  if (!receipt) {
    const url = `https://codeload.github.com/D-Robotics/${name}/tar.gz/${spec.commit}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Skills download failed: ${name} ${response.status}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    if (spec.archive_sha256 && sha256 !== spec.archive_sha256) throw new Error(`Checksum mismatch: ${name}`);
    await mkdir(target, { recursive: true });
    const archive = path.join(root, 'vendor', `${name}.tgz`);
    await writeFile(archive, bytes);
    const result = spawnSync('tar', ['-xzf', archive, '--strip-components=1', '-C', target], { stdio: 'inherit' });
    if (result.status !== 0) throw new Error(`Extraction failed: ${name}`);
    receipt = { url, commit: spec.commit, sha256 };
    await writeFile(receiptFile, JSON.stringify(receipt, null, 2));
  }
  receipts[name] = receipt;
}

const catalog = new Map();
const source = path.join(root, 'vendor', 'rdk-device-skills', 'skills');
async function add(folder, origin) {
  const text = await readFile(path.join(folder, 'SKILL.md'), 'utf8');
  const name = /^name:\s*["']?([a-z0-9_-]+)/m.exec(text)?.[1];
  if (!name) throw new Error(`Invalid skill metadata: ${folder}`);
  if (catalog.has(name)) throw new Error(`Duplicate skill name: ${name}`);
  catalog.set(name, { name, source: folder, origin });
}
for (const entry of await readdir(source, { withFileTypes: true })) {
  if (entry.isDirectory()) await add(path.join(source, entry.name), 'rdk-device-skills');
}
// The hub is an index: do not load its mirrored copies of the device pack.
for (const name of ['rdk-skill-finder', 'rdk-pack-installer']) {
  await add(path.join(root, 'vendor', 'rdk-skills', 'skills', name), 'rdk-skills');
}
const runtime = process.env.LUKA_AGENT_DEV_ROOT ?? '/home/sunrise/luka_data/runtime/agent-dev';
if (process.platform !== 'linux') throw new Error('Install the developer skill links on the Linux target');
const destination = path.join(runtime, '.moss', 'skills');
await mkdir(destination, { recursive: true, mode: 0o700 });
for (const item of catalog.values()) {
  const container = path.join(destination, item.name);
  try {
    const exists = await lstat(container);
    if (exists.isSymbolicLink()) {
      if (await realpath(container) !== await realpath(item.source)) throw new Error(`Existing skill conflicts: ${container}`);
      // Moss scans real directories; replace only our exact source link.
      await unlink(container);
    } else if (!exists.isDirectory()) throw new Error(`Existing skill conflicts: ${container}`);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  await mkdir(container, { recursive: true });
  for (const entry of await readdir(item.source, { withFileTypes: true })) {
    const target = path.join(item.source, entry.name);
    const link = path.join(container, entry.name);
    try {
      const exists = await lstat(link);
      if (!exists.isSymbolicLink() || await realpath(link) !== await realpath(target)) throw new Error(`Existing skill member conflicts: ${link}`);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      await symlink(target, link, entry.isDirectory() ? 'dir' : 'file');
    }
  }
}
const report = { developer_only: true, entries: [...catalog.values()], upstream: receipts };
await writeFile(path.join(runtime, 'skill-catalog.json'), JSON.stringify(report, null, 2), { mode: 0o600 });
console.log(JSON.stringify({ skill_count: catalog.size, duplicate_names: 0, developer_root: runtime, receipts }));
