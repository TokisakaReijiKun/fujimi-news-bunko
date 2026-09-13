import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from article_store import db_connection
from server import create_app


class FakeProvider:
    def __init__(self, key, values, events, *, collect_wait=None):
        self.KEY = key
        self.values = values
        self.events = events
        self.collect_wait = collect_wait
        self.collect_finished = threading.Event()

    def collect(self, source, fetch):
        self.events.append(('collect', self.KEY))
        if self.collect_wait:
            self.collect_wait.wait(4)
        self.collect_finished.set()
        return [f'https://{self.KEY}.test/{value}' for value in self.values if not value.startswith('member')]

    def fetch_article(self, url, fetch):
        value = url.rsplit('/', 1)[-1]
        self.events.append(('candidate', self.KEY, value))
        if value.startswith('invalid'):
            raise ValueError('invalid article')
        return {'title': f'{self.KEY} {value}', 'url': url, 'paragraphs': [f'{self.KEY} {value} 本文。'],
                'images': [], 'videos': [], 'source_key': self.KEY}

    def postprocess(self, article, extracted, services):
        self.events.append(('postprocess', self.KEY, extracted['url'].rsplit('/', 1)[-1]))
        result = services.prepare(article, extracted, self.KEY)
        services.annotate(result)
        return services.save(result)


class DailyCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name)
        self.client = self.app.test_client()

    def tearDown(self):
        import gc
        gc.collect()
        self.temp.cleanup()

    def configure(self, sources, target):
        with db_connection(self.app.article_store.db_path) as db:
            db.execute("UPDATE settings SET value=? WHERE key='news-sources'", (json.dumps(sources),))
            db.execute("UPDATE settings SET value=? WHERE key='daily-content'", (json.dumps({'target_count': target}),))

    def wait_done(self, timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            task = self.client.get('/api/tasks/daily').json
            if task['status'] != 'running':
                return task
            time.sleep(.01)
        self.fail('daily worker did not finish')

    def use_providers(self, providers):
        def select(url):
            return providers[url.split('//', 1)[1].split('.', 1)[0]]
        return patch('server.provider_for', side_effect=select)

    def test_collectors_exclude_members_before_candidates_are_selected(self):
        events = []
        providers = {
            'alpha': FakeProvider('alpha', ['member', 'a1', 'a2'], events),
            'beta': FakeProvider('beta', ['b1', 'b2'], events),
            'gamma': FakeProvider('gamma', ['c1'], events),
        }
        self.configure([
            {'id': 1, 'name': 'Alpha', 'homepage': 'https://alpha.test/', 'minimum_count': 1},
            {'id': 2, 'name': 'Beta', 'homepage': 'https://beta.test/', 'minimum_count': 1},
            {'id': 3, 'name': 'Gamma', 'homepage': 'https://gamma.test/', 'minimum_count': 0},
        ], 3)
        with self.use_providers(providers), patch.dict('os.environ', {}, clear=True):
            self.client.post('/api/daily/generate')
            task = self.wait_done()
        self.assertEqual(task['status'], 'completed', task)
        self.assertEqual(task['completed'], 3)
        self.assertEqual(sum(task['source_counts'].values()), 3)
        self.assertGreaterEqual(task['source_counts']['Alpha'], 1)
        self.assertGreaterEqual(task['source_counts']['Beta'], 1)
        self.assertEqual(task['source_counts']['Gamma'], 0)
        self.assertNotIn('member_excluded', task['candidate_stats']['Alpha'])
        self.assertEqual(task['errors'], [])
        candidates = [i for i, event in enumerate(events) if event[0] == 'candidate']
        posts = [i for i, event in enumerate(events) if event[0] == 'postprocess']
        self.assertGreater(min(posts), max(candidates))
        self.assertNotIn(('candidate', 'alpha', 'member'), events)
        self.assertNotIn(('postprocess', 'alpha', 'member'), events)
        self.assertNotIn(('postprocess', 'gamma', 'c1'), events)
        saved = self.client.get('/api/daily').json['articles']
        self.assertGreaterEqual([a['source_name'] for a in saved].count('Alpha'), 1)
        self.assertGreaterEqual([a['source_name'] for a in saved].count('Beta'), 1)

    def test_candidate_failures_do_not_enter_error_list_or_block_public_sources(self):
        events = []
        providers = {
            'locked': FakeProvider('locked', ['member-1', 'invalid-1', 'member-2'], events),
            'open': FakeProvider('open', ['one', 'two'], events),
        }
        self.configure([
            {'id': 1, 'name': 'Locked', 'homepage': 'https://locked.test/', 'minimum_count': 1},
            {'id': 2, 'name': 'Open', 'homepage': 'https://open.test/', 'minimum_count': 1},
        ], 2)
        with self.use_providers(providers), patch.dict('os.environ', {}, clear=True):
            self.client.post('/api/daily/generate')
            task = self.wait_done()
        self.assertEqual(task['status'], 'partial')
        self.assertEqual(task['missing_sources'], ['Locked'])
        self.assertEqual(task['candidate_stats']['Locked']['invalid_excluded'], 1)
        self.assertEqual(task['errors'], [])
        self.assertEqual(task['source_counts']['Open'], 2)
        self.assertFalse(any(event[1] == 'locked' and event[0] == 'postprocess' for event in events))

    def test_existing_articles_are_selected_without_reprocessing(self):
        self.client.post('/api/articles/text', json={'title': '已保存', 'text': '正文'})
        events = []
        provider = FakeProvider('alpha', ['a1'], events)
        self.configure([{'id': 1, 'name': 'Alpha', 'homepage': 'https://alpha.test/', 'minimum_count': 1}], 2)
        with self.use_providers({'alpha': provider}), patch.dict('os.environ', {}, clear=True):
            self.client.post('/api/daily/generate')
            task = self.wait_done()
        self.assertEqual(task['status'], 'completed')
        self.assertEqual(task['selected'], 2)
        self.assertEqual(events.count(('postprocess', 'alpha', 'a1')), 1)
        self.assertEqual(len(self.client.get('/api/daily').json['articles']), 2)

    def test_retry_with_more_existing_articles_than_target_uses_real_total(self):
        for number in range(3):
            self.client.post('/api/articles/text', json={'title': f'已保存 {number}', 'text': '正文'})
        provider=FakeProvider('alpha', ['new'], [])
        self.configure([{'id': 1, 'name': 'Alpha', 'homepage': 'https://alpha.test/', 'minimum_count': 1}], 2)
        with self.use_providers({'alpha': provider}), patch.dict('os.environ', {}, clear=True):
            self.client.post('/api/daily/generate')
            task=self.wait_done()
        self.assertEqual(task['total'], 4)
        self.assertEqual(task['completed'], 4)
        self.assertEqual(task['message'],'日刊 4/4 篇。')

    def test_candidate_pool_is_limited_to_five_per_source(self):
        events=[]
        provider=FakeProvider('alpha', [f'item-{number}' for number in range(8)], events)
        sources=[{'id': 1, 'name': 'Alpha', 'homepage': 'https://alpha.test/', 'minimum_count': 1}]
        self.configure(sources, 10)
        with self.use_providers({'alpha': provider}), patch.dict('os.environ', {}, clear=True):
            self.client.post('/api/daily/generate')
            task=self.wait_done()
        self.assertEqual(task['total'], 10)
        self.assertEqual(task['status'], 'partial', task)
        self.assertEqual(task['candidate_stats']['Alpha']['listed'], 5)
        self.assertEqual(task['candidate_stats']['Alpha']['public'], 5)
        self.assertEqual(len([event for event in events if event[0] == 'candidate']), 5)

    def test_selection_reserves_each_source_then_randomly_fills_remaining_slots(self):
        events = []
        names = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon', 'Zeta']
        providers = {name.lower(): FakeProvider(name.lower(), ['one', 'two'], events) for name in names}
        sources = [
            {'id': index, 'name': name, 'homepage': f'https://{name.lower()}.test/', 'minimum_count': 1}
            for index, name in enumerate(names, 1)
        ]
        self.configure(sources, 10)

        class ReverseRandom:
            @staticmethod
            def shuffle(values):
                values.reverse()

        with self.use_providers(providers), patch('server.random.SystemRandom', return_value=ReverseRandom()), \
                patch.dict('os.environ', {}, clear=True):
            self.client.post('/api/daily/generate')
            task = self.wait_done()

        self.assertEqual(task['status'], 'completed', task)
        self.assertEqual(task['completed'], 10)
        self.assertEqual(sum(task['source_counts'].values()), 10)
        self.assertTrue(all(task['source_counts'][name] >= 1 for name in names))
        self.assertEqual(task['source_counts'], {
            'Alpha': 1, 'Beta': 1, 'Gamma': 2, 'Delta': 2, 'Epsilon': 2, 'Zeta': 2,
        })

    def test_satisfied_edition_retry_needs_no_network_or_reprocessing(self):
        events=[]
        provider=FakeProvider('alpha', ['first'], events)
        self.configure([{'id':1,'name':'Alpha','homepage':'https://alpha.test/','minimum_count':1}],1)
        with self.use_providers({'alpha':provider}), patch.dict('os.environ',{},clear=True):
            self.client.post('/api/daily/generate')
            self.assertEqual(self.wait_done()['status'],'completed')
            events.clear()
            self.client.post('/api/daily/generate')
            task=self.wait_done()
        self.assertEqual(task['status'],'completed')
        self.assertEqual(events,[])
        self.assertEqual(task['source_counts'],{'Alpha':1})

    def test_cancelled_candidate_worker_cannot_postprocess_or_publish(self):
        events, release = [], threading.Event()
        blocked = FakeProvider('blocked', ['old'], events, collect_wait=release)
        empty = FakeProvider('empty', [], events)
        self.configure([
            {'id': 1, 'name': 'Blocked', 'homepage': 'https://blocked.test/', 'minimum_count': 1},
            {'id': 2, 'name': 'Empty', 'homepage': 'https://empty.test/', 'minimum_count': 0},
        ], 1)
        providers = {'blocked': blocked, 'empty': empty}
        with self.use_providers(providers), patch.dict('os.environ', {}, clear=True):
            self.client.post('/api/daily/generate')
            self.assertFalse(blocked.collect_finished.wait(.1))
            old_id = self.client.get('/api/tasks/daily').json['id']
            self.client.delete('/api/tasks/daily')
            release.set()
            providers['blocked'] = FakeProvider('blocked', [], events)
            self.client.post('/api/daily/generate')
            task = self.wait_done()
            self.assertNotEqual(task['id'], old_id)
        self.assertFalse(any(event[0] == 'postprocess' and event[1] == 'blocked' for event in events))
        self.assertEqual(self.client.get('/api/days').json, [])
