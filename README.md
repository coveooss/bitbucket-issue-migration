# Bitbucket To Github Migration

Warning: use at your own risk, comes with no warranty or liability of any kind. 

* Set the `USER_MAPPING`, and `KNOWN_REPO_MAPPING` variables in `config.py`.
* Run the main migration script and observe for errors:

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

  --dry-run / --no-dry-run        Only list issues that would be
                                  created/updated  [default: False]

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

## Requirements

Python 3.8+

Install requirements with
`pip3 install -r requirements.pip`
