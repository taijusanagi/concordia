# OpenAI and Codex providers

`openai` uses an OpenAI Platform API key and API billing. `openai_codex`
uses a local Codex CLI signed in with ChatGPT and the account's Codex allowance.

## ChatGPT subscription setup

Install the official [Codex CLI](https://developers.openai.com/codex/cli),
then sign in with your ChatGPT account:

```sh
codex login
codex login status
```

Choose ChatGPT when signing in. The provider requires the local CLI's
`app-server` interface and its account/rate-limit APIs. It was verified with
Codex CLI `0.169.0-alpha.11.1`. No OpenAI Python SDK is required by this adapter.

Use the registered provider with a model available to your Codex account:

```python
from concordia.contrib import language_models

model = language_models.language_model_setup(
    api_type='openai_codex',
    model_name='gpt-6.1-sol',  # Choose a model your Codex account can access.
)
print(model.sample_text('Question: Is Jake a turtle?\nAnswer: Jake is '))
print(model.sample_choice('Choose a greeting.', ['hello', 'good morning']))
```

For example runners that accept `--api_type` and `--model_name`, use
`--api_type=openai_codex --model_name=gpt-6.1-sol`. Some runners automatically
pass environment API keys into every provider. Unset those keys for the command:

```sh
env -u OPENAI_API_KEY -u CODEX_API_KEY -u GOOGLE_API_KEY -u GEMINI_API_KEY \
  python -m examples.concordia_island.run \
  --personas_date=brecksville_ohio --agents=2 --ticks=1 \
  --api_type=openai_codex --model_name=gpt-6.1-sol \
  --poll=False --output_dir=./local_runs/codex_subscription
```

Do not pass `--api_key`, `--aistudio_api_key`, or enable `--use_aistudio` with
this provider. If `codex` is outside PATH, instantiate the class directly:

```python
from concordia.contrib.language_models.openai import codex_model

model = codex_model.CodexLanguageModel(
    model_name='gpt-6.1-sol', codex_path='/absolute/path/to/codex'
)
```

## Subscription and runtime behavior

* API-key accounts and explicit `api_key` arguments are rejected before any
  model request. API keys and endpoint overrides from the parent environment
  are removed from the Codex subprocess. There is no API-key fallback.
* Codex owns login storage and token refresh. Concordia never reads or copies
  your OAuth tokens or initiates login/logout.
* The provider checks reported quota buckets before each completion and stops
  if any reports exhaustion or quota information cannot be retrieved. Quota,
  authentication, and model errors propagate to the caller. The choice method
  retries invalid text choices at most three times, but never retries quota or
  authentication errors itself.
* Codex owns account billing. This adapter never buys credits or enables
  automatic top-ups. To enforce spending strictly within your included plan,
  disable paid overage/automatic top-ups in your account settings: the app-server
  interface has no per-request switch to prohibit existing supplemental credit
  use, and a quota check cannot reserve allowance against concurrent usage.
* Each completion starts a local app-server process and a fresh ephemeral thread
  in a temporary directory, with read-only permissions, no interactive approvals,
  and shell, patch, Code Mode, multi-agent, app, MCP, and web-search features
  disabled. Startup overhead makes this slower than a direct model API.
* `temperature`, `top_p`, `top_k`, and `seed` are not exposed by this interface
  and are ignored. `max_tokens` is a prompt hint, not a hard token cap.
  `terminators` truncate returned text locally and do not reduce generated usage.
  `timeout` bounds the app-server interaction, followed by process cleanup.
  Direct calls default to 300 seconds to allow long persona-generation
  responses. Explicit timeouts (including those from wrappers) are respected.
* This is a local integration for personal simulations. Hosted/commercial use
  requires the appropriate authentication integration; see the official
  [app-server documentation](https://developers.openai.com/codex/app-server).

## Tests

From the repository root, run:

```sh
python -m pytest -n 0 \
  concordia/contrib/language_models/openai/codex_model_test.py \
  concordia/contrib/language_models/language_models_test.py
```

The tests use a fake JSONL app-server subprocess and never contact OpenAI or
consume subscription allowance.
