import { build } from 'esbuild';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

await build({
    entryPoints: ['player.js'], bundle: true, format: 'iife', globalName: 'AdbPlayer',
    outfile: '../../app/static/scrcpy-player.js',
    banner: {js: '/*! Third-party licenses: /static/scrcpy-licenses.txt */'},
});
const notices = [];
async function visit(directory) {
    for (const item of await readdir(directory, {withFileTypes: true})) {
        const path = join(directory, item.name);
        if (item.isDirectory()) await visit(path);
        else if (/LICENSE|COPYING/i.test(item.name)) {
            notices.push(`${path}\n\n${await readFile(path, 'utf8')}`);
        }
    }
}
await visit('node_modules');
await writeFile('../../app/static/scrcpy-licenses.txt', notices.join('\n\n---\n\n'));
