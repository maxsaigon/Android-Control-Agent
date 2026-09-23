"""Offline browser regressions; no server or Android device required."""
from pathlib import Path
import re
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request):
            path = request.request.url.split('http://dashboard.test', 1)[-1].split('?', 1)[0]
            if path == '/':
                html = (ROOT / 'app/static/index.html').read_text()
                html = re.sub(r'<script[^>]*src="[^"]*"[^>]*></script>', '', html)
                request.fulfill(content_type='text/html', body=html)
            elif path == '/runtime.js':
                request.fulfill(content_type='text/javascript', body=(ROOT / 'app/static/dashboard-runtime.js').read_text())
            else:
                request.fulfill(status=200, body='')

        page.route('**/*', route)
        page.goto('http://dashboard.test/')
        script = (ROOT / 'app/static/app.js').read_text()
        page.add_script_tag(content=script)
        page.evaluate('''async () => {
            dashboardRuntime = await import('/runtime.js');
            devices = [{id: 1, name: '<img src=x onerror="window.injected=true">',
                ip_address: 'cloud', adb_port: 0, status: 'online', device_model: 'test'}];
            renderDevices();
            window.firstCard = document.getElementById('dev-1');
            renderDevices();
            if (window.firstCard !== document.getElementById('dev-1')) throw Error('Unchanged card replaced');
            if (document.querySelector('#dev-1 img')) throw Error('Device name interpreted as HTML');
            window.firstCard.classList.add('selected');
            devices[0].status = 'busy';
            renderDevices();
            if (!document.getElementById('dev-1').classList.contains('selected')) throw Error('Selection lost');
            const timerCallbacks = [];
            window.setInterval = callback => { timerCallbacks.push(callback); return 1; };
            let hidden = false;
            Object.defineProperty(document, 'hidden', {get: () => hidden});
            let calls = 0, finish;
            dashboardRuntime.pollVisible(() => { calls++; return new Promise(resolve => finish=resolve); }, 10);
            timerCallbacks[0](); timerCallbacks[0]();
            if (calls !== 1) throw Error('Polling overlaps');
            finish(); await Promise.resolve(); await Promise.resolve();
            hidden = true; timerCallbacks[0]();
            if (calls !== 1) throw Error('Hidden tab polled');
        }''')
        assert not errors, errors
        page.close()
        page = browser.new_page()
        page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=re.sub(
            r'<script[^>]*src="[^"]*"[^>]*></script>', '',
            (ROOT / 'refactor/src/android_control/static/index.html').read_text())))
        page.goto('http://dashboard.test/')
        script = (ROOT / 'refactor/src/android_control/static/app.js').read_text().replace('\ninit();', '')
        page.add_script_tag(content=script)
        page.evaluate('''async () => {
            state.devices = [1,2].map(id => ({id, name: String(id), transport:'cloud',status:'online'}));
            let respond;
            api = () => new Promise(resolve => respond = resolve);
            selectDevice(1);
            const pending = refreshScreen();
            selectDevice(2);
            respond({result:{data:'old-device-frame',format:'png'}});
            await pending;
            if (!document.getElementById('deviceScreen').hidden) throw Error('Old device frame displayed');
        }''')
        browser.close()
    print('PASS: stable cards, escaped device names, selection, non-overlapping polling, hidden tabs, stale screenshots')


if __name__ == '__main__':
    main()
