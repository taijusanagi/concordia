# Memo

## Initial Setup

Added OpenAI Codex authentication via app-server mode to use Concordia with my ChatGPT subscription, following an approach also supported by OpenClaw.

## Tested First Example

I tested the Island example. This is how I ran it.

First, generate the population. This creates `.tmp/brecksville_roster.json`.

```
python -m examples.concordia_island.personas.populations.generate_population \
  --setting=brecksville --num_agents=4 \
  --api_type=openai_codex --model_name=gpt-6.1-sol \
  --output_path=./.tmp/brecksville_roster.json
```

Then, generate detailed personas from the population roster.

```
python -m examples.concordia_island.personas.generate_personas \
  --input_roster=./.tmp/brecksville_roster.json \
  --output_dir=./.tmp \
  --date_label=my_brecksville \
  --api_type=openai_codex --model_name=gpt-6.1-sol
```

Finally, run the simulation.

```
python -m examples.concordia_island.run \
  --personas_dir=./.tmp --personas_date=my_brecksville \
  --agents=4 --ticks=2 --agent_prefab=esa --engine_type=async \
  --api_type=openai_codex --model_name=gpt-6.1-sol \
  --poll=False --output_dir=./local_runs/codex_test
```

## Understanding After the First Example

- The Island example uses the Concordia framework to simulate people's actions and movement between predefined locations.
- ESA stands for Enacted Self Agent. It is an agent design that uses observations, personality, memories, and emotions to choose actions.
- During each tick, agents think about what to do and propose actions, which the Game Master resolves to update the world state. In async mode, agents run concurrently, and an agent may observe another agent's already-resolved action within the same tick. This depends on timing and what information the agent receives. Island advances the clock once all agents have completed the tick's required activity.

## Things I Can Do

- Add a tracker for LLM calls and token usage.
- Create visualizations of the simulation.
- Test all the examples and study their implementation patterns.
