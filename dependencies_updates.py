# Example usage:
# python dependencies_updates.py
# python dependencies_updates.py -c 2022-10-24
# python dependencies_updates.py -c 2022-10-03 -s
# DEBUG=1 python dependencies_updates.py

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

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')

def run():
  parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('-c', '--compare-to', help='Previous result to compare this run against')
  parser.add_argument('-s', '--strict',
    default = False,
    action = 'store_true',
    help = 'Only look at dependencies in the follow_dependencies config list'
  )

  sys.exit(DependencyUpdates().run(parser.parse_args()))

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

def basenames_without_extension(dirpath, extension):
  ret = {}
  for file in pathlib.Path(dirpath).glob(f'*.{extension}'):
    ret[os.path.splitext(os.path.basename(file))[0]] = file
  return ret

def create_file(filepath, content_str):
  with open(filepath, 'w') as outfile:
    outfile.write(content_str)
  print(f'Wrote: {filepath}')

def create_result_file(basename, content_str):
  create_file(os.path.join(RESULTS_DIR, basename), content_str)

'''
[1, 0, 0]
[2, 0, 0]
0

[1, 0, 0]
[1, 1, 0]
1

[1, 0, 0]
[1, 0, 1]
2

[1, 2, 3]
[1, 2, 3, 4]
3

[1, 2]
[1, 2, 3, 4]
2
'''
def compare_version_parts(version_parts_1, version_parts_2):
  if version_parts_1 == version_parts_2:
    return -1

  idx = 0
  max_len = min(len(version_parts_1), len(version_parts_2))
  while idx < max_len:
    if version_parts_1[idx] != version_parts_2[idx]:
      return idx
    idx += 1

  return idx

class DependencyUpdates:
  def __init__(self):
    super(self.__class__) # TODO is this necessary? update GemfileLockParser if so.
    self._config_dict = None
    self._default_branches = {}
    self._github_token = os.environ.get('GITHUB_TOKEN')

    config_file = 'config.json'
    if not os.path.isfile(config_file):
      config_file = 'config_sample.json'

    self._config_dict = None
    with open(config_file, 'r') as config_file:
      self._config_dict = json.load(config_file)

  def _gh_pull_file(self, repo_shortname, filepath):
    if len(os.environ.get('DEBUG', '')) > 0:
      directory = os.path.join(self._config_dict['debug']['repos_dir'], repo_shortname)
      if os.path.isdir(directory):
        with open(os.path.join(directory, filepath), 'r') as file:
          return file.read()
      else:
        return ''

    url = urllib.parse.urljoin('https://raw.githubusercontent.com', posixpath.join(
      self._config_dict['owner'],
      repo_shortname,
      self._default_branch(repo_shortname),
      filepath
    ))

    return requests.get(url, headers={'Authorization': f'Bearer {self._github_token}'}).text or ''

  def _gh_api_call(self, path):
    url = urllib.parse.urljoin('https://api.github.com', path)
    return requests.get(url, headers={'Authorization': f'Bearer {self._github_token}'})

  def _default_branch(self, repo_shortname):
    if repo_shortname not in self._default_branches:
      owner = self._config_dict['owner']
      response = self._gh_api_call(f'/repos/{owner}/{repo_shortname}')
      self._default_branches[repo_shortname] = response.json()['default_branch']

    return self._default_branches[repo_shortname]

  def _version_for_ruby(self, repo_shortname):
    repo_config = self._config_dict['repos'][repo_shortname]

    version_string_regexes = [
      ['Gemfile.lock', r'^\s{3}ruby\s+((?:\d\.?)+).*?$'],
      ['.ruby-version', r'^\s*((?:\d\.?)+).*?$']
    ]

    for version_string_regex in version_string_regexes:
      location = posixpath.join(repo_config.get('gemfile_dir', ''), version_string_regex[0])
      location = location.strip('/')
      file_content = self._gh_pull_file(repo_shortname, location) or ''
      result = re.search(version_string_regex[1], file_content, re.MULTILINE)
      if result is not None:
        version_parts_str_list = result.group(1).strip('.').split('.')
        version_parts = [int(version_part) for version_part in version_parts_str_list]
        while len(version_parts) < 3:
          version_parts.append(0)

        return version_parts

    return None

  def _version_for_gem(self, repo_shortname, gem_name):
    pass

  '''
  Returns the version for `dependency_name` that `repo_shortname` uses
  IMPORTANT: Updates the `result_store` hash if it's present
  '''
  def version(self, repo_shortname, dependency_name, result_store = None):
    version = None

    if dependency_name == 'ruby':
      version = self._version_for_ruby(repo_shortname)
    else:
      version = self._version_for_gem(repo_shortname, dependency_name)

    if version is not None and result_store is not None:
      if repo_shortname not in result_store:
        result_store[repo_shortname] = {}
      result_store[repo_shortname][dependency_name] = version

    return version

  def build_new_result(self):
    result = {}

    for repo_shortname, repo_config in self._config_dict['repos'].items():
      gemfile_location = posixpath.join(repo_config.get('gemfile_dir', ''), 'Gemfile.lock')
      gemfile_content = self._gh_pull_file(repo_shortname, gemfile_location.strip('/'))
      dependencies_dict = parse_gemfile_content(gemfile_content)

      if 'ruby' not in dependencies_dict:
        ruby_version_location = posixpath.join(repo_config.get('gemfile_dir', ''), '.ruby-version')
        ruby_version_content = self._gh_pull_file(repo_shortname, ruby_version_location.strip('/'))
        ruby_version_parts = parse_ruby_version_content(ruby_version_content)
        if ruby_version_parts:
          dependencies_dict['ruby'] = ruby_version_parts

      result[repo_shortname] = dependencies_dict

    return result

  def compare_results(self, result_old, result_new, strict = False):
    print_message_types = [
      'Major',
      'Minor',
      'Patch',
      'Old',
      'Added',
      'Removed'
    ]

    ret = []
    for repo_shortname, repo_config in self._config_dict['repos'].items():
      if (repo_shortname not in result_new) or (repo_shortname not in result_old):
        continue

      print_messages = {}
      for print_message_type in print_message_types:
        print_messages[print_message_type] = []

      dependency_names = set(
        list(result_new[repo_shortname].keys()) +
        list(result_old[repo_shortname].keys())
      )

      for dependency_name in dependency_names:
        if strict and dependency_name not in self._config_dict.get('follow_dependencies', []):
          continue

        if dependency_name not in result_old[repo_shortname]:
          msg = f'[{repo_shortname}] Added dependency: {dependency_name}'
          print_messages['Added'].append(msg)
          continue

        if dependency_name not in result_new[repo_shortname]:
          msg = f'[{repo_shortname}] Removed dependency: {dependency_name}'
          print_messages['Removed'].append(msg)
          continue

        new_version_parts = result_new[repo_shortname][dependency_name]
        old_version_parts = result_old[repo_shortname][dependency_name]

        if new_version_parts == old_version_parts:
          continue

        diff = compare_version_parts(new_version_parts, old_version_parts)
        diff_str = {0: 'Major', 1: 'Minor', 2: 'Patch'}.get(diff, 'Old')
        from_str = '.'.join([str(part) for part in old_version_parts])
        to_str = '.'.join([str(part) for part in new_version_parts])
        print_messages[diff_str].append(f'[{repo_shortname}] ' \
          f'{diff_str} version update for {dependency_name}: {from_str} -> {to_str}'
        )

      for print_message_type in print_message_types:
        for print_message in print_messages[print_message_type]:
          ret.append(print_message)
    return ret

  def run(self, args):
    result_old = None

    if len(args.compare_to or '') > 0:
      prev_result_basenames = basenames_without_extension(RESULTS_DIR, 'json')
      if args.compare_to in prev_result_basenames:
        with open(prev_result_basenames[args.compare_to], 'r') as file:
          result_old = json.load(file)
      else:
        sorted_options = list(prev_result_basenames.keys())
        sorted_options.sort(reverse = True)
        print('Possible options for compare-to argument:\n' + '\n'.join(sorted_options))
        return 1

    result_new = self.build_new_result()
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    create_result_file(f'{today_str}.json', json.dumps(result_new, indent=2))

    if result_old is not None:
      basename = f'{args.compare_to}_{today_str}.txt'
      content = '\n'.join(self.compare_results(result_old, result_new, args.strict))
      create_result_file(basename, content)

    return 0

if __name__ == "__main__":
  run()
