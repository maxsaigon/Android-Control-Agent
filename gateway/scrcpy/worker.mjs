// One process per authenticated dashboard session. No public listening socket.
import { readFile } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { once } from 'node:events';
import { AdbServerClient } from '@yume-chan/adb';
import { AdbServerNodeTcpConnector } from '@yume-chan/adb-server-node-tcp';
import { AdbScrcpyClient, AdbScrcpyOptions3_3_3 } from '@yume-chan/adb-scrcpy';
import { ReadableStream } from '@yume-chan/stream-extra';
import { encodePacket } from './protocol.mjs';

let client;
let adb;
let closing = false;
async function close(code = 0) {
    if (closing) return;
    closing = true;
    const deadline = setTimeout(() => process.exit(code), 1500);
    deadline.unref();
    try { await client?.close(); await adb?.close(); }
    catch (error) { console.error(error.message); }
    process.exit(code);
}
process.on('SIGTERM', () => void close());
process.on('SIGINT', () => void close());
process.stdout.on('error', () => void close(1));

// stdout: uint32 BE length, then type byte + uint64 BE PTS + encoded bytes.
async function send(packet) {
    const payload = encodePacket(packet);
    const header = Buffer.alloc(4);
    header.writeUInt32BE(payload.length);
    const output = Buffer.concat([header, payload]);
    if (!process.stdout.write(output)) await once(process.stdout, 'drain');
}

try {
    const [serial, serverPath, host, port] = process.argv.slice(2);
    const server = new AdbServerClient(new AdbServerNodeTcpConnector({host, port: Number(port)}));
    adb = await server.createAdb({serial});
    const binary = await readFile(serverPath);
    const remotePath = '/data/local/tmp/android-control-scrcpy-3.3.3.jar';
    await AdbScrcpyClient.pushServer(adb, new ReadableStream({
        start(controller) { controller.enqueue(binary); controller.close(); },
    }), remotePath);
    client = await AdbScrcpyClient.start(adb, remotePath, new AdbScrcpyOptions3_3_3({
        audio: false, videoCodec: 'h264', maxSize: 1280, maxFps: 30,
        videoBitRate: 2_000_000, tunnelForward: true, clipboardAutosync: false,
    }));
    // Drain server output so logs cannot block streaming. Keep stdout binary-only.
    void (async () => { for await (const line of client.output) console.error(line); })()
        .catch(error => { console.error(error.message); void close(1); });
    const video = await client.videoStream;
    const control = client.controller;
    const input = createInterface({input: process.stdin});
    void (async () => {
        for await (const line of input) {
            const message = JSON.parse(line); // validated by FastAPI
            if (message.action === 'touch') {
                await control.injectTouch({
                    action: message.phase, pointerId: BigInt(message.pointerId),
                    pointerX: Math.min(video.width - 1, Math.round(message.x * video.width)),
                    pointerY: Math.min(video.height - 1, Math.round(message.y * video.height)),
                    videoWidth: video.width, videoHeight: video.height,
                    pressure: message.phase === 1 || message.phase === 3 ? 0 : 1,
                    actionButton: 0, buttons: 0,
                });
            } else if (message.action === 'key') {
                for (const action of [0, 1]) {
                    await control.injectKeyCode({action, keyCode: message.keyCode, repeat: 0, metaState: 0});
                }
            } else if (message.action === 'text') {
                // Clipboard paste supports Unicode where injectText does not.
                await control.setClipboard({sequence: 0n, paste: true, content: message.text});
            }
        }
        await close();
    })().catch(error => { console.error(error.message); void close(1); });
    for await (const packet of video.stream) await send(packet);
    await close();
} catch (error) {
    console.error(error.message);
    await close(1);
}
