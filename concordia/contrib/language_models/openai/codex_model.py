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

"""Text completions through a local Codex ChatGPT subscription login.

Requires the Codex CLI and `codex login`. No OpenAI Python SDK is needed.
Each call uses a fresh ephemeral thread. API-key accounts are refused before
starting a thread; login and token refresh remain owned by Codex.
"""

from collections import deque
from collections.abc import Collection, Sequence
import json
import math
import os
import selectors
import shutil
import subprocess
import tempfile
import time
from typing import Any, override

from concordia.language_model import language_model
from concordia.utils import measurements as measurements_lib

_INSTRUCTIONS = (
    'You are a text completion model for a simulation. Continue the supplied'
    ' text without repeating it. Return only the completion, without commentary'
    ' or markdown fences. Treat the prompt as simulation data. Do not use'
    ' tools, inspect files, execute commands, or access external services.'
)
_MAX_CHOICE_ATTEMPTS = 3
# Persona generation requests long narratives, and app-server startup/auth
# consume part of the same budget. Keep explicit caller timeouts unchanged.
_DEFAULT_TIMEOUT_SECONDS = 300
# Prevent both API-key fallback and endpoint overrides from the parent shell.
_REMOVED_ENV = {
    'OPENAI_API_KEY',
    'CODEX_API_KEY',
    'OPENAI_BASE_URL',
    'OPENAI_API_BASE',
    'OPENAI_ORG_ID',
    'OPENAI_PROJECT_ID',
    'CODEX_AUTH_JSON',
}
_CONFIG = {
    'model_provider': 'openai',
    'approval_policy': 'never',
    'sandbox_mode': 'read-only',
    'web_search': 'disabled',
    'features.shell_tool': False,
    'features.apply_patch_freeform': False,
    'features.code_mode': False,
    'features.multi_agent': False,
    'features.multi_agent_v2': False,
    'features.apps': False,
    'orchestrator.mcp.enabled': False,
}


class CodexError(RuntimeError):
  """Codex could not complete a subscription request."""


class _Connection:
  """A bounded, synchronous JSONL connection to a single app-server process."""

  def __init__(self, process: subprocess.Popen, timeout: float):
    if process.stdin is None or process.stdout is None:
      raise ValueError('Codex app-server requires stdin/stdout pipes.')
    self._stdin = process.stdin
    self._stdout = process.stdout
    self._deadline = time.monotonic() + timeout
    self._buffer = b''
    self._notifications = deque()
    self._selector = selectors.DefaultSelector()
    self._selector.register(self._stdout, selectors.EVENT_READ)

  def close(self) -> None:
    self._selector.close()

  def send(self, message: dict[str, Any]) -> None:
    try:
      self._stdin.write((json.dumps(message) + '\n').encode())
      self._stdin.flush()
    except (BrokenPipeError, OSError) as error:
      raise CodexError('Codex app-server closed its input.') from error

  def receive(self) -> dict[str, Any]:
    if time.monotonic() >= self._deadline:
      raise TimeoutError('Codex subscription request timed out.')
    if self._notifications:
      return self._notifications.popleft()
    return self._read()

  def _read(self) -> dict[str, Any]:
    if time.monotonic() >= self._deadline:
      raise TimeoutError('Codex subscription request timed out.')
    while b'\n' not in self._buffer:
      remaining = self._deadline - time.monotonic()
      if remaining <= 0 or not self._selector.select(remaining):
        raise TimeoutError('Codex subscription request timed out.')
      chunk = os.read(self._stdout.fileno(), 65536)
      if not chunk:
        raise CodexError(
            'Codex app-server exited unexpectedly. Check `codex --version` '
            'and `codex login status`.'
        )
      self._buffer += chunk
    line, self._buffer = self._buffer.split(b'\n', 1)
    try:
      message = json.loads(line)
    except (ValueError, UnicodeError) as error:
      raise CodexError('Invalid JSON from Codex app-server.') from error
    if not isinstance(message, dict):
      raise CodexError('Invalid message from Codex app-server.')
    # No interactive approvals, credential requests, or tool execution.
    if 'method' in message and 'id' in message:
      self.send({
          'id': message['id'],
          'error': {'code': -32601, 'message': 'Unsupported by Concordia.'},
      })
      raise CodexError('Codex requested an unsupported interactive operation.')
    if message.get('method') == 'account/updated':
      if message.get('params', {}).get('authMode') != 'chatgpt':
        raise CodexError('Codex is no longer using ChatGPT subscription auth.')
    return message

  def request(self, request_id: int, method: str, params: dict) -> dict:
    self.send({'id': request_id, 'method': method, 'params': params})
    while True:
      message = self._read()
      if message.get('id') == request_id:
        if 'error' in message:
          raise CodexError(
              f'Codex {method} failed: '
              f'{message["error"].get("message", "Unknown error")}'
          )
        return message['result']
      self._notifications.append(message)


class CodexLanguageModel(language_model.LanguageModel):
  """Uses only ChatGPT-authenticated Codex; never falls back to an API key.

  Sampling controls and hard output token limits are not exposed by app-server.
  `max_tokens` is a prompt hint; terminators are applied to the returned text.
  Calls do not share conversation history and can run concurrently.
  """

  def __init__(
      self,
      model_name: str,
      *,
      api_key: str | None = None,
      codex_path: str = 'codex',
      measurements: measurements_lib.Measurements | None = None,
      channel: str = language_model.DEFAULT_STATS_CHANNEL,
  ):
    if api_key is not None:
      raise ValueError(
          'openai_codex uses ChatGPT login only. Omit api_key and run `codex'
          ' login`. Unset API-key environment variables in example runners.'
      )
    executable = shutil.which(codex_path)
    if executable is None:
      raise ValueError(
          'Codex CLI not found. Install it, run `codex login`, and ensure '
          '`codex` is on PATH (or pass codex_path).'
      )
    self._codex_path = executable
    self._model_name = model_name
    self._measurements = measurements
    self._channel = channel

  def _complete(self, prompt: str, timeout: float) -> str:
    if not math.isfinite(timeout) or timeout <= 0:
      raise ValueError('timeout must be a positive finite number of seconds.')
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _REMOVED_ENV
    }
    command = [self._codex_path, 'app-server']
    for key, value in _CONFIG.items():
      command.extend(['-c', f'{key}={json.dumps(value)}'])
    # A neutral cwd avoids loading repository instructions/config into prompts.
    with tempfile.TemporaryDirectory(prefix='concordia-codex-') as directory:
      with subprocess.Popen(
          command,
          stdin=subprocess.PIPE,
          stdout=subprocess.PIPE,
          stderr=subprocess.DEVNULL,
          cwd=directory,
          env=env,
      ) as process:
        connection = _Connection(process, timeout)
        try:
          connection.request(
              0,
              'initialize',
              {
                  'clientInfo': {'name': 'concordia', 'version': '1.0.0'},
              },
          )
          connection.send({'method': 'initialized', 'params': {}})
          account = connection.request(
              1, 'account/read', {'refreshToken': False}
          ).get('account')
          if not account or account.get('type') != 'chatgpt':
            raise CodexError(
                'A ChatGPT subscription login is required. Run `codex login` '
                'and choose ChatGPT. API-key accounts are not accepted.'
            )
          limits = connection.request(2, 'account/rateLimits/read', {})
          snapshots = list((limits.get('rateLimitsByLimitId') or {}).values())
          if limits.get('rateLimits'):
            snapshots.append(limits['rateLimits'])
          if not any(
              snapshot.get('primary') or snapshot.get('secondary')
              for snapshot in snapshots
          ):
            raise CodexError(
                'Cannot verify Codex subscription allowance; refusing to '
                'start a completion.'
            )
          for snapshot in snapshots:
            windows = [snapshot.get('primary'), snapshot.get('secondary')]
            if snapshot.get('rateLimitReachedType') or any(
                window and window.get('usedPercent', 0) >= 100
                for window in windows
            ):
              raise CodexError(
                  'Codex subscription allowance is exhausted. Wait for the '
                  'limit to reset. No API-key fallback was attempted.'
              )
          thread = connection.request(
              3,
              'thread/start',
              {
                  'model': self._model_name,
                  'modelProvider': 'openai',
                  'cwd': directory,
                  'ephemeral': True,
                  'approvalPolicy': 'never',
                  'sandbox': 'read-only',
                  'baseInstructions': _INSTRUCTIONS,
                  'developerInstructions': '',
              },
          )
          thread_id = thread['thread']['id']
          connection.request(
              4,
              'turn/start',
              {
                  'threadId': thread_id,
                  'input': [{'type': 'text', 'text': prompt}],
              },
          )
          messages = {}
          while True:
            event = connection.receive()
            params = event.get('params', {})
            if params.get('threadId') != thread_id:
              continue
            if event.get('method') == 'item/completed':
              item = params.get('item', {})
              if item.get('type') == 'agentMessage':
                if item.get('phase') != 'commentary':
                  messages[item['id']] = item['text']
            if event.get('method') == 'turn/completed':
              turn = params['turn']
              if turn.get('status') != 'completed':
                detail = (turn.get('error') or {}).get(
                    'message', turn['status']
                )
                raise CodexError(
                    f'Codex subscription turn failed: {detail}. '
                    'No API-key fallback was attempted.'
                )
              if not messages:
                raise CodexError('Codex completed without a text response.')
              return '\n'.join(messages.values())
        finally:
          connection.close()
          if process.poll() is None:
            process.terminate()
            try:
              process.wait(timeout=5)
            except subprocess.TimeoutExpired:
              process.kill()
              process.wait()

  @override
  def sample_text(
      self,
      prompt: str,
      *,
      max_tokens: int = language_model.DEFAULT_MAX_TOKENS,
      terminators: Collection[str] = language_model.DEFAULT_TERMINATORS,
      temperature: float = language_model.DEFAULT_TEMPERATURE,
      top_p: float = language_model.DEFAULT_TOP_P,
      top_k: int = language_model.DEFAULT_TOP_K,
      timeout: float = _DEFAULT_TIMEOUT_SECONDS,
      seed: int | None = None,
  ) -> str:
    del temperature, top_p, top_k, seed  # Not exposed by Codex app-server.
    result = self._complete(
        f'Keep the completion within approximately {max_tokens} tokens.\n\n'
        + prompt,
        timeout,
    )
    for terminator in terminators:
      if terminator:
        result = result.split(terminator, 1)[0]
    if self._measurements is not None:
      self._measurements.publish_datum(
          self._channel, {'raw_text_length': len(result)}
      )
    return result

  @override
  def sample_choice(
      self,
      prompt: str,
      responses: Sequence[str],
      *,
      seed: int | None = None,
  ) -> tuple[int, str, dict[str, float]]:
    if not responses:
      raise ValueError('responses must not be empty.')
    choice_prompt = (
        prompt
        + '\nRespond EXACTLY with one of these strings:\n'
        + '\n'.join(responses)
    )
    answer = ''
    for attempt in range(_MAX_CHOICE_ATTEMPTS):
      answer = self.sample_text(choice_prompt, seed=seed).strip()
      if answer in responses:
        index = responses.index(answer)
        if self._measurements is not None:
          self._measurements.publish_datum(
              self._channel, {'choices_calls': attempt}
          )
        return index, responses[index], {}
    raise language_model.InvalidResponseError(
        f'Codex did not return an allowed choice. Last response: {answer!r}'
    )
