import { ScrcpyVideoCodecId } from '@yume-chan/scrcpy';
import { WebCodecsVideoDecoder, BitmapVideoFrameRenderer } from '@yume-chan/scrcpy-decoder-webcodecs';
import { decodePacket, mapPoint } from './protocol.mjs';

export function create(deviceId, container, onStatus) {
    if (!window.isSecureContext || !WebCodecsVideoDecoder.isSupported) {
        throw new Error('Live Control ADB cần HTTPS hoặc localhost và trình duyệt hỗ trợ WebCodecs.');
    }
    const renderer = new BitmapVideoFrameRenderer();
    const canvas = renderer.canvas;
    canvas.className = 'live-control-canvas';
    container.appendChild(canvas);
    const decoder = new WebCodecsVideoDecoder({codec: ScrcpyVideoCodecId.H264, renderer});
    const writer = decoder.writable.getWriter();
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/adb/${deviceId}`);
    socket.binaryType = 'arraybuffer';
    let closed = false;
    let failed = false;
    let started = false;
    let pending = 0;
    let chain = Promise.resolve();
    const pointers = new Set();
    let lastMove = 0;

    function fail(message) {
        if (closed || failed) return;
        failed = true;
        onStatus(`Lỗi: ${message}`);
        socket.close();
    }
    function send(message) {
        if (closed || failed || socket.readyState !== WebSocket.OPEN || !started) return false;
        if (socket.bufferedAmount > 65536) {
            fail('Kết nối quá chậm. Đóng rồi mở lại Live Control.');
            return false;
        }
        socket.send(JSON.stringify(message));
        return true;
    }
    void writer.closed.catch(error => fail(error.message));
    socket.onmessage = (event) => {
        if (closed || failed) return;
        if (typeof event.data === 'string') {
            const message = JSON.parse(event.data);
            if (message.error) fail(message.error);
            return;
        }
        if (++pending > 90) {
            fail('Player không theo kịp video. Đóng rồi mở lại Live Control.');
            return;
        }
        const bytes = new Uint8Array(event.data);
        chain = chain.then(async () => {
            if (closed || failed) return;
            await writer.write(decodePacket(bytes));
        }).catch(error => fail(error.message)).finally(() => --pending);
    };
    decoder.sizeChanged(() => {
        if (closed || failed) return;
        started = true;
        onStatus('Đang điều khiển trực tiếp qua ADB');
    });
    socket.onerror = () => fail('Không kết nối được gateway. Kiểm tra đăng nhập và cấu hình ADB.');
    socket.onclose = () => {
        if (!closed && !failed) onStatus('Stream đã ngắt. Đóng rồi mở lại để kết nối.');
        dispose();
    };

    function touch(event, phase) {
        if (!decoder.width || !decoder.height) return;
        const rect = canvas.getBoundingClientRect();
        const point = mapPoint(event.clientX, event.clientY, rect, decoder.width, decoder.height);
        send({action: 'touch', phase, pointerId: event.pointerId, ...point});
    }
    canvas.onpointerdown = event => {
        event.preventDefault();
        pointers.add(event.pointerId);
        canvas.setPointerCapture(event.pointerId);
        touch(event, 0);
    };
    canvas.onpointermove = event => {
        if (!pointers.has(event.pointerId) || performance.now() - lastMove < 16) return;
        lastMove = performance.now();
        touch(event, 2);
    };
    canvas.onpointerup = event => {
        if (!pointers.delete(event.pointerId)) return;
        touch(event, 1);
    };
    canvas.onpointercancel = event => {
        if (!pointers.delete(event.pointerId)) return;
        touch(event, 3);
    };
    canvas.oncontextmenu = event => event.preventDefault();

    function dispose() {
        if (closed) return;
        closed = true;
        pointers.clear();
        socket.close();
        decoder.dispose();
        canvas.remove();
    }
    return {
        close: dispose,
        send(action, params) {
            if (action === 'type_text') return send({action: 'text', text: params.text});
            if (action === 'global_action') {
                const keyCode = {back: 4, home: 3, recents: 187}[params.action];
                return keyCode ? send({action: 'key', keyCode}) : false;
            }
            return false;
        },
    };
}
