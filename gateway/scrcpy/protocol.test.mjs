import test from 'node:test';
import assert from 'node:assert/strict';
import { decodePacket, encodePacket, mapPoint } from './protocol.mjs';

test('configuration and H264 data survive binary transport without changing PTS', () => {
    for (const packet of [
        {type: 'configuration', data: new Uint8Array([0, 0, 0, 1, 103])},
        {type: 'data', keyframe: true, pts: 2n ** 54n, data: new Uint8Array([0, 0, 1, 101])},
        {type: 'data', keyframe: false, pts: 123456n, data: new Uint8Array([0, 0, 1, 65])},
    ]) assert.deepEqual(decodePacket(encodePacket(packet)), packet);
});

test('malformed frames are rejected', () => {
    assert.throws(() => decodePacket(new Uint8Array(8)));
    assert.throws(() => decodePacket(new Uint8Array([3, 0, 0, 0, 0, 0, 0, 0, 0])));
});

test('letterboxing, rotation and captured pointers outside canvas map correctly', () => {
    const rect = {left: 10, top: 20, width: 400, height: 400};
    assert.deepEqual(mapPoint(210, 220, rect, 1080, 1920), {x: 0.5, y: 0.5});
    assert.deepEqual(mapPoint(210, 220, rect, 1920, 1080), {x: 0.5, y: 0.5});
    assert.deepEqual(mapPoint(-100, 1000, rect, 1080, 1920), {x: 0, y: 1});
});
