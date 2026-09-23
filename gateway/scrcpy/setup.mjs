import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

const name = 'scrcpy-server-v3.3.3';
const expected = '7e70323ba7f259649dd4acce97ac4fefbae8102b2c6d91e2e7be613fd5354be0';
const target = new URL(`./vendor/${name}`, import.meta.url);
let data;
try { data = await readFile(target); } catch (error) {
    if (error.code !== 'ENOENT') throw error;
}
if (!data) {
    const response = await fetch(`https://github.com/Genymobile/scrcpy/releases/download/v3.3.3/${name}`, {
        signal: AbortSignal.timeout(60000),
    });
    if (!response.ok) throw new Error(`Download failed: ${response.status}`);
    data = Buffer.from(await response.arrayBuffer());
}
if (createHash('sha256').update(data).digest('hex') !== expected) {
    throw new Error('scrcpy-server checksum mismatch');
}
await mkdir(new URL('./vendor/', import.meta.url), {recursive: true});
await writeFile(target, data);
console.log(`Verified ${name}`);
