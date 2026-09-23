import asyncio
import time


def test_run_api_executes_on_event_loop_and_blocks_manual_control(client, monkeypatch):
    from android_control.workflows.tiktok import WORKFLOWS

    async def runner(transport, params, emit):
        await emit('test', 'Runner actually started', True)
        await asyncio.sleep(60)

    monkeypatch.setitem(WORKFLOWS, 'test.wait', {
        'title': 'test', 'description': '', 'parameters': {}, 'runner': runner,
    })
    device = client.post('/api/devices', json={
        'name': 'test', 'transport': 'adb', 'address': 'test-device',
    }).json()['device']
    response = client.post(f"/api/devices/{device['id']}/runs", json={'workflow': 'test.wait'})
    assert response.status_code == 202
    run_id = response.json()['id']
    for _ in range(50):
        run = client.get(f'/api/runs/{run_id}').json()
        if run['steps']:
            break
        time.sleep(.01)
    assert run['status'] == 'running'
    assert run['steps'][0]['detail'] == 'Runner actually started'
    manual = client.post(f"/api/devices/{device['id']}/actions/tap", json={'params': {'x': 1, 'y': 1}})
    assert manual.status_code == 409
    queued = client.post(f"/api/devices/{device['id']}/runs", json={'workflow': 'test.wait'}).json()
    assert client.post(f"/api/runs/{queued['id']}/cancel").status_code == 202
    time.sleep(.03)
    assert client.get('/api/devices').json()[0]['status'] == 'busy'
    assert client.post(f'/api/runs/{run_id}/cancel').status_code == 202
    for _ in range(50):
        if client.get(f'/api/runs/{run_id}').json()['status'] == 'cancelled':
            break
        time.sleep(.01)
    assert client.get(f'/api/runs/{run_id}').json()['status'] == 'cancelled'


def test_startup_reconciles_unfinished_runs(client):
    device = client.post('/api/devices', json={'name': 'offline'}).json()['device']
    repo = client.app.state.repository
    repo.insert_run({'id': 'interrupted', 'device_id': device['id'], 'workflow': 'tiktok.browse',
                     'status': 'running', 'params': {}, 'created_at': '2026-01-01'})
    repo.recover_interrupted_runs()
    assert repo.get_run('interrupted')['status'] == 'cancelled'
