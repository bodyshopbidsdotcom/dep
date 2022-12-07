# Dep

This script pulls dependencies (only gem and ruby at the moment) versions out of the `Gemfile.lock` and stores them in snapshot files in `json` format for easy consumption. So, it transforms a `Gemfile.lock` into `json`. It then uses these json files to create diffs between two snapshots to track dependency updates over time.

Currently, the script takes snapshots of gem versions and `ruby` versions. If the `ruby` version is not called out in the `Gemfile.lock` file, it looks at the `.ruby-version` file in the directory specified by the [`repos.repo-name.gemfile_dir`](#config-reposrepo-namegemfile_dir) config.

## Environment

This script was built in the following environment, and is therefore the recommended setup:

- MacOS 12.6 or newer.
- Python 3.
- [`pyenv`](https://formulae.brew.sh/formula/pyenv) as the Python Version Manager and [`pyenv-virtualenv`](https://formulae.brew.sh/formula/pyenv) as the package manager. The file `.python-version` is read by `pyenv` and switches to this python version when `cd`ing into this directory.

## Setup

1. If you use `pyenv` and `pyenv-virtualenv`, install the version of python (if you don't have it already in the `pyenv versions` list) and create the virtualenv:

    ```shell
    pyenv install `cat .python-version`
    pyenv virtualenv `cat .python-version` dep
    ```

1. Install the required package dependencies:

    ```shell
    pip install -r requirements.txt
    ```

1. In order to pull data from Github, the environment variable `GITHUB_TOKEN` must be set with permissions to read the repositories specified in the [config file](#config-files). Go [here](https://github.com/settings/tokens) to create one if you don't already have one.

1. Create your `configs/default.json` [config file](#config-files). You can start from `cp configs/default_sample.json configs/default.json`

## Usage

If you're using `pyenv` and `pyenv-virtualenv`, you need to activate the virtualenv with `pyenv activate dep`, assuming you called the virtualenv `dep` at creation during [setup](#setup).

By default, if you just run `./dep`, the script will try to use the config file `configs/default.json`. If this file doesn't exist, it will fail. You can explicitly specify which config file to use with the `-c` flag. For example:

```shell
./dep -c services
```

This will make the script use the config file `configs/services.json`.

Every time the script runs successfully, it will create a json [snapshot file](#snapshots) in `snapshots/`.

Use the `-d` flag to create a [diff file](#diffs) against an old snapshot. Diff files are csv files stored in `diffs/`.

### Take a snapshot of dependency versions from 2 github repos

- Use a config file like this:

    ```json
    {
      "owner": "github-owner",
      "repos": {
        "repo1": { },
        "repo2": { },
      }
    }
    ```

### Take a snapshot of dependency versions from 2 **local** repos

- Use a config file like this:

    ```json
    {
      "repos": {
        "repo1": { },
        "repo2": { },
      },
      "force_debug_mode": true,
      "debug": {
        "repos_dir": "/Users/reposdirectory"
      }
    }
    ```

### Take a snapshot and diff it against and old run

- Let's say you have a config file like `configs/services.json` like this:

    ```json
    {
      "owner": "github-owner",
      "repos": {
        "repo1": { },
        "repo2": { },
      }
    }
    ```

- Let's also say you have a bunch of snapshots taken

    ```plaintext
    snapshots/
        |
        +----- services_2022-10-01.json
        |
        +----- services_2022-11-01.json
    ```

- One can capture the dependency changes between one of these old snapshots and today with

    ```shell
    ./dep -c services -d services_2022-11-01
    ```

    If today is `2022-12-01`, this will create a diff file `diffs/services_2022-11-01_2022-12-01.csv`

### Compare dependency changes for two different `Gemfile.lock` files from the same repo

This is useful when you are in the process of upgrading rails and you run tests on two different versions of rails using different `Gemfile.lock` files following a process similar to [Github's](https://github.blog/2018-09-28-upgrading-github-from-rails-3-2-to-5-2/#how-did-we-do-it).

For example, let's say you have a repo called `repo1` which is upgrading from Rails 3 to Rails 4, using `Gemfile.lock` and `Gemfile_next.lock` respectively. Here's how we can get the diff:

- Use 2 different config files, let's call them `core_r3.json` and `core_r4.json`

    ```javascript
    // core_r3.json
    {
      "owner": "github-owner",
      "repos": {
        "repo1": { "gemfile_name": "Gemfile.lock" }
      }
    }
    ```

    ```javascript
    // core_r4.json
    {
      "owner": "github-owner",
      "repos": {
        "repo1": { "gemfile_name": "Gemfile_next.lock" }
      }
    }
    ```

- Take a snapshot using `core_r3.json` with:

    ```shell
    $ ./dep -c core_r3.json
    Using config file core_r3.json
    Wrote snapshots/core_r3_2022-12-07.json
    ```

- Take a snapshot using `core_r4.json` and diff it against the snapshot just taken for Rails 3:

    ```shell
    $ ./dep -c core_r4.json -d core_r3_2022-12-07
    Wrote snapshots/core_r4_2022-12-07-v1.json
    Wrote diffs/core_r3_2022-12-07_core_r4_2022-12-07.csv
    ```

    That's it. The diff file `diffs/core_r3_2022-12-07_core_r4_2022-12-07.csv` will contain all the changes.

## Config files

These are `json` files that live in the `configs/` directory have a defined structure. If a config file is not specified, the script is going to use `configs/default.json`.

All config files are gitignored.

Config files have the following structure:

```javascript
{
  "owner": "<github-org-or-owner>",
  "repos": {
    "<repo-name-1>": {
      "gemfile_dir": "/path/to/directory",
      "gemfile_name": "Gemfile.lock"
    },
    "<repo-name-2>": { ... },
    // ...
  },
  "force_debug_mode": false,
  "debug": {
      "repos_dir": "/path/to/directory"
  }
}
```

### Config: `owner`

---

```javascript
{
  "owner": "<github-org-or-owner>",
  // ...
}
```

Used when making API calls to github. For example when pulling `Gemfile.lock` files, the API call path uses an owner name.

### Config: `repos`

---

```javascript
{
  "repos": { /* ... */ },
  // ...
}
```

Repos to report on. Each key within this dictionary is a repo name. The values are configured as follows.

### Config: `repos.repo-name.gemfile_dir`

---

```javascript
{
  "repos": {
    "<repo-name>": {
      "gemfile_dir":"/path/to/directory",
      // ...
    }
   },
  // ...
}
```

Defaults to `"/"` if this is not present. This is the directory where the script will search for the `Gemfile.lock` and `.ruby-version` (if the version is not found within the `Gemfile.lock` file) files.

### Config: `repos.repo-name.gemfile_name`

---

```javascript
{
  "repos": {
    "<repo-name>": {
      "gemfile_name": "Gemfile.lock",
      // ...
    }
   },
  // ...
}
```

Defaults to `"Gemfile.lock"`. This is the name of the Gemfile itself within the repo. Together with the `gemfile_dir` config, this is how the script finds these files. If you don't specify these configs the script will try to find `"/Gemfile.lock"`

### Config: `force_debug_mode`

---

```javascript
{
  "force_debug_mode": false,
  // ...
}
```

This config allows you to avoid making any API calls to github and only look at the `repos` locally. It will look for them in the directory specified by the `debug.repos_dir` config.

This config name will likely change in the future to `force_local_mode`.

### Config: `debug`

---

```javascript
{
  "debug": { /* ... */ },
  // ...
}
```

Settings relevant only when the script runs in debug mode.

This config name will likely change in the future to `local`.

### Config: `debug.repos_dir`

---

```javascript
{
  "debug": {
    "repos_dir": '/path/to/directory',
    // ...
  }
  // ...
}
```

When running in debug mode, this is the directory where the script tries to find the `repos` instead of making API calls to Github.

## Snapshots

Snapshots are gitignored json files stored in `snapshots/`.

They contain all the dependency versions for each repo specified in the [repos](#config-repos) config. The script consumes these files to create the [diffs](#diffs). A new snapshot is created every time the script runs successfully.

### Snapshots Name Format

The format is `snapshots/<config>_<date>.json` where `<config>` is the name of the config file used to take the snapshot, and the `<date>` is the day when the snapshot was taken. For example `snapshots/default_2022-12-07.json`.

## Diffs

Diffs are gitignored csv files stored in `diffs/`. They're created only when passing the `-c` flag.

### Diffs Name Format

The format is `diffs/<config-from>_<date-from>_<config-to>_<date-to>.csv` where:

- `<config-from>` is the name of the config file used in the snapshot we're diffing from.
- `<date-from>` is the date of the snapshot we're diffing from.
- `<config-to>` is the name of the config file used in the snapshot we're diffing to. I.e. the snapshot we took as part of this run.
- `<date-to>` is the date of the snapshot we're diffing to. I.e. the snapshot we took as part of this run.

When both the snapshot we're diffing from and the snapshot we're diffing to use the same config file, the `_<config-to>` part is removed. E.g. `diffs/default_2022-11-01_2022-12-01.csv`
