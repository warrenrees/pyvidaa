"""Offline regression tests. Only the loopback test opens a local TCP socket."""
from __future__ import annotations
import ast
import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import logging
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import paho.mqtt.client as mqtt
import pyvidaa.async_client as ac
from pyvidaa.client import VidaaTV, AppListTimeoutError, AppNotFoundError
from pyvidaa.config.storage import TokenStorage
from pyvidaa.topics import *

def wait(event):
    if not event.wait(3):
        raise AssertionError('Test barrier timed out')


def make_tv():
    # Real constructor and real Paho; disable discovery, persistence and TLS.
    tv = VidaaTV('tv.invalid', use_ssl=False, enable_persistence=False,
                 auto_detect_protocol=False, username='test-only', password='test-only')
    tv._connected = True
    return tv


def deliver(tv, topic, payload):
    message = mqtt.MQTTMessage(topic=get_topic(topic, tv.client_id).encode())
    message.payload = json.dumps(payload).encode()
    # Exercise Paho's actual dispatch, including its filtered-callback behavior.
    tv._client._handle_on_message(message)


def published():
    return SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS)


class LifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_disconnect_keeps_client_owned(self):
        tv = ac.AsyncVidaaTV('tv.invalid')
        client = SimpleNamespace(disconnect=lambda: (_ for _ in ()).throw(OSError('test-only')))
        tv._client = client
        with self.assertRaises(OSError): await tv.async_reset()
        self.assertIs(tv._client, client)
        client.disconnect = lambda: None
        await tv.async_close()

    async def test_single_constructor_for_parallel_connect_and_command(self):
        entered, release = threading.Event(), threading.Event()
        created = []
        class Client:
            def __init__(self, **kwargs):
                created.append(self)
                self.is_connected = False
                entered.set()
                wait(release)
            def connect(self, **kwargs):
                self.is_connected = True
                return True
            def send_key(self, *args, **kwargs):
                return self.is_connected
            def disconnect(self):
                self.is_connected = False
        with patch.object(ac, 'VidaaTV', Client), ThreadPoolExecutor(4) as executor:
            tv = ac.AsyncVidaaTV('tv.invalid', executor=executor)
            connect = asyncio.create_task(tv.async_connect())
            await asyncio.to_thread(wait, entered)
            command = asyncio.create_task(tv.async_send_key('KEY_HOME'))
            await asyncio.sleep(0)
            release.set()
            self.assertEqual(await asyncio.gather(connect, command), [True, True])
            await tv.async_close()
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].is_connected)

    async def check_close_during_connect(self, cancel_connect=False, cancel_close=False):
        entered, release = threading.Event(), threading.Event()
        tv_sync = make_tv()
        running = False
        def connect(*args, **kwargs):
            entered.set()
            wait(release)
        def loop_start():
            nonlocal running
            running = True
            tv_sync._connected = True
        def stop():
            nonlocal running
            running = False
        with patch.object(tv_sync._client, 'connect', connect), \
             patch.object(tv_sync._client, 'loop_start', loop_start), \
             patch.object(tv_sync._client, 'loop_stop', stop), \
             patch.object(tv_sync._client, 'disconnect', stop), ThreadPoolExecutor(4) as executor:
            tv = ac.AsyncVidaaTV('tv.invalid', executor=executor)
            tv._client = tv_sync
            connecting = asyncio.create_task(tv.async_connect())
            await asyncio.to_thread(wait, entered)
            if cancel_connect:
                connecting.cancel()
                await asyncio.sleep(0)
                connecting.cancel()  # repeated cancellation must still drain
            closing = asyncio.create_task(tv.async_close())
            await asyncio.sleep(0)
            if cancel_close:
                closing.cancel()
                await asyncio.sleep(0)
            queued = asyncio.create_task(tv.async_send_key('KEY_HOME'))
            release.set()
            values = await asyncio.gather(connecting, closing, queued, return_exceptions=True)
            self.assertIsInstance(values[2], RuntimeError)
            self.assertFalse(running)
            self.assertFalse(tv.is_connected)
            if cancel_connect:
                self.assertIsInstance(values[0], asyncio.CancelledError)
            if cancel_close:
                self.assertIsInstance(values[1], asyncio.CancelledError)
            await tv.async_close()  # idempotent
            with self.assertRaises(RuntimeError):
                await tv.async_connect()

    async def test_close_waits_for_pending_connect(self):
        await self.check_close_during_connect()

    async def test_cancelled_connect_is_drained_before_close(self):
        await self.check_close_during_connect(cancel_connect=True)

    async def test_cancelled_close_still_finishes_cleanup(self):
        await self.check_close_during_connect(cancel_close=True)

    async def test_reset_rebuilds_only_after_previous_operation(self):
        events = []
        class Client:
            def __init__(self, **kwargs): events.append('new')
            def connect(self, **kwargs): events.append('connect'); return True
            def disconnect(self): events.append('disconnect')
        with patch.object(ac, 'VidaaTV', Client), ThreadPoolExecutor(4) as executor:
            tv = ac.AsyncVidaaTV('tv.invalid', executor=executor)
            await tv.async_connect()
            await tv.async_reset()
            await tv.async_connect()
            await tv.async_close()
        self.assertEqual(events, ['new', 'connect', 'disconnect', 'new', 'connect', 'disconnect'])

    async def test_waiter_cancellation_does_not_cancel_another_request(self):
        entered, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(4) as executor:
            tv = ac.AsyncVidaaTV('tv.invalid', executor=executor)
            active = asyncio.create_task(tv._run_in_executor(lambda: (entered.set(), wait(release))))
            await asyncio.to_thread(wait, entered)
            never_called = []
            waiter = asyncio.create_task(tv._run_in_executor(lambda: never_called.append(True)))
            await asyncio.sleep(0)
            waiter.cancel()
            release.set()
            results = await asyncio.gather(active, waiter, return_exceptions=True)
            await tv.async_close()
        self.assertEqual(never_called, [])
        self.assertIsInstance(results[1], asyncio.CancelledError)


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.tv = make_tv()

    def test_concurrent_launch_and_app_list_share_real_paho_dispatch(self):
        entered, release = threading.Event(), threading.Event()
        requests = []
        apps = [{'name': 'Кинопоиск', 'appId': 'fake-app', 'url': 'test-only'}]
        def publish(topic, payload):
            requests.append(topic)
            if topic == get_topic(TOPIC_GET_APPS, self.tv.client_id):
                entered.set()
                wait(release)
                deliver(self.tv, TOPIC_APPS_RESPONSE, apps)
            return published()
        with patch.object(self.tv._client, 'publish', publish), ThreadPoolExecutor(2) as executor:
            launch = executor.submit(self.tv.launch_app, 'Кинопоиск')
            wait(entered)
            listing = executor.submit(self.tv.get_apps)
            release.set()
            self.assertTrue(launch.result(3))
            self.assertEqual(listing.result(3), apps)
        self.assertEqual(requests.count(get_topic(TOPIC_GET_APPS, self.tv.client_id)), 2)
        self.assertIn(get_topic(TOPIC_LAUNCH_APP, self.tv.client_id), requests)
        self.assertTrue(self.tv.is_connected)

    def test_device_info_ignores_unrelated_volume_and_waits_for_correct_topic(self):
        expected = {'model_name': 'Test TV'}
        def publish(topic, payload):
            deliver(self.tv, TOPIC_VOLUME_RESPONSE, {'volume_type': 0, 'volume_value': 12})
            self.assertFalse(self.tv._response_event.is_set())
            deliver(self.tv, TOPIC_DEVICE_INFO_RESPONSE, expected)
            return published()
        with patch.object(self.tv._client, 'publish', publish):
            self.assertEqual(self.tv.get_device_info(timeout=.1), expected)
            self.assertEqual(self.tv.cached_volume, 12)

    def test_timeout_cleans_waiter_and_late_unrelated_response_is_ignored(self):
        with patch.object(self.tv._client, 'publish', return_value=published()):
            self.assertIsNone(self.tv.get_device_info(timeout=.01))
        deliver(self.tv, TOPIC_DEVICE_INFO_RESPONSE, {'model_name': 'Late'})
        self.assertEqual(self.tv._expected_response_topics, set())
        self.assertIsNone(self.tv._last_response)

    def test_volume_broadcast_and_source_list_still_work(self):
        def publish(topic, payload):
            if topic.endswith('/getvolume'):
                deliver(self.tv, '/remoteapp/mobile/broadcast/platform_service/actions/volumechange', {'volume_value': 14})
            else:
                deliver(self.tv, TOPIC_SOURCES_RESPONSE, [{'sourceid': '3', 'sourcename': 'HDMI1'}])
            return published()
        with patch.object(self.tv._client, 'publish', publish):
            self.assertEqual(self.tv.get_volume(timeout=.1), 14)
            self.assertEqual(self.tv.get_sources(timeout=.1)[0]['sourceid'], '3')

    def test_missing_app_and_timeout_are_distinct_errors(self):
        with patch.object(self.tv, 'get_apps', return_value=[]):
            with self.assertRaises(AppNotFoundError): self.tv.launch_app('Missing')
        with patch.object(self.tv, 'get_apps', return_value=None):
            with self.assertRaises(AppListTimeoutError): self.tv.launch_app('Missing')
            self.tv._connected = False
            self.assertFalse(self.tv.launch_app('Missing'))

class TokenTests(unittest.TestCase):
    def test_optional_refresh_token_has_zero_expiry_without_crashing(self):
        storage = TokenStorage.__new__(TokenStorage)
        memory = {}
        storage._load_all = lambda: copy.deepcopy(memory)
        storage._save_all = lambda data: memory.update(copy.deepcopy(data))
        storage.save_token('tv.invalid:36669', 'tv.invalid', access_token='FAKE_ACCESS', refresh_token=None, auth_method='modern')
        status = storage.get_token_status(host='tv.invalid')
        self.assertTrue(status['access_valid'])
        self.assertFalse(status['refresh_valid'])
        self.assertEqual(status['refresh_expires_in'], 0)

    def test_refresh_updates_actual_paho_password_and_rotated_token(self):
        tv = make_tv()
        tv._refresh_token = 'FAKE_OLD_REFRESH'
        def publish(topic, payload):
            deliver(tv, TOPIC_TOKEN_RESPONSE, {'accesstoken': 'FAKE_NEW_ACCESS', 'refreshtoken': 'FAKE_NEW_REFRESH'})
            return published()
        with patch.object(tv._client, 'publish', publish):
            self.assertTrue(tv.refresh_token(timeout=.1))
        self.assertEqual(tv._client._password, b'FAKE_NEW_ACCESS')
        self.assertEqual(tv._refresh_token, 'FAKE_NEW_REFRESH')

    def test_auth_ack_is_not_mistaken_for_token_refresh(self):
        tv = make_tv()
        tv._refresh_token = 'FAKE_REFRESH'
        tv._access_token = 'FAKE_OLD_ACCESS'
        def publish(topic, payload):
            deliver(tv, TOPIC_AUTH_CODE_RESPONSE, {'result': 1})
            return published()
        with patch.object(tv._client, 'publish', publish):
            self.assertFalse(tv.refresh_token(timeout=.01))

    def test_refresh_response_without_rotated_token_retains_current_token(self):
        tv = make_tv()
        tv._refresh_token = 'FAKE_CURRENT_REFRESH'
        tv._handle_token_response({'accesstoken': 'FAKE_NEW_ACCESS'})
        self.assertEqual(tv._refresh_token, 'FAKE_CURRENT_REFRESH')


class LoopbackBroker:
    """Tiny MQTT 3.1.1 peer for real Paho thread/socket lifecycle checks."""
    def __enter__(self):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen()
        self.listener.settimeout(.1)
        self.stopped = threading.Event()
        self.workers = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        return self
    def serve(self):
        while not self.stopped.is_set():
            try: conn, _ = self.listener.accept()
            except socket.timeout: continue
            except OSError: break
            worker = threading.Thread(target=self.client, args=(conn,), daemon=True)
            self.workers.append(worker)
            worker.start()
    def client(self, conn):
        conn.settimeout(.1)
        def read(n):
            data = b''
            while len(data) < n and not self.stopped.is_set():
                try: part = conn.recv(n - len(data))
                except socket.timeout: continue
                if not part: raise EOFError
                data += part
            if len(data) != n: raise EOFError
            return data
        try:
            while not self.stopped.is_set():
                header = read(1)[0]
                size, multiplier = 0, 1
                while True:
                    digit = read(1)[0]
                    size += (digit & 127) * multiplier
                    if not digit & 128: break
                    multiplier *= 128
                body = read(size)
                if header >> 4 == 1: conn.sendall(b'\x20\x02\x00\x00')
                elif header >> 4 == 8: conn.sendall(b'\x90\x03' + body[:2] + b'\x00')
                elif header >> 4 == 12: conn.sendall(b'\xd0\x00')
                elif header >> 4 == 14: break
        except (EOFError, OSError): pass
        finally: conn.close()
    def __exit__(self, *args):
        self.stopped.set()
        self.listener.close()
        self.thread.join(2)
        for thread in self.workers: thread.join(2)


class PahoLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_mqtt_threads_and_sockets_end_after_repeated_reload(self):
        with LoopbackBroker() as broker:
            clients = []
            for _ in range(3):
                tv = ac.AsyncVidaaTV('127.0.0.1', port=broker.port, use_ssl=False,
                                    enable_persistence=False, auto_detect_protocol=False,
                                    username='test-only', password='test-only')
                self.assertTrue(await tv.async_connect(timeout=2))
                clients.append(tv._client._client)
                await tv.async_close()
            self.assertTrue(all(c._thread is None and c.socket() is None for c in clients))


class StandbyCredentialTests(unittest.TestCase):
    def credentials(self, **changes):
        return dict(client_id='TEST_CLIENT', mqtt_username='TEST_USER',
                    access_token='FAKE_ACCESS', refresh_token='FAKE_REFRESH',
                    auth_method='modern', protocol_version=3290,
                    **changes)

    def construct(self):
        return VidaaTV('tv.invalid', use_ssl=False, enable_persistence=False,
                       use_dynamic_auth=True, mac_address='00:11:22:33:44:55')

    def test_saved_pairing_skips_discovery_on_every_offline_rebuild(self):
        from pyvidaa.protocol import AuthMethod
        with patch.object(VidaaTV, '_load_saved_credentials', return_value=self.credentials()), \
             patch('pyvidaa.client.detect_protocol', side_effect=AssertionError('Unexpected discovery')), \
             self.assertNoLogs('pyvidaa', level='WARNING'):
            for _ in range(5):
                tv = self.construct()
                self.assertEqual(tv.auth_method, AuthMethod.MODERN)
                self.assertEqual(tv._protocol_version, 3290)
                self.assertEqual(tv._client._password, b'FAKE_ACCESS')
                with patch.object(tv._client, 'connect', side_effect=OSError('Host is unreachable')):
                    self.assertFalse(tv.connect(timeout=.01))
                    self.assertEqual(tv._client.connect_timeout, .01)
                tv.disconnect()

    def test_saved_refresh_and_static_pairings_skip_discovery(self):
        scenarios = [
            ({'needs_refresh': True}, b'FAKE_REFRESH'),
            ({'auth_method': 'static', 'access_token': None}, None),
            ({'auth_method': None, 'protocol_version': None}, b'FAKE_ACCESS'),
        ]
        for overrides, password in scenarios:
            creds = self.credentials()
            creds.update(overrides)
            with self.subTest(overrides=overrides), \
                 patch.object(VidaaTV, '_load_saved_credentials', return_value=creds), \
                 patch('pyvidaa.client.detect_protocol', side_effect=AssertionError('Unexpected discovery')):
                tv = self.construct()
                self.assertTrue(tv._using_saved_creds)
                if password: self.assertEqual(tv._client._password, password)
                self.assertEqual(tv._pending_token_refresh, bool(overrides.get('needs_refresh')))
                tv.disconnect()

    def test_new_or_expired_pairing_still_detects_protocol(self):
        for creds in (None, self.credentials(needs_reauth=True)):
            with self.subTest(expired=bool(creds)), \
                 patch.object(VidaaTV, '_load_saved_credentials', return_value=creds), \
                 patch('pyvidaa.client.detect_protocol', return_value=3290) as detect:
                tv = self.construct()
                detect.assert_called_once_with('tv.invalid')
                tv.disconnect()

    def test_normal_sleep_disconnects_are_informational(self):
        for rc in (7, 16):
            tv = make_tv()
            with self.subTest(rc=rc), self.assertLogs('pyvidaa.client', level='INFO') as logs:
                tv._on_disconnect(tv._client, None, rc)
            self.assertEqual([r.levelno for r in logs.records], [logging.INFO])
            self.assertFalse(tv.is_connected)
            tv.disconnect()

    def test_protocol_and_authentication_errors_remain_visible(self):
        tv = make_tv()
        with self.assertLogs('pyvidaa.client', level='WARNING') as logs:
            tv._on_disconnect(tv._client, None, 1)
        self.assertEqual(logs.records[0].levelno, logging.WARNING)
        with self.assertLogs('pyvidaa.client', level='ERROR'):
            tv._on_connect(tv._client, None, {}, 5)
        tv.disconnect()

    def test_offline_metadata_is_quiet_but_explicit_command_fails(self):
        tv = make_tv()
        tv._connected = False
        with self.assertNoLogs('pyvidaa', level='WARNING'), \
             patch.object(tv._client, 'publish', side_effect=AssertionError('Offline metadata must not publish')):
            self.assertIsNone(tv.get_sources(timeout=.01))
        with self.assertLogs('pyvidaa', level='WARNING'):
            self.assertFalse(tv.send_key('KEY_HOME'))
        tv.disconnect()


class WakeClientTests(unittest.TestCase):
    def test_offline_state_and_power_on_are_quiet_and_never_publish(self):
        tv = make_tv()
        tv._connected = False
        with self.assertNoLogs('pyvidaa', level='WARNING'), patch.object(tv._client, 'publish') as publish:
            self.assertIsNone(tv.get_state(timeout=.01))
            self.assertFalse(tv.power_on())
        publish.assert_not_called()
        tv.disconnect()

    def test_unknown_and_awake_states_never_toggle_power(self):
        tv = make_tv()
        for state, expected in ((None, False), ({}, False),
                                ({'statetype': 'app'}, True),
                                ({'statetype': 'fake_sleep_1'}, True)):
            with self.subTest(state=state), patch.object(tv, 'get_state', return_value=state), \
                 patch.object(tv, 'send_key') as send:
                self.assertIs(tv.power_on(), expected)
                send.assert_not_called()
        with patch.object(tv, 'get_state', return_value={'statetype': 'fake_sleep_0'}), \
             patch.object(tv, 'send_key', return_value=True) as send:
            self.assertTrue(tv.power_on())
            send.assert_called_once_with('KEY_POWER')
        tv.disconnect()

    def test_failed_state_publish_never_returns_stale_on_state(self):
        tv = make_tv()
        tv._state = {'statetype': 'app'}
        with patch.object(tv, '_publish', return_value=False), \
             patch.object(tv, 'send_key') as send:
            self.assertIsNone(tv.get_state())
            self.assertFalse(tv.power_on())
            send.assert_not_called()
        tv.disconnect()


if __name__ == '__main__':
    unittest.main(verbosity=2)
