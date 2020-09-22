from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import unicodedata

import requests
import typer
from github import Github
from github.NamedUser import NamedUser

from src.bitbucket import BitbucketExport


def clean_up_name(name: str, prefixes: Optional[List[str]], suffixes: Optional[List[str]], remove_spaces: bool = False):
    tmp = name.casefold()
    if "@" in tmp:
        tmp = tmp.split("@")[0]
    if prefixes:
        for prefix in prefixes:
            prefix = prefix.casefold()
            if tmp.startswith(prefix):
                tmp = tmp[len(prefix) :]
    if suffixes:
        for suffix in suffixes:
            suffix = suffix.casefold()
            if tmp.endswith(suffix):
                tmp = tmp[: -len(suffix)]
    tmp = tmp.strip("-_.")
    if remove_spaces:
        tmp = tmp.replace(" ", "")
    return "".join((c for c in unicodedata.normalize("NFD", tmp) if unicodedata.category(c) != "Mn"))


@dataclass
class UserName:
    name_type: str
    name: str
    cleaned_up_name: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.name_type}:{self.name}({self.cleaned_up_name})"

    def cleaned_up(self, prefixes: Optional[List[str]], suffixes: Optional[List[str]]) -> str:
        if not self.cleaned_up_name:
            self.cleaned_up_name = clean_up_name(self.name, prefixes, suffixes)

        return self.cleaned_up_name


@dataclass
class GitHubUser:
    gh_user: NamedUser
    names: List[UserName]
    taken: bool = False

    def __hash__(self):
        return self.login.__hash__()

    def __str__(self) -> str:
        return f"GitHub user {','.join([str(name) for name in self.names])}"

    @property
    def login(self) -> str:
        return self.gh_user.login


@dataclass
class BitbucketUser:
    raw: Dict[str, Any]
    names: List[UserName]
    matching_gh_user: Optional[GitHubUser] = None

    def __hash__(self):
        return self.nickname.__hash__()

    def __str__(self) -> str:
        return f"Bitbucket user {','.join([str(name) for name in self.names])}"

    @property
    def nickname(self) -> str:
        return self.raw.get("nickname", "unknown")


def main(
    github_access_token: str = typer.Option(..., envvar="GITHUB_ACCESS_TOKEN", prompt=True),
    github_org: str = typer.Option(...),
    bitbucket_username: str = typer.Option(..., envvar="BITBUCKET_USERNAME", prompt=True),
    bitbucket_password: str = typer.Option(..., envvar="BITBUCKET_PASSWORD", prompt=True),
    bitbucket_team: str = typer.Option(...),
    user_prefix: List[str] = typer.Option(
        None,
        help="Prefix to remove to user names to attempt matching. "
        "For example, you can remove your company name from users login.",
    ),
    user_suffix: List[str] = typer.Option(None, help="Suffix to remove to user names to attempt matching"),
    jira_url: str = typer.Option(
        None,
        help="Your Jira instance root url, i.e. https://yourcompany.atlassian.net/. "
        "Use Jira to fetch more information about users",
    ),
    jira_username: str = typer.Option(None),
    jira_password: str = typer.Option(None),
):

    github = Github(github_access_token, timeout=30, retry=3, per_page=100)

    print(f"Getting GitHub org {github_org} members")
    gh_org_members = github.get_organization(github_org).get_members()

    bitbucket = BitbucketExport(team_name=bitbucket_team, username=bitbucket_username, app_password=bitbucket_password)
    print(f"Getting Bitbucket team {bitbucket_team} members")
    bb_users_raw = bitbucket.get_team_users()
    print(f"Got {len(bb_users_raw)} Bitbucket users")

    bb_users: List[BitbucketUser] = []
    for bb_user_raw in bb_users_raw:
        names: List[UserName] = []
        if nickname := bb_user_raw.get("nickname"):
            names.append(UserName("Nickname", nickname, clean_up_name(nickname, user_prefix, user_suffix)))
            names.append(
                UserName("Nickname", nickname, clean_up_name(nickname, user_prefix, user_suffix, remove_spaces=True))
            )
        if display_name := bb_user_raw.get("display_name"):
            names.append(UserName("Display Name", display_name, clean_up_name(display_name, user_prefix, user_suffix)))
            names.append(
                UserName(
                    "Display Name",
                    display_name,
                    clean_up_name(display_name, user_prefix, user_suffix, remove_spaces=True),
                )
            )
        bb_users.append(BitbucketUser(raw=bb_user_raw, names=names))

    if jira_url and jira_username and jira_password:
        print(f"Getting details about Bitbucket users using Jira API")
        for i, bb_user in enumerate(bb_users):
            if (i + 1) % 10 == 0:
                print(f"{i + 1}...")
            bb_account_id = bb_user.raw.get("account_id")
            if not bb_account_id:
                continue
            jira_response = requests.get(
                f"{jira_url}/rest/api/3/user", params={"accountId": bb_account_id}, auth=(jira_username, jira_password)
            )
            if not jira_response.ok:
                print(f"Warning: cannot get Jira user from Bitbucket user {bb_user.nickname}")
                continue
            if email := jira_response.json().get("emailAddress"):
                bb_user.names.append(
                    UserName("Email (from Jira)", email, clean_up_name(email, user_prefix, user_suffix))
                )
            if display_name := jira_response.json().get("displayName"):
                bb_user.names.append(
                    UserName(
                        "Display Name (from Jira)", display_name, clean_up_name(display_name, user_prefix, user_suffix)
                    )
                )

    print(f"Getting details about all GitHub {github_org} org members")
    gh_detailed_org_members: List[NamedUser] = []
    for i, gh_org_member in enumerate(gh_org_members):
        if (i + 1) % 10 == 0:
            print(f"{i + 1}...")
        gh_detailed_org_members.append(github.get_user(gh_org_member.login))
    print(f"Got {len(gh_detailed_org_members)} GitHub users")

    gh_users: List[GitHubUser] = []
    for gh_detailed_org_member in gh_detailed_org_members:
        names: List[UserName] = []
        if gh_detailed_org_member.login:
            names.append(
                UserName(
                    "login",
                    gh_detailed_org_member.login,
                    clean_up_name(gh_detailed_org_member.login, user_prefix, user_suffix),
                )
            )
        if gh_detailed_org_member.name:
            names.append(
                UserName(
                    "name",
                    gh_detailed_org_member.name,
                    clean_up_name(gh_detailed_org_member.name, user_prefix, user_suffix),
                )
            )
            names.append(
                UserName(
                    "name",
                    gh_detailed_org_member.name,
                    clean_up_name(gh_detailed_org_member.name, user_prefix, user_suffix, remove_spaces=True),
                )
            )
        if gh_detailed_org_member.email:
            names.append(
                UserName(
                    "name",
                    gh_detailed_org_member.email,
                    clean_up_name(gh_detailed_org_member.email, user_prefix, user_suffix),
                )
            )
        gh_users.append(GitHubUser(gh_detailed_org_member, names))

    for bb_user in bb_users:
        for gh_user in gh_users:
            if gh_user.taken:
                continue
            for bb_name in bb_user.names:
                for gh_name in gh_user.names:
                    if bb_name.cleaned_up_name == gh_name.cleaned_up_name:
                        gh_user.taken = True
                        bb_user.matching_gh_user = gh_user
                        print(
                            f"Matched Bitbucket user {bb_user} with GitHub user {gh_user} on Bitbucket "
                            f"{bb_name.name_type} ({bb_name.name}) to GitHub {gh_name.name_type} ({gh_name.name})"
                        )
                        break
                if bb_user.matching_gh_user:
                    break
            if bb_user.matching_gh_user:
                break
        else:
            print(f"Unable to find GitHub user for Bitbucket user {bb_user}")

    print("\nUser mapping to copy to config.py:\nUSER_MAPPING: Dict[str, str] = {")
    for bb_user in [user for user in bb_users if user.matching_gh_user]:
        print(f'    "{bb_user.nickname}": "{bb_user.matching_gh_user.login}",')
    print("}\n")

    print("Bitbucket orphan users:")
    for bb_user in sorted([user for user in bb_users if not user.matching_gh_user], key=lambda u: u.nickname):
        print(f"{bb_user}")
    print()

    print("GitHub orphan users:")
    for gh_orphan in sorted([user for user in gh_users if not user.taken], key=lambda u: u.login):
        print(f"{gh_orphan}")


if __name__ == "__main__":
    typer.run(main)
