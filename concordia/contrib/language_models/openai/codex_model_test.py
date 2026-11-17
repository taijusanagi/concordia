# Copyright 2026 DeepMind Technologies Limited.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Subscription-only Codex tests using a real subprocess with a fake server."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from concordia.contrib import language_models
from concordia.contrib.language_models.openai import codex_model
from concordia.language_model import language_model
from concordia.utils import measurements

_SERVER = r"""
import json, os, sys, time

def send(value):
  print(json.dumps(value), flush=True)

for line in sys.stdin:
  request = json.loads(line)
  with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(request) + '\n')
  method = request['method']
  if method == 'initialized':
    continue
  mode = os.environ.get('FAKE_MODE', 'ok')
  result = {}
  if method == 'initialize':
    assert 'OPENAI_API_KEY' not in os.environ
    assert 'CODEX_API_KEY' not in os.environ
    assert 'OPENAI_BASE_URL' not in os.environ
    if mode == 'timeout':
      time.sleep(30)
    if mode == 'exit':
      sys.exit(1)
    if mode == 'invalid':
      print('not json', flush=True)
      continue
  if method == 'account/read':
    result = {'account': {'type': 'chatgpt'}}
    if mode == 'apikey':
      result = {'account': {'type': 'apiKey'}}
    if mode == 'logged_out':
      result = {'account': None}
  if method == 'thread/start':
    assert request['params']['ephemeral']
    assert request['params']['modelProvider'] == 'openai'
    assert request['params']['sandbox'] == 'read-only'
    assert request['params']['approvalPolicy'] == 'never'
    result = {'thread': {'id': 'thread1'}}
    if mode == 'rpc_error':
      send({'id': request['id'], 'error': {'message': 'model unavailable'}})
      continue
  if method == 'account/rateLimits/read':
    result = {'rateLimits': {'primary': {'usedPercent': 10}}}
    if mode == 'exhausted':
      result['rateLimits']['primary']['usedPercent'] = 100
    if mode == 'unknown_limits':
      result = {}
    if mode == 'null_windows':
      result = {'rateLimits': {'primary': None, 'secondary': None}}
  if method != 'turn/start' or mode != 'early_events':
    send({'id': request['id'], 'result': result})
  if method == 'turn/start':
    if mode == 'interactive':
      send({'id': 99, 'method': 'item/commandExecution/requestApproval',
            'params': {}})
      continue
    if mode == 'auth_changed':
      send({'method': 'account/updated', 'params': {'authMode': 'apikey'}})
      continue
    if mode == 'quota':
      send({'method': 'turn/completed', 'params': {'threadId': 'thread1',
        'turn': {'status': 'failed', 'error': {'message': 'Usage limit reached'}}}})
      continue
    if mode != 'empty':
      send({'method': 'item/completed', 'params': {'threadId': 'thread1',
        'item': {'id': 'comment', 'type': 'agentMessage',
                 'phase': 'commentary', 'text': 'Thinking...'}}})
      send({'method': 'item/completed', 'params': {'threadId': 'thread1',
        'item': {'id': 'answer', 'type': 'agentMessage',
                 'phase': 'final_answer', 'text': 'Hello Ω!STOP ignored'}}})
    send({'method': 'turn/completed', 'params': {'threadId': 'thread1',
      'turn': {'status': 'completed'}}})
    if mode == 'early_events':
      send({'id': request['id'], 'result': result})
"""


class CodexModelTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.log = Path(directory.name) / 'requests.jsonl'
    server = Path(directory.name) / 'codex'
    server.write_text(f'#!{sys.executable}\n' + _SERVER)
    server.chmod(0o700)
    environment = mock.patch.dict(
        os.environ,
        {
            'FAKE_LOG': str(self.log),
            'FAKE_MODE': 'ok',
            'OPENAI_API_KEY': 'must-not-be-used',
            'CODEX_API_KEY': 'must-not-be-used',
            'OPENAI_BASE_URL': 'https://must-not-be-used.invalid',
        },
    )
    environment.start()
    self.addCleanup(environment.stop)
    self.model = codex_model.CodexLanguageModel(
        model_name='subscription-model', codex_path=str(server)
    )

  def requests(self):
    return [json.loads(line) for line in self.log.read_text().splitlines()]

  def test_completion_and_measurements(self):
    stats = measurements.Measurements()
    self.model._measurements = stats
    self.assertEqual(
        self.model.sample_text('Test', terminators=('STOP',)), 'Hello Ω!'
    )
    self.assertEqual(
        stats.get_last_datum('language_model_stats'), {'raw_text_length': 8}
    )
    self.assertEqual(
        [r['method'] for r in self.requests()],
        [
            'initialize',
            'initialized',
            'account/read',
            'account/rateLimits/read',
            'thread/start',
            'turn/start',
        ],
    )

  def test_no_history_shared_between_calls(self):
    self.model.sample_text('First')
    self.model.sample_text('Second')
    inputs = [
        r['params']['input'][0]['text']
        for r in self.requests()
        if r['method'] == 'turn/start'
    ]
    self.assertIn('First', inputs[0])
    self.assertNotIn('First', inputs[1])

  def test_refuses_api_key_or_missing_login_before_starting_thread(self):
    for mode in ('apikey', 'logged_out'):
      with self.subTest(mode=mode):
        os.environ['FAKE_MODE'] = mode
        with self.assertRaisesRegex(codex_model.CodexError, 'codex login'):
          self.model.sample_text('Never send this')
    self.assertFalse(
        any(r['method'] == 'thread/start' for r in self.requests())
    )

  def test_refuses_explicit_api_key(self):
    with self.assertRaisesRegex(ValueError, 'ChatGPT login only'):
      codex_model.CodexLanguageModel('model', api_key='key')

  def test_missing_cli_has_setup_instructions(self):
    with self.assertRaisesRegex(ValueError, 'Codex CLI not found'):
      codex_model.CodexLanguageModel('model', codex_path='/missing/codex')

  def test_usage_limit_propagates_without_retry_or_fallback(self):
    os.environ['FAKE_MODE'] = 'quota'
    with self.assertRaisesRegex(codex_model.CodexError, 'Usage limit reached'):
      self.model.sample_choice('Pick', ['a', 'b'])
    self.assertEqual(
        sum(r['method'] == 'turn/start' for r in self.requests()), 1
    )

  def test_exhausted_or_unknown_quota_stops_before_starting_thread(self):
    for mode in ('exhausted', 'unknown_limits', 'null_windows'):
      with self.subTest(mode=mode):
        os.environ['FAKE_MODE'] = mode
        with self.assertRaises(codex_model.CodexError):
          self.model.sample_text('Never send this')
    self.assertFalse(
        any(r['method'] == 'thread/start' for r in self.requests())
    )

  def test_timeout_terminates_process(self):
    os.environ['FAKE_MODE'] = 'timeout'
    start = time.monotonic()
    with self.assertRaises(TimeoutError):
      self.model.sample_text('Test', timeout=0.2)
    self.assertLess(time.monotonic() - start, 5)

  def test_long_generation_budget_and_explicit_timeout(self):
    with mock.patch.object(
        self.model, '_complete', return_value='answer'
    ) as complete:
      self.model.sample_text('A detailed persona')
      self.assertEqual(complete.call_args.args[1], 300)
      self.model.sample_text('A short request', timeout=12)
      self.assertEqual(complete.call_args.args[1], 12)

  def test_invalid_timeout(self):
    for timeout in (0, -1, float('inf'), float('nan')):
      with self.subTest(timeout=timeout), self.assertRaises(ValueError):
        self.model.sample_text('Test', timeout=timeout)

  def test_server_failures_are_reported(self):
    for mode, message in (
        ('exit', 'exited unexpectedly'),
        ('invalid', 'Invalid JSON'),
        ('rpc_error', 'model unavailable'),
        ('empty', 'without a text'),
        ('interactive', 'unsupported interactive'),
        ('auth_changed', 'no longer using ChatGPT'),
    ):
      with self.subTest(mode=mode):
        os.environ['FAKE_MODE'] = mode
        with self.assertRaisesRegex(codex_model.CodexError, message):
          self.model.sample_text('Test')

  def test_notifications_before_turn_start_response_are_preserved(self):
    os.environ['FAKE_MODE'] = 'early_events'
    self.assertEqual(self.model.sample_text('Test'), 'Hello Ω!STOP ignored')

  def test_choice_retries_invalid_output(self):
    with mock.patch.object(
        self.model, 'sample_text', side_effect=['invalid', ' b \n']
    ) as sample:
      self.assertEqual(
          self.model.sample_choice('Pick', ['a', 'b']), (1, 'b', {})
      )
    self.assertEqual(sample.call_count, 2)

  def test_choice_retries_are_bounded(self):
    with mock.patch.object(self.model, 'sample_text', return_value='invalid'):
      with self.assertRaises(language_model.InvalidResponseError):
        self.model.sample_choice('Pick', ['a', 'b'])

  def test_empty_choices_are_rejected(self):
    with self.assertRaises(ValueError):
      self.model.sample_choice('Pick', [])

  def test_factory_loads_codex_provider(self):
    with mock.patch.object(codex_model.shutil, 'which', return_value='/codex'):
      model = language_models.language_model_setup(
          api_type='openai_codex', model_name='subscription-model'
      )
    self.assertIsInstance(model, codex_model.CodexLanguageModel)


if __name__ == '__main__':
  unittest.main()
