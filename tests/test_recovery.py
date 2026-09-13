import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from server import create_app, public_url, translate
from local_config import load_local_config


class RecoveryTests(unittest.TestCase):
    def test_translation_splits_misaligned_batch(self):
        def response(values):
            result = Mock(ok=True)
            result.json.return_value = {'choices':[{'message':{'content':json.dumps(values)}}]}
            return result
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':'test-only'}), patch('server.requests.post', side_effect=[response(['合并']), response(['一']), response(['二'])]) as post:
            self.assertEqual(translate(['first', 'second']), ['一','二'])
            self.assertEqual(post.call_count, 3)

    def test_proxy_dns_validation_keeps_private_hosts_blocked(self):
        dns = [(socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001::9df0:c23', 443, 0, 0))]
        with patch('server.socket.getaddrinfo', return_value=dns), patch('server.requests.utils.get_environ_proxies', return_value={'https': 'http://127.0.0.1:7890'}), patch('server.remote_public_addresses', return_value=('23.217.118.143',)):
            self.assertEqual(public_url('https://www.sankei.com/'), 'https://www.sankei.com/')
            for url in ('http://127.0.0.1/', 'http://localhost/', 'http://[::1]/'):
                with self.assertRaises(ValueError): public_url(url)
        with patch('server.socket.getaddrinfo', return_value=dns), patch('server.requests.utils.get_environ_proxies', return_value={}), patch('server.remote_public_addresses') as resolver:
            with self.assertRaises(ValueError): public_url('https://www.sankei.com/')
            resolver.assert_not_called()

    def test_local_config_environment_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, '.env').write_text('DEEPSEEK_API_KEY=test-local\nDEEPSEEK_MODEL=test-model\nPATH=ignored\n', encoding='utf-8')
            with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-environment'}, clear=True):
                load_local_config(folder)
                self.assertEqual(os.environ['DEEPSEEK_API_KEY'], 'test-environment')
                self.assertEqual(os.environ['DEEPSEEK_MODEL'], 'test-model')
                self.assertNotIn('PATH', os.environ)

    def test_missing_source_is_partial_even_when_target_met(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            app = create_app(folder)
            client = app.test_client()
            client.post('/api/articles/text', json={'title':'Test article', 'text':'本を読みます。'})
            with sqlite3.connect(Path(folder) / 'fujimi.sqlite3') as db:
                db.execute("UPDATE settings SET value=? WHERE key='news-sources'", (json.dumps([{'name':'Unavailable','id':1,'minimum_count':1,'homepage':'https://example.com/'}]),))
                db.execute("UPDATE settings SET value=? WHERE key='daily-content'", ('{"target_count":1}',))
            db.close()
            provider = Mock()
            provider.collect.side_effect = ValueError('test fetch failed')
            with patch('server.provider_for', return_value=provider):
                client.post('/api/daily/generate')
                for _ in range(100):
                    task = client.get('/api/tasks/daily').json
                    if task['status'] != 'running': break
                    time.sleep(.02)
            self.assertEqual(task['status'], 'partial')
            self.assertEqual(task['missing_sources'], ['Unavailable'])
            self.assertLess(task['percent'], 100)
            self.assertEqual(create_app(folder).test_client().get('/api/tasks/daily').json['status'], 'partial')
            import gc
            gc.collect()
