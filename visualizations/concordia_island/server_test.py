"""Tests for reading saved replay records without running a simulation."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from visualizations.concordia_island import server


def record(agent, local_step, clock, location):
  return {
      'Step': local_step,
      f'Entity [{agent}]': {
          'SituationPerception': {'State': 'A quiet morning.', 'cached': True},
          '__act__': {'Value': 'Walk to the cafe.'},
      },
      'island rules --- Event Resolution': {
          'make_observation': {agent: {'__act__': {'Value': 'You are at home.'}}},
          'resolve': {
              '__terminate__': {'Value': clock},
              '__resolution__': {'Value': 'The agent reaches the cafe.'},
              'locations': {'Value': f'{agent}: {location}\n'},
          },
      },
  }


class ReplayLoaderTest(unittest.TestCase):

  def setUp(self):
    temp_root = server.ROOT / '.tmp'
    temp_root.mkdir(exist_ok=True)
    self.directory = tempfile.TemporaryDirectory(dir=temp_root)
    self.addCleanup(self.directory.cleanup)
    self.folder = Path(self.directory.name)
    self.atlas = mock.patch.object(server, 'load_atlas', return_value={'places': []})
    self.atlas.start()
    self.addCleanup(self.atlas.stop)
    self.profiles = mock.patch.object(server, 'load_profiles', return_value={})
    self.profiles.start()
    self.addCleanup(self.profiles.stop)

  def save(self, filename, payload):
    (self.folder / filename).write_text(json.dumps(payload))

  def test_tick_grouping_uses_clock_not_async_local_step(self):
    self.save('raw_log.json', [
        record('Alice', 1, 'Thursday, January 1st, 7:00 AM', 'home'),
        record('Bob', 9, 'Thursday, January 1st, 7:00 AM', 'home'),
        record('Alice', 3, 'Thursday, January 1st, 9:00 AM', 'cafe'),
    ])
    run = server.load_run(self.folder)
    self.assertEqual([event['tick'] for event in run['events']], [1, 1, 2])
    self.assertEqual([event['local_step'] for event in run['events']], [1, 9, 3])
    self.assertEqual([agent['name'] for agent in run['agents']], ['Alice', 'Bob'])

  def test_resolution_context_and_tick_snapshot_stay_distinct(self):
    self.save('raw_log.json', [record('Alice', 1, 'Thursday, January 1st, 7:00 AM', 'home')])
    self.save('location_history.json', {'snapshots': {'1': [{'agent': 'Alice', 'location': 'cafe'}]}})
    event = server.load_run(self.folder)['events'][0]
    self.assertEqual(event['context_locations'], {'Alice': 'home'})
    self.assertEqual(event['snapshot_locations'], {'Alice': 'cafe'})
    self.assertEqual(event['action'], 'Walk to the cafe.')
    self.assertEqual(event['resolution'], 'The agent reaches the cafe.')
    self.assertTrue(event['thoughts'][0]['cached'])

  def test_final_memories_are_separate_from_event_observations(self):
    self.save('raw_log.json', [record('Alice', 1, '', 'home')])
    self.save('entity_memories.json', {'Alice': ['[self] Alice is kind.', '[observation] A later event.']})
    run = server.load_run(self.folder)
    self.assertEqual(run['agents'][0]['initial_memories'], ['[self] Alice is kind.'])
    self.assertEqual(len(run['agents'][0]['memories']), 2)
    self.assertEqual(run['events'][0]['observation'], 'You are at home.')
    self.assertIsNone(run['events'][0]['tick'])

  def test_incomplete_and_invalid_runs(self):
    self.save('raw_log.json', [])
    self.assertEqual(server.load_run(self.folder)['events'], [])
    self.save('raw_log.json', {'unexpected': 'object'})
    with self.assertRaisesRegex(ValueError, 'list'):
      server.load_run(self.folder)

  def test_discovery_ignores_non_runs_and_symlinks(self):
    valid = self.folder / 'saved'
    valid.mkdir()
    (valid / 'raw_log.json').write_text('[]')
    (self.folder / 'not_a_run').mkdir()
    (self.folder / 'shortcut').symlink_to(valid, target_is_directory=True)
    self.assertEqual([run['id'] for run in server.discover_runs(self.folder)], ['saved'])

  def test_text_extraction_and_location_parsing(self):
    self.assertEqual(server.text_value({}), '')
    self.assertEqual(server.text_value({'Value': ['one', 'two']}), 'one\ntwo')
    self.assertEqual(server.parse_locations({'Value': 'Alice: cafe\nBob: home'}), {'Alice': 'cafe', 'Bob': 'home'})


if __name__ == '__main__':
  unittest.main()
