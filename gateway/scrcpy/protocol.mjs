// WebSocket payload: kind (1 byte), microsecond PTS (8 bytes BE), encoded data.
export function encodePacket(packet) {
    const bytes = new Uint8Array(9 + packet.data.length);
    bytes[0] = packet.type === 'configuration' ? 0 : packet.keyframe ? 1 : 2;
    new DataView(bytes.buffer).setBigUint64(1, packet.pts ?? 0n);
    bytes.set(packet.data, 9);
    return bytes;
}

export function decodePacket(bytes) {
    if (bytes.byteLength < 9 || bytes[0] > 2) throw new Error('Invalid video packet');
    if (bytes[0] === 0) return {type: 'configuration', data: bytes.subarray(9)};
    return {
        type: 'data', keyframe: bytes[0] === 1,
        pts: new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getBigUint64(1),
        data: bytes.subarray(9),
    };
}

export function mapPoint(clientX, clientY, rect, width, height) {
    const scale = Math.min(rect.width / width, rect.height / height);
    const contentWidth = width * scale;
    const contentHeight = height * scale;
    return {
        x: Math.max(0, Math.min(1, (clientX - rect.left - (rect.width - contentWidth) / 2) / contentWidth)),
        y: Math.max(0, Math.min(1, (clientY - rect.top - (rect.height - contentHeight) / 2) / contentHeight)),
    };
}
