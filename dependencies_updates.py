# Example usage:
# python dependencies_updates.py
# python dependencies_updates.py -c 2022-10-24
# python dependencies_updates.py -c 2022-10-03 -s
# DEBUG=1 python dependencies_updates.py
# TODO: rename results folder to `snapshots`
# TODO: add `diffs` folder to host the diff csvs and flip the dates in the names
# TODO: rename script to `dependency_snapshots`

import argparse
from genericpath import isdir, isfile
import sys
import requests
import os
import re
import json
import urllib.parse
import posixpath
import datetime
import pathlib
import io
import csv

ROOT_DIR = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(ROOT_DIR, 'results')
CONFIGS_DIR = os.path.join(ROOT_DIR, 'configs')

def run():
  parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('-c', '--compare-to', help='Previous result to compare this run against')
  parser.add_argument('-f', '--config-file',
    help='Config file basename (without extension, json assumed) to use'
  )

  sys.exit(DependencyUpdates(parser.parse_args()).run())

def parse_gemfile_content(gemfile_lock_content):
  ret = {}

  current_section = None
  previous_level = None
  for line in gemfile_lock_content.split('\n'):
    line_stripped = line.strip()

    if len(line_stripped) <= 0:
      continue

    if re.search(r'^[^\s]', line):
      current_section = line_stripped
      previous_level = ''
      continue

    # Ensures going at most 1 layer deep into a section
    if previous_level not in ['', re.search(r'^(\s+)', line).group(1)]:
      continue

    if current_section is None:
      continue

    result = None
    if current_section == 'GEM':
      result = re.search(r'^(\s+)([^\s]+)\s\(((?:\d\.?)+)\)\s*$', line)
    elif current_section == 'RUBY VERSION':
      result = re.search(r'^(\s+)(ruby)\s+((?:\d\.?)+).*?$', line)

    if result:
      previous_level = result.group(1)
      dependency_name = result.group(2)
      version_parts = [int(version_part) for version_part in result.group(3).strip('.').split('.')]
      if dependency_name in ret:
        print(f'WARNING! looks like {dependency_name} appears twice in the Gemfile!')
      ret[dependency_name] = version_parts

  return ret

def parse_ruby_version_content(ruby_version_content):
  result = re.search(r'^\s*(?:ruby\-)?((?:\d\.?)+).*?$', ruby_version_content, re.MULTILINE)
  if result is not None:
    version_parts = [int(version_part) for version_part in result.group(1).strip('.').split('.')]
    while len(version_parts) < 3:
      version_parts.append(0)
    return version_parts
  else:
    return None

def basenames_without_extension(dirpath, prefix='', extension='txt'):
  ret = {}
  for file in pathlib.Path(dirpath).glob(f'{prefix}*.{extension}'):
    ret[os.path.splitext(os.path.basename(file))[0]] = file
  return ret

def create_file(filepath, content_str):
  with open(filepath, 'w') as outfile:
    outfile.write(content_str)

'''
Creates a file with the passed basename, content, and extension. If a file with the same name
exists, it appends -v1, -v2, -v3, etc to the basename until no file with tha name exists.

It returns the basename it ended up with
'''
def create_result_file(basename, content_str, extension = 'txt'):
  new_basename = basename
  filepath = os.path.join(RESULTS_DIR, f'{new_basename}.{extension}')
  idx = 1
  while os.path.isfile(filepath):
    new_basename = f'{basename}-v{idx}'
    filepath = os.path.join(RESULTS_DIR, f'{new_basename}.{extension}')
    idx += 1

  create_file(filepath, content_str)
  print(f'Wrote {os.path.relpath(filepath, start=ROOT_DIR)}')
  return new_basename

'''
[1, 0, 0]
[2, 0, 0]
=> [0, 1]

[1, 0, 0]
[5, 0, 0]
=> [0, 4]

[1, 0, 0]
[1, 1, 0]
=> [1, 1]

[1, 0, 0]
[1, 0, 1]
=> [2, 1]

[1, 2, 3]
[1, 2, 3, 4]
=> [3, 4]

[1, 2]
[1, 2, 3, 4]
=> [2, 3]

[1]
[1, 0, 0, 0]
=> [-1, 0]
'''
def compare_version_parts(version_parts_1, version_parts_2):
  if version_parts_1 == version_parts_2:
    return [-1, 0]

  idx = 0
  max_len = max(len(version_parts_1), len(version_parts_2))
  while idx < max_len:
    version_part_1 = version_parts_1[idx] if idx < len(version_parts_1) else 0
    version_part_2 = version_parts_2[idx] if idx < len(version_parts_2) else 0

    if version_part_1 != version_part_2:
      return [idx, version_part_2 - version_part_1]
    idx += 1

  return [-1, 0]

class DependencyUpdates:
  def __init__(self, args):
    super(self.__class__) # TODO is this necessary? update GemfileLockParser if so.
    self._args = args
    self._config_dict = None
    self._default_branches = {}
    self._github_token = os.environ.get('GITHUB_TOKEN')

  def gh_pull_file(self, repo_shortname, filepath):
    if len(os.environ.get('DEBUG', '')) > 0 or self._config_dict.get('force_debug_mode', False):
      directory = os.path.join(self._config_dict['debug']['repos_dir'], repo_shortname)
      if os.path.isdir(directory):
        with open(os.path.join(directory, filepath), 'r') as file:
          return file.read()
      else:
        return ''

    path = posixpath.join(
      self._config_dict['owner'],
      repo_shortname,
      self.gh_default_branch(repo_shortname),
      filepath
    )

    return self.gh_api_call(path, 'raw.githubusercontent.com').text or ''

  def gh_api_call(self, path, domain = 'api.github.com'):
    url = urllib.parse.urljoin(f'https://{domain}', path)
    return requests.get(url, headers={'Authorization': f'Bearer {self._github_token}'})

  def gh_default_branch(self, repo_shortname):
    if repo_shortname not in self._default_branches:
      owner = self._config_dict['owner']
      response = self.gh_api_call(f'/repos/{owner}/{repo_shortname}')
      self._default_branches[repo_shortname] = response.json()['default_branch']

    return self._default_branches[repo_shortname]

  def build_new_result(self):
    result = {}

    for repo_shortname, repo_config in self._config_dict['repos'].items():
      gemfile_name = repo_config.get('gemfile_name', 'Gemfile.lock')
      gemfile_location = posixpath.join(repo_config.get('gemfile_dir', ''), gemfile_name)
      gemfile_content = self.gh_pull_file(repo_shortname, gemfile_location.strip('/'))
      dependencies_dict = parse_gemfile_content(gemfile_content)

      if 'ruby' not in dependencies_dict:
        ruby_version_location = posixpath.join(repo_config.get('gemfile_dir', ''), '.ruby-version')
        ruby_version_content = self.gh_pull_file(repo_shortname, ruby_version_location.strip('/'))
        ruby_version_parts = parse_ruby_version_content(ruby_version_content)
        if ruby_version_parts:
          dependencies_dict['ruby'] = ruby_version_parts

      result[repo_shortname] = dependencies_dict

    return result

  '''
  Returns a list that can be used to create a csv. Each element in this list is a list with 6
  elements:
  1. Repo Name. E.g. 'vice-backend'.
  1. Dependency Name. E.g. 'rails'.
  2. Update Type. One of 'Upgrade', 'Downgrade', 'Removal', 'Addition'.
  3. Level. One of 'Major', 'Minor', 'Patch', 'Old'
  4. From Version. E.g. [4, 2, 2]
  5. To Version. E.g. [5, 1, 0]
  '''
  def compare_results(self, result_old, result_new):
    ret_groups = [
      'Major Upgrade',
      'Major Downgrade',
      'Minor Upgrade',
      'Minor Downgrade',
      'Patch Upgrade',
      'Patch Downgrade',
      'Old Upgrade',
      'Old Downgrade',
      'Addition',
      'Removal'
    ]

    ret = []
    for repo_shortname, repo_config in self._config_dict['repos'].items():
      if (repo_shortname not in result_new) or (repo_shortname not in result_old):
        continue

      repo_updates = {}
      for ret_group in ret_groups:
        repo_updates[ret_group] = []

      dependency_names = set(
        list(result_new[repo_shortname].keys()) +
        list(result_old[repo_shortname].keys())
      )

      for dependency_name in dependency_names:
        new_version_parts = result_new[repo_shortname].get(dependency_name)
        old_version_parts = result_old[repo_shortname].get(dependency_name)

        if dependency_name not in result_old[repo_shortname]:
          repo_updates['Addition'].append([
            repo_shortname,
            dependency_name,
            'Addition',
            'Major',
            None,
            new_version_parts
          ])
          continue

        if dependency_name not in result_new[repo_shortname]:
          repo_updates['Removal'].append([
            repo_shortname,
            dependency_name,
            'Removal',
            'Major',
            old_version_parts,
            None
          ])
          continue

        if new_version_parts == old_version_parts:
          continue

        diff, diff_amount = compare_version_parts(old_version_parts, new_version_parts)

        if diff == -1:
          # case when one version is [1, 3], and the other [1, 3, 0, 0,...]
          continue

        diff_str = {0: 'Major', 1: 'Minor', 2: 'Patch'}.get(diff, 'Old')
        upgrade_downgrade = 'Downgrade' if diff_amount < 0 else 'Upgrade'
        ret_group = f'{diff_str} {upgrade_downgrade}'

        repo_updates[ret_group].append([
          repo_shortname,
          dependency_name,
          upgrade_downgrade,
          diff_str,
          old_version_parts,
          new_version_parts
        ])

      for ret_group in ret_groups:
        for row in repo_updates[ret_group]:
          ret.append(row)
    return ret

  '''
  Returns an array with three elements:
  1. An integer exit code that can be used as an exit code from the script
  2. A friendly description of the result.
    - If the exit code is non-zero, this is a description of the error
    - Otherwise, it is information that can be sent to the user like config file used.
  3. Config file basename without the extension, or None if the exit code is non-zero
  4. A dictionary if the exit code is zero, or None otherwise.
  '''
  def create_config_dict(self):
    if len(self._args.config_file or '') > 0:
      config_file_basename, config_file_extension = os.path.splitext(
        os.path.basename(self._args.config_file)
      )

      if len(config_file_extension) <= 0:
        config_file_extension = '.json'

      if config_file_extension != '.json':
        return [1, 'Non json config files are invalid', None, None]

      potential_config_basenames = [config_file_basename]
    else:
      potential_config_basenames = ['default', 'default_sample']

    config_filepath = None
    config_basename = None
    for potential_config_basename in potential_config_basenames:
      potential_config_filepath = os.path.join(CONFIGS_DIR, f'{potential_config_basename}.json')
      if os.path.isfile(potential_config_filepath):
        config_filepath = potential_config_filepath
        config_basename = potential_config_basename
        break

    if config_filepath is None:
      potential_config_basenames = list(
        basenames_without_extension(CONFIGS_DIR, extension='json').keys()
      )
      potential_config_basenames.sort()
      msg = 'Possible options for --config-file argument:\n' + '\n'.join(potential_config_basenames)
      return [1, msg, None, None]

    with open(config_filepath, 'r') as config_file:
      msg = f'Using config file {os.path.basename(config_filepath)}'
      return [0, msg, config_basename, json.load(config_file)]

  def run(self):
    exit_code, msg, config_basename, config_dict = self.create_config_dict()
    if msg is not None:
      print(msg)
    if exit_code != 0:
      return exit_code
    self._config_dict = config_dict

    result_old = None

    if len(self._args.compare_to or '') > 0:
      prev_result_basenames = basenames_without_extension(RESULTS_DIR, extension='json')
      if self._args.compare_to in prev_result_basenames:
        with open(prev_result_basenames[self._args.compare_to], 'r') as file:
          result_old = json.load(file)
      else:
        sorted_options = list(prev_result_basenames.keys())
        sorted_options.sort(reverse = True)
        print('Possible options for --compare-to argument:\n' + '\n'.join(sorted_options))
        return 1

    result_new = self.build_new_result()
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    result_new_prefix = f'{config_basename}_'
    basename = f'{result_new_prefix}{today_str}'
    basename = create_result_file(basename, json.dumps(result_new, indent=2), 'json')

    if result_old is not None:
      output = io.StringIO()
      writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC)
      writer.writerow([
        'Repo Name',
        'Dependency Name',
        'Update Type',
        'Level',
        'From Version',
        'To Version'
      ])
      for row in self.compare_results(result_old, result_new):
        writer.writerow(row)

      if self._args.compare_to.startswith(result_new_prefix):
        basename = f'{basename}_{self._args.compare_to[len(result_new_prefix):]}'
      else:
        basename = f'{basename}_{self._args.compare_to}'
      create_result_file(basename, output.getvalue(), 'csv')

    return 0

if __name__ == "__main__":
  run()
