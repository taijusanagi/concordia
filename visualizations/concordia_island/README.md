# Island Observatory

A local, read-only replay of Concordia Island. Select a saved run, follow its
residents on an illustrated map, inspect recorded ESA component outputs, and
compare proposed actions with Game Master resolutions.

## Start

From the repository root, with your existing virtual environment activated:

```sh
python -m visualizations.concordia_island.server
```

Open **http://127.0.0.1:8766**. No frontend build, Node.js installation, API key,
or Codex process is needed. The server uses Python's standard library plus
PyYAML, which is also used by the existing Island visualization tools. If it
is missing, install it with `python -m pip install pyyaml`.

By default, the run picker lists direct subdirectories of `local_runs/` that
contain `raw_log.json`. To read a different archive or use another port:

```sh
python -m visualizations.concordia_island.server \
  --runs-dir=./.tmp/saved_runs --port=8767
```

The server binds only to `127.0.0.1`. Stop it with Ctrl+C.

## Explore a run

* Play, pause, step, or scrub through the recorded events. Playback speed is a
  presentation speed, not a reconstruction of elapsed simulation runtime.
* Select a resident in the roster or on the map. While inspecting a different
  resident, the inspector shows their latest record at or before the selected
  event; it never substitutes an unmarked future action.
* **Observe / Think / Act / Resolve** shows the agent's observation, saved
  component outputs, proposed action, and Game Master outcome. Expand a thought
  card and its transcript to inspect the full recorded component data.
* **Persona** reads matching generated persona files from `.tmp/<population>/`
  and `examples/concordia_island/personas/populations/<population>/`. Profiles
  are matched by name, not by an immutable run provenance identifier; if a
  same-named persona has since been regenerated, it may differ from the original.
  Without a matching file, initial background memory entries are shown.
* **Memories** searches the final saved memory bank. It is explicitly an
  end-of-run view, not an event-time memory snapshot.
* **GM context** shows the location context saved with the selected resolution.
  **Tick snapshot** shows the separate `location_history.json` record.
* Filter the event list by resident, or toggle map labels. Keyboard shortcuts:
  left/right arrows to step; Space to play/pause outside controls.

## What the replay can establish

`raw_log.json` is the required source. The viewer uses optional
`simulation_state.json`, `performance.json`, `location_history.json`, and
`entity_memories.json` when present. Existing atlas data provides place names
and aliases; the village layout and routes are illustrative.

The display preserves recorded log order. Local per-agent `Step` values can
include async polling iterations, so they are not treated as global tick IDs.
Displayed ticks are grouped from recorded Game Master simulation-clock labels;
missing/incomplete clock records can make those labels incomplete.

Saved logs do not establish exact concurrent model-call timing, actual walking
paths, or a complete physical simulation. Component output and prompt
transcripts are the recorded text, not hidden model reasoning. No token counts
or model-call timings are invented. Game Master context and tick snapshots can
differ because they were captured at different points during async execution.

This first version replays saved runs. It does not monitor active simulations.
Completed artifacts are read fresh when selecting or refreshing a run.

## Verification

The loader tests require no model access:

```sh
python -m unittest visualizations.concordia_island.server_test
```

The UI has also been checked in a Chromium browser against the local
four-resident run, including playback, stage selection, persona inspection,
memory search, event filters, map-source switching, and a mobile viewport.
