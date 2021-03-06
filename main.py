#!/usr/bin/env python3
import datetime
import os
import pathlib
from subprocess import check_call
from typing import List, Optional

import typer
from git import Repo
from github import Github
from github.GithubException import GithubException, UnknownObjectException

import config
from src import migrate_discussions
from src.bitbucket import BitbucketExport

ROOT = os.path.abspath(os.path.dirname(__file__))
MIGRATION_DATA_DIR = os.path.join(ROOT, "migration_data")


def bitbucket_repo_url(repo, username, password):
    return "https://" + username + ":" + password + "@bitbucket.org/" + repo


def github_repo_url(repo):
    return "git@github.com:" + repo + ".git"


def execute(cmd, *args, **kwargs):
    print("> '{}'".format(cmd))
    check_call(cmd, *args, shell=True, **kwargs)


def step(msg):
    now = datetime.datetime.now()
    time = now.strftime("%Y-%m-%d %H:%M:%S")
    print("\n[{}] === {}...".format(time, msg))


def is_github_repo_empty(github, gh_repo):
    repo = github.get_repo(gh_repo)
    try:
        repo.get_contents("/")
        return False
    except GithubException as e:
        return e.args[1]["message"] == "This repository is empty."


def main(
    bitbucket_repositories: List[str],
    github_username: str = typer.Option("x-access-token", envvar="GITHUB_USERNAME"),
    github_access_token: str = typer.Option(
        ..., envvar="GITHUB_ACCESS_TOKEN", help="An access token is required for repository creation", prompt=True
    ),
    bitbucket_username: str = typer.Option(..., envvar="BITBUCKET_USERNAME", prompt=True),
    bitbucket_password: str = typer.Option(..., envvar="BITBUCKET_PASSWORD", prompt=True),
    clone: bool = typer.Option(
        True, help="Skip clone/pull and repo creation in GitHub. Go directly to issues and Pull Requests migration."
    ),
    migrate_issues: bool = typer.Option(True, help="Migrate the issues and pull requests"),
    specific_issues: Optional[List[str]] = typer.Option(
        None, help="ID of specific Bitbucket issues to migrate, will ignore all others"
    ),
    specific_pulls: Optional[List[str]] = typer.Option(
        None, help="ID of specific Bitbucket Pull Requests to migrate, will ignore all others"
    ),
    dry_run: bool = typer.Option(
        False, help="Only list issues that would be created/updated. Does not apply to repository creation."
    ),
    update: bool = typer.Option(True, help="Skip update of existing issues"),
    skip_attachments: bool = typer.Option(False, help="Skip the migration of attachments (development only!)"),
):
    """Migrate repositories from Bitbucket to Github"""
    repositories_to_migrate = {bb_repo: config.KNOWN_REPO_MAPPING[bb_repo] for bb_repo in bitbucket_repositories}
    print("Bitbucket repositories to be migrated: {}".format(", ".join(repositories_to_migrate.keys())))

    github = Github(github_access_token, timeout=30, retry=3, per_page=100)

    if clone:
        for bb_repo, gh_repo in repositories_to_migrate.items():
            bitbucket_client = BitbucketExport(bb_repo, username=bitbucket_username, app_password=bitbucket_password)

            step(f"Ensuring GitHub repo exists")
            try:
                gh_repo_api = github.get_repo(gh_repo)
            except UnknownObjectException:
                print(f"Repo {gh_repo} does not exist in GitHub, creating...")
                organization_name, repo_name = gh_repo.split("/")
                gh_repo_api = github.get_organization(organization_name).create_repo(
                    repo_name,
                    description=(
                        f"{bitbucket_client.get_repo_description()} "
                        f"Migrated from Bitbucket https://bitbucket.org/{bb_repo}"
                    ),
                    private=True,
                    has_issues=True,
                    auto_init=False,
                    allow_squash_merge=True,
                )

            step(f"Checking local repository for '{gh_repo}'")
            git_folder = os.path.join(MIGRATION_DATA_DIR, "github", gh_repo)

            if not os.path.isdir(git_folder):
                pathlib.Path(git_folder).mkdir(parents=True, exist_ok=True)
                print(f"Cloning Bitbucket repo https://bitbucket.org/{bb_repo} into {git_folder}")
                repo = Repo.clone_from(f"https://bitbucket.org/{bb_repo}", git_folder)
                repo.config_writer().set_value("core", "ignoreCase", "false")
            else:
                repo = Repo(git_folder)

            # Find or create a remote for Bitbucket
            bb_remote = None
            for remote in repo.remotes:
                if any("bitbucket.org" in url for url in remote.urls):
                    bb_remote = remote
                    continue
            if not bb_remote:
                bb_remote = repo.create_remote(
                    "bitbucket", f"https://{bitbucket_username}:{bitbucket_password}@bitbucket.org/{bb_repo}"
                )
            print(f"Pulling Bitbucket repo https://bitbucket.org/{bb_repo} into {git_folder}")
            bb_remote.pull()

            step(f"Adding/Ensuring remote github '{gh_repo}' to local git repository")
            for remote in repo.remotes:
                if remote.name == "github":
                    gh_remote = remote
                    break
            else:
                gh_remote = repo.create_remote(
                    "github", f"https://{github_username}:{github_access_token}@github.com/{gh_repo}.git"
                )

            step(f"Pushing Bitbucket repo '{bb_repo}' to GitHub repo '{gh_repo}'")

            # --mirror pushes the remotes too, let's push all branches and tags

            # Pushes branches from the Bitbucket remote to the GitHub one without needing to create them locally
            gh_remote.push(f"refs/remotes/{bb_remote.name}/*:refs/heads/*")
            gh_remote.push(":HEAD")  # Remove "HEAD" branch created by the above command
            gh_remote.push("refs/tags/*:refs/tags/*")

            # Set main branch if different
            bb_main_branch = bitbucket_client.get_repo_main_branch()
            if bb_main_branch:
                gh_repo_default_branch = gh_repo_api.default_branch
                if bb_main_branch != gh_repo_default_branch:
                    print(f"Setting GitHub repo default branch to {bb_main_branch} (was {gh_repo_default_branch})")
                    gh_repo_api.edit(default_branch=bb_main_branch)

    if migrate_issues:
        for bb_repo, gh_repo in repositories_to_migrate.items():
            step(f"Migrate issues and pull requests of Bitbucket repository '{bb_repo}' to GitHub")
            migrate_discussions.main(
                github_access_token,
                bb_repo,
                gh_repo,
                bitbucket_username,
                bitbucket_password,
                skip_attachments=skip_attachments,
                update=update,
                specific_issues=specific_issues,
                specific_pulls=specific_pulls,
                dry_run=dry_run,
            )


if __name__ == "__main__":
    typer.run(main)
