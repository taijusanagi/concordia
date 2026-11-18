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
  --poll=False --output_dir=./local_runs/concordia_island
```

## Understanding After the First Example

- The Island example uses the Concordia framework to simulate people's actions and movement between predefined locations.
- ESA stands for Enacted Self Agent. It is an agent design that uses observations, personality, memories, and emotions to choose actions.
- During each tick, agents think about what to do and propose actions, which the Game Master resolves to update the world state. In async mode, agents run concurrently, and an agent may observe another agent's already-resolved action within the same tick. This depends on timing and what information the agent receives. Island advances the clock once all agents have completed the tick's required activity.

## Things I Can Do Next

- [x] Track LLM calls and estimate token usage with the existing profiler.
- [x] Create visualizations of the simulation.
- Test all the examples and study their implementation patterns.
  -> Select the most relevant ones.

## Visualizations

- I added a visualization for the Island example. It is useful, but I should not spend too much time on it because it is optional.
- Island initializes the world state, but its default output does not save a dedicated initial-state snapshot or a complete, ordered history of state changes. This makes exact replay difficult. When exploring the next example, I will consider how to capture the initial state and subsequent changes.

## Testing the Tutorial Code

- I updated the tutorial code to use Codex authentication and selected a lower-cost model.
- I found a way to count LLM calls and estimate token usage with the existing profiler. These estimates are not the actual token counts reported by Codex.
- World state can be represented by narrative memories or structured component state. Prefabs assemble the components that manage it.
- Defining the entities and deciding how to represent and manage world state will be key first steps in our project.

## Things I Can Do Next

- [ ] Try saving and resuming simulations with checkpoints.
- [ ] Explore practical implementation examples relevant to my project.
