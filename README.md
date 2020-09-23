# Bitbucket To Github Migration

Warning: use at your own risk, comes with no warranty or liability of any kind. 

* Set the `USER_MAPPING`, and `KNOWN_REPO_MAPPING` variables in `config.py`. See the "Find users script" section for help populating the user mapping.
* Run the main migration script and observe for errors

Main migration CLI parameters:
```
Usage: main.py [OPTIONS] BITBUCKET_REPOSITORIES...

  Migrate repositories from Bitbucket to Github

Arguments:
  BITBUCKET_REPOSITORIES...  [required]

Options:
  --github-username TEXT          [env var: GITHUB_USERNAME; default:
                                  x-access-token]

  --github-access-token TEXT      An access token is required for repository
                                  creation  [env var: GITHUB_ACCESS_TOKEN;
                                  required]

  --bitbucket-username TEXT       [env var: BITBUCKET_USERNAME; required]
  --bitbucket-password TEXT       [env var: BITBUCKET_PASSWORD; required]
  --clone / --no-clone            Skip clone/pull and repo creation in GitHub.
                                  Go directly to issues and Pull Requests
                                  migration.  [default: True]

  --migrate-issues / --no-migrate-issues
                                  Migrate the issues and pull requests
                                  [default: True]

  --specific-issues TEXT          ID of specific Bitbucket issues to migrate,
                                  will ignore all others

  --specific-pulls TEXT           ID of specific Bitbucket Pull Requests to
                                  migrate, will ignore all others

  --dry-run / --no-dry-run        Only list issues that would be
                                  created/updated. Does not apply to
                                  repository creation.  [default: False]

  --update / --no-update          Skip update of existing issues  [default:
                                  True]

  --skip-attachments / --no-skip-attachments
                                  Skip the migration of attachments
                                  (development only!)  [default: False]

  --install-completion [bash|zsh|fish|powershell|pwsh]
                                  Install completion for the specified shell.
  --show-completion [bash|zsh|fish|powershell|pwsh]
                                  Show completion for the specified shell, to
                                  copy it or customize the installation.

  --help                          Show this message and exit.
```

* Prevent commits in the original repository by changing its settings (BitBucket):
  * All users except for 'admin' should have 'read' permission only.
* Adapt the corresponding Jenkins jobs accordingly.

## Features

This script migrates:

* Bitbucket repository to GitHub repository (repository object creation in API)
* Bitbucket's attachments to Github's gists
* Bitbucket's issues to Github's issues
  * Bitbucket's issue changes and comments to Github's comments
  * Bitbucket's issue state, kind, priority and component to Github's labels
* Bitbucket's pull requests to Github's issues and pull requests
  * Closed Bitbucket's pull request to closed Github's issues
  * Open Bitbucket's pull request to Github's pull requests
  * Bitbucket's pull request activity and comments to Github's comments
  * Bitbucket's pull request state to Github's labels

The script is idempotent. It can be run several times for the same repository without overriding data from previous attempts.

## Limitations

* Issue numbers are not kept. Instead the title in GitHub contains a reference to the original ID in Bitbucket

## Find users script

For bigger organizations, filling the user mapping can be a tiresome task. The script` find_users.py` can help with this. It attempts to create the mapping for you.

Please note that neither Bitbucket nor GitHub exposes the user emails, so manual work will still be needed.

The script will do the following:
- Get all users from Bitbucket.
- If Jira credentials are supplied, get more details about Bitbucket users from the Jira API (it is worth it!)
- Get all users from GitHub
- Attempt to match names in Bitbucket (and Jira) to GitHub by removing spaces, user supplied prefixes and suffixes (e.g. your company name), email domain, spaces, diacritics
- Print the config to paste in config.py
- Print the Bitbucket users that were not matched
- Print the GitHub users that were not matched

```
Usage: find_users.py [OPTIONS]

Options:
  --github-access-token TEXT      [env var: GITHUB_ACCESS_TOKEN; required]
  --github-org TEXT               [required]
  --bitbucket-username TEXT       [env var: BITBUCKET_USERNAME; required]
  --bitbucket-password TEXT       [env var: BITBUCKET_PASSWORD; required]
  --bitbucket-team TEXT           [required]
  --user-prefix TEXT              Prefix to remove from user names to attempt
                                  matching. For example, you can remove your
                                  company name from users login.

  --user-suffix TEXT              Suffix to remove from user names to attempt
                                  matching

  --jira-url TEXT                 Your Jira instance root url, i.e.
                                  https://yourcompany.atlassian.net/. Use Jira
                                  to fetch more information about users

  --jira-username TEXT
  --jira-password TEXT
  --install-completion [bash|zsh|fish|powershell|pwsh]
                                  Install completion for the specified shell.
  --show-completion [bash|zsh|fish|powershell|pwsh]
                                  Show completion for the specified shell, to
                                  copy it or customize the installation.

  --help                          Show this message and exit.
```

## Requirements

Python 3.8+

Install requirements with
`pip3 install -r requirements.pip`
