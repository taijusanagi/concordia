"""Local, read-only replay of Concordia Island run artifacts.

Run from the repository root:
  python -m visualizations.concordia_island.server
"""

from __future__ import annotations

import argparse
from datetime import datetime
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).with_name('static')
COLORS = ['#c26b4f', '#6e8195', '#8d9762', '#b28a58', '#9d7997', '#5f9990']
THINKING_ORDER = [
    'SituationPerception', 'RelevantMemories', 'WorkingMemory',
    'SelfPerception', 'EmotionalExperience', 'EmotionalExpression',
    'MovementDecision', 'PersonBySituation',
]


def read_json(path: Path, default: Any = None) -> Any:
  return json.loads(path.read_text()) if path.is_file() else default


def text_value(value: Any) -> str:
  if isinstance(value, dict):
    if not value:
      return ''
    for key in ('State', 'Value', 'Expression Narrative', 'Summary'):
      if key in value and value[key] is not None:
        return text_value(value[key])
    return json.dumps(value, ensure_ascii=False, indent=2)
  if isinstance(value, list):
    return '\n'.join(text_value(item) for item in value)
  return str(value) if value is not None else ''


def parse_locations(value: Any) -> dict[str, str]:
  result = {}
  for line in text_value(value).splitlines():
    if ': ' in line:
      name, location = line.split(': ', 1)
      result[name.strip()] = location.strip()
  return result


def clock_sort(label: str) -> tuple:
  clean = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', label)
  try:
    # A leap year permits sorting month/day labels without inventing a run year.
    stamp = datetime.strptime(clean + ', 2000', '%A, %B %d, %I:%M %p, %Y')
    return (stamp.month, stamp.day, stamp.hour, stamp.minute)
  except ValueError:
    return (99, 99, 99, label)


def discover_runs(runs_dir: Path) -> list[dict]:
  if not runs_dir.is_dir():
    return []
  result = []
  for folder in runs_dir.iterdir():
    if not folder.is_dir() or folder.is_symlink():
      continue
    if not (folder / 'raw_log.json').is_file():
      continue
    try:
      state = read_json(folder / 'simulation_state.json', {})
      perf = read_json(folder / 'performance.json', {})
      result.append({
          'id': folder.name, 'agents': state.get('agents'),
          'ticks': state.get('ticks'), 'engine': perf.get('engine_type', ''),
          'modified': (folder / 'raw_log.json').stat().st_mtime,
      })
    except (ValueError, OSError):
      continue
  return sorted(result, key=lambda run: run['modified'], reverse=True)


def load_atlas(atlas_id: str) -> dict:
  # Atlas coordinates are illustrative map units, not physical trajectories.
  import yaml  # Island already depends on PyYAML.
  path = ROOT / 'examples/concordia_island/data/atlas' / f'{atlas_id}.yaml'
  if not path.is_file():
    return {'meta': {'display_name': 'Island'}, 'places': [], 'sim_ids': {}}
  return yaml.safe_load(path.read_text())


def load_profiles(names: list[str], root: Path = ROOT) -> dict:
  profiles = {}
  # Only local generated populations; never read credentials or arbitrary paths.
  for base in (root / '.tmp', root / 'examples/concordia_island/personas/populations'):
    if not base.exists():
      continue
    for name in names:
      filename = name.replace(' ', '_').lower() + '_persona.json'
      for path in sorted(base.glob(f'*/{filename}')):
        if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
          continue
        try:
          profile = read_json(path, {})
          if profile.get('name') == name:
            profiles.setdefault(name, profile)
        except (ValueError, OSError):
          continue
  return profiles


def load_run(folder: Path) -> dict:
  raw = read_json(folder / 'raw_log.json', [])
  if not isinstance(raw, list):
    raise ValueError('raw_log.json must contain a list of recorded events.')
  state = read_json(folder / 'simulation_state.json', {})
  performance = read_json(folder / 'performance.json', {})
  history = read_json(folder / 'location_history.json', {})
  memories = read_json(folder / 'entity_memories.json', {})
  events, names = [], []
  for row in raw:
    if not isinstance(row, dict):
      continue
    entity_key = next((key for key in row if key.startswith('Entity [')), None)
    if not entity_key or not isinstance(row[entity_key], dict):
      continue
    name = entity_key[len('Entity ['):-1]
    if name not in names:
      names.append(name)
    components = row[entity_key]
    gm_key = next((key for key, value in row.items()
                   if isinstance(value, dict) and 'resolve' in value), None)
    gm = row.get(gm_key, {})
    resolve = gm.get('resolve', {})
    observed = gm.get('make_observation', {}).get(name, {})
    clock = text_value(resolve.get('__terminate__', {})).strip()
    if not clock:
      clock = text_value(gm.get('next_acting', {}).get('__terminate__', {})).strip()
    observation = text_value(observed.get('__act__', {}))
    resolution = text_value(resolve.get('__resolution__', {}))
    if not resolution:
      resolution = text_value(resolve.get('__act__', {}))
    if not resolution and gm_key and ' --- ' in gm_key:
      resolution = gm_key.split(' --- ', 1)[1]
    ordered = [key for key in THINKING_ORDER if key in components]
    ordered.extend(key for key in components if key not in ordered
                   and key not in ('Instructions', 'LocationInfo', 'ScheduleAwareness',
                                   '__observation__', '__act__', 'CurrentLocation'))
    thoughts = []
    for key in ordered:
      value = components[key]
      thoughts.append({
          'id': key, 'label': re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', key),
          'text': text_value(value),
          'cached': bool(value.get('cached', False)) if isinstance(value, dict) else False,
          'record': value,
      })
    events.append({
        'id': len(events), 'agent': name, 'clock': clock,
        'local_step': row.get('Step'), 'observation': observation,
        'action': text_value(components.get('__act__', {})),
        'resolution': resolution, 'thoughts': thoughts,
        'context_locations': parse_locations(resolve.get('locations', {})),
        'gm_record': resolve,
    })
  clocks = sorted({event['clock'] for event in events if event['clock']}, key=clock_sort)
  clock_ticks = {clock: index + 1 for index, clock in enumerate(clocks)}
  for event in events:
    event['tick'] = clock_ticks.get(event['clock'])
    tick_rows = history.get('snapshots', {}).get(str(event['tick']), [])
    event['snapshot_locations'] = {row['agent']: row['location'] for row in tick_rows}
  profiles = load_profiles(names)
  first_context = events[0]['context_locations'] if events else {}
  agents = []
  for index, name in enumerate(names):
    profile = profiles.get(name, {})
    bank = memories.get(name, [])
    # Final memory banks are deliberately separate from event-time cognition.
    initial = [str(memory) for memory in bank
               if str(memory).startswith(('[self]', '[background]', '[formative]'))]
    agents.append({
        'name': name, 'color': COLORS[index % len(COLORS)],
        'profile': profile, 'memories': bank, 'initial_memories': initial,
        'home': profile.get('home_place') or first_context.get(name, ''),
        'work': profile.get('work_place', ''),
        'events': [event['id'] for event in events if event['agent'] == name],
    })
  hints = ' '.join(str(item) for item in first_context.values())
  context_text = text_value(events[0]['gm_record'].get('locations_constant', {})) if events else ''
  atlas_id = 'brecksville' if ('brecksville' in context_text.lower()
                             or 'millbrook' in hints) else 'concordia_island'
  return {
      'id': folder.name, 'state': state, 'performance': performance,
      'agents': agents, 'events': events, 'atlas': load_atlas(atlas_id),
      'clocks': clocks,
      'notes': [
          'Replay follows saved log order, not measured async execution timing.',
          'Movement connects recorded positions; walking routes are illustrative.',
          'Tick snapshots and per-event Game Master context are distinct records.',
      ],
  }


class Handler(SimpleHTTPRequestHandler):
  def __init__(self, *args, runs_dir: Path, **kwargs):
    self.runs_dir = runs_dir.resolve()
    super().__init__(*args, directory=str(STATIC), **kwargs)

  def send_json(self, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode()
    self.send_response(status)
    self.send_header('Content-Type', 'application/json; charset=utf-8')
    self.send_header('Content-Length', str(len(body)))
    self.send_header('Cache-Control', 'no-store')
    self.end_headers()
    self.wfile.write(body)

  def do_GET(self) -> None:
    path = unquote(urlsplit(self.path).path)
    if path == '/api/runs':
      self.send_json({'runs': discover_runs(self.runs_dir)})
      return
    if path.startswith('/api/runs/'):
      name = path.removeprefix('/api/runs/')
      folder = self.runs_dir / name
      if (not name or '/' in name or '\\' in name or name in ('.', '..')
          or not folder.is_dir() or folder.is_symlink()
          or folder.resolve().parent != self.runs_dir):
        self.send_json({'error': 'Run not found.'}, HTTPStatus.NOT_FOUND)
        return
      try:
        self.send_json(load_run(folder))
      except (ValueError, OSError, KeyError, TypeError) as error:
        self.send_json({'error': f'Cannot read this run: {error}'}, 422)
      return
    # Restrict static reads to this app, including symlink resolution.
    target = (STATIC / path.lstrip('/')).resolve()
    if not target.is_relative_to(STATIC.resolve()):
      self.send_error(HTTPStatus.NOT_FOUND)
      return
    super().do_GET()


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--runs-dir', type=Path, default=ROOT / 'local_runs')
  parser.add_argument('--port', type=int, default=8766)
  args = parser.parse_args()
  handler = partial(Handler, runs_dir=args.runs_dir)
  with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
    print(f'Island replay: http://127.0.0.1:{args.port}', flush=True)
    print(f'Reading runs from {args.runs_dir.resolve()}', flush=True)
    try:
      server.serve_forever()
    except KeyboardInterrupt:
      pass


if __name__ == '__main__':
  main()
