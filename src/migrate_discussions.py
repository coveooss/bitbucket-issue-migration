#!/usr/bin/env python3
import re
import time
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urlparse

import requests
import typer
from dateutil import parser
from github.Gist import Gist
from github.InputFileContent import InputFileContent
from github.Issue import Issue
from github.PullRequest import PullRequest

import config
from src.bitbucket import BitbucketExport
from src.github import GithubImport


@dataclass
class MigrationConfig:
    bb_repo: str
    bb_export: BitbucketExport
    gh_repo: str
    gh_import: GithubImport
    skip_attachments: bool
    update: bool
    dry_run: bool


def map_bb_state_to_gh_state(bb_issue: Dict):
    bb_state = bb_issue["state"]
    if bb_state in config.OPEN_ISSUE_OR_PULL_REQUEST_STATES:
        return "open"
    else:
        return "closed"


def map_bb_user_to_gh_user(bb_user: Dict):
    if bb_user is None:
        return None

    if not (nickname := bb_user.get("nickname")):
        return None
    return config.USER_MAPPING.get(nickname)


def map_bb_repo_to_gh_repo(bb_repo: str):
    if bb_repo not in config.KNOWN_REPO_MAPPING:
        return None
    return config.KNOWN_REPO_MAPPING[bb_repo]


def map_bb_state_to_gh_labels(bb_issue: Dict):
    bb_state = bb_issue["state"]
    if bb_state in config.STATE_MAPPING:
        label = config.STATE_MAPPING[bb_state]
        if label is None:
            return []
        else:
            return [label]
    else:
        print(f"Warning: ignoring bitbucket issue state '{bb_state}'")
        return []


def map_bb_priority_to_gh_labels(bb_issue: Dict):
    bb_priority = bb_issue["priority"]
    if bb_priority in config.PRIORITY_MAPPING:
        label = config.PRIORITY_MAPPING[bb_priority]
        if label is None:
            return []
        else:
            return [label]
    else:
        print(f"Warning: ignoring bitbucket issue priority '{bb_priority}'")
        return []


def map_bb_kind_to_gh_labels(bb_issue):
    bb_kind = bb_issue["kind"]
    if bb_kind in config.KIND_MAPPING:
        label = config.KIND_MAPPING[bb_kind]
        if label is None:
            return []
        else:
            return [label]
    else:
        print(f"Warning: ignoring bitbucket issue kind '{bb_kind}'")
        return []


def map_bb_component_to_gh_labels(bb_issue):
    if bb_issue["component"] is None:
        return []

    bb_component = bb_issue["component"]["name"]
    if bb_component in config.COMPONENT_MAPPING:
        label = config.COMPONENT_MAPPING[bb_component]
        if label is None:
            return []
        else:
            return [label]
    else:
        print(f"Warning: ignoring bitbucket issue component '{bb_component}'")
        return []


def format_bb_user_mention(bb_user: Dict, capitalize=False) -> str:
    if bb_user is None or "nickname" not in bb_user:
        return f"{'A' if capitalize else 'a'} former bitbucket user (account deleted)"
    else:
        if (gh_user := map_bb_user_to_gh_user(bb_user)) is None:
            return f"{'B' if capitalize else 'b'}itbucket user **{bb_user['nickname']}**"
        else:
            return f"**@{gh_user}**"


def time_string_to_date_string(timestring: str) -> str:
    datetime = parser.parse(timestring)
    return datetime.strftime("%Y-%m-%d %H:%M")


def convert_date(bb_date: str) -> str:
    """Convert the date from Bitbucket format to GitHub format."""
    # '2012-11-26T09:59:39+00:00'
    if m := re.search(r"(\d\d\d\d-\d\d-\d\d)T(\d\d:\d\d:\d\d)", bb_date):
        return f"{m.group(1)}T{m.group(2)}Z"

    raise RuntimeError(f"Could not parse date: {bb_date}")


def construct_gh_comment_body(bb_comment: Dict[str, Any], run_data: MigrationConfig) -> str:
    sb = []
    comment_created_on = time_string_to_date_string(bb_comment["created_on"])
    user_mention = format_bb_user_mention(bb_comment["user"], capitalize=True)
    sb.append(f"> {user_mention} commented on {comment_created_on}\n")
    if "inline" in bb_comment:
        bb_comment = run_data.bb_export.get_detailed_comment(bb_comment)
        inline_data = bb_comment["inline"]
        file_path = inline_data["path"]

        if inline_data["outdated"]:
            message_prefix = "Outdated location"
        else:
            message_prefix = "Location"

        show_snippet = False
        snippet_file_url = ""
        if False and "code" in bb_comment["links"]:
            # Disabled, because the hg_commit looks wrong
            diff_url = urlparse(bb_comment["links"]["code"]["href"])
            snippet_commit = diff_url.path.split("..")[-1]
            if snippet_commit is not None:
                snippet_file_url = f"https://github.com/{map_bb_repo_to_gh_repo(run_data.bb_export.get_repo_full_name())}/blob/{snippet_commit}/{file_path}"
                snippet_url_status = requests.get(snippet_file_url).status_code
                show_snippet = snippet_url_status == 200
                if snippet_url_status == 404:
                    print(f"Warning: page '{snippet_file_url}' does not exist")
                if snippet_url_status not in (200, 404):
                    print(f"Warning: page '{snippet_file_url}'")

        sb.append(">\n")
        if inline_data["from"] is None and inline_data["to"] is None:
            # No line
            if show_snippet:
                sb.append(f"> **{message_prefix}:** [`{file_path}`]({snippet_file_url})\n")
            else:
                sb.append(f"> **{message_prefix}:** `{file_path}`\n")
        elif None in (inline_data["from"], inline_data["to"]) or inline_data["from"] == inline_data["to"]:
            # Single line
            the_line = inline_data["to"] if inline_data["from"] is None else inline_data["from"]
            sb.append(f"> **{message_prefix}:** line {the_line} of `{file_path}`\n")
            if show_snippet:
                sb.append(f"> {snippet_file_url}#L{the_line}\n")
        else:
            # Multiple lines
            from_line = inline_data["from"]
            to_line = inline_data["to"]
            sb.append(f"> **{message_prefix}:** lines {from_line}-{to_line} of `{file_path}`\n")
            if show_snippet:
                sb.append(f"> {snippet_file_url}#L{from_line}-L{to_line}\n")
    sb.append("\n")

    if raw_content := bb_comment["content"]["raw"]:
        sb.append(raw_content)

    return "".join(sb)


def construct_gh_issue_body(
    bb_issue: Dict[str, Any], bb_attachments: Dict[str, Any], attachment_gist_by_issue_id: Dict[int, Any]
):
    sb = []

    # Header
    created_on = time_string_to_date_string(bb_issue["created_on"])
    updated_on = time_string_to_date_string(bb_issue["updated_on"])
    sb.append("> Created by " + format_bb_user_mention(bb_issue["reporter"]) + " on " + created_on + "\n")
    if created_on != updated_on:
        sb.append("> Last updated on " + updated_on + "\n")

    # Content
    sb.append("\n")
    sb.append(bb_issue["content"]["raw"])
    sb.append("\n")

    # Attachments
    if bb_attachments:
        sb.append("\n")
        sb.append("---\n")
        sb.append("\n")
        sb.append("Attachments:\n")
        for name in bb_attachments.keys():
            issue_id = bb_issue["id"]
            if issue_id in attachment_gist_by_issue_id:
                attachments_gist = attachment_gist_by_issue_id[issue_id]
                sb.append(f"* [**`{name}`**]({attachments_gist.files[name].raw_url})\n")
            else:
                print(f"Error: missing gist for the attachments of issue #{issue_id}.")
                sb.append(f"* **`{name}`** (missing link)\n")

    return "".join(sb)


def construct_gh_pull_request_body(bb_pull: Dict[str, Any], run_data: MigrationConfig):
    sb = []

    # Header
    created_on = time_string_to_date_string(bb_pull["created_on"])
    updated_on = time_string_to_date_string(bb_pull["updated_on"])
    if bb_pull["author"] is None:
        author_msg = ""
    else:
        author_msg = "by " + format_bb_user_mention(bb_pull["author"]) + " "
    sb.append(">  **Pull request** :twisted_rightwards_arrows: created " + author_msg + "on " + created_on + "\n")
    if created_on != updated_on:
        sb.append("> Last updated on " + updated_on + "\n")
    sb.append(f"> Original Bitbucket pull request id: {bb_pull['id']}\n")

    if bb_pull["participants"]:
        sb.append(">\n")
        sb.append("> Participants:\n")
        sb.append(">\n")
        for participant in bb_pull["participants"]:
            sb.append(f"> * {format_bb_user_mention(participant['user'])}")
            if participant["role"] == "REVIEWER":
                sb.append(" (reviewer)")
            if participant["approved"]:
                sb.append(" :heavy_check_mark:")
            sb.append("\n")

    sb.append(">\n")
    source = bb_pull["source"]
    if source["repository"] is None and source["commit"] is None:
        source_bb_branch = source["branch"]["name"]
        sb.append(f"> Source: unknown commit on branch `{source_bb_branch}` of an unknown repo\n")
    else:
        source_branch = source["branch"]["name"]
        source_hash = source["commit"]["hash"]
        source_gh_repo = map_bb_repo_to_gh_repo(run_data.bb_export.get_repo_full_name())
        if source_hash is None:
            message = f"> Source: unidentified commit on branch `{source_branch}`\n"
        else:
            message = (
                f"> Source: https://github.com/{source_gh_repo}/commit/{source_hash} on branch `{source_branch}`\n"
            )
        sb.append(message)

    destination = bb_pull["destination"]
    destination_brepo = destination["repository"]["full_name"]
    destination_branch = destination["branch"]["name"]
    destination_bcommit = destination["commit"]
    destination_hash = destination_bcommit["hash"] if destination_bcommit else None
    destination_grepo = map_bb_repo_to_gh_repo(destination_brepo)
    if destination_brepo != run_data.bb_export.get_repo_full_name():
        print(
            f"Error: the destination of a pull request, '{destination_brepo}', "
            f"is not '{run_data.bb_export.get_repo_full_name()}'."
        )

    if not destination_hash:
        message = f"> Destination: https://github.com/{destination_grepo} on branch {destination_branch}\n"
    else:
        message = (
            f"> Destination: https://github.com/{destination_grepo}/commit/{destination_hash} "
            f"on branch `{destination_branch}`\n"
        )
    sb.append(message)

    if bb_pull["merge_commit"] is not None:
        merge_bb_repo = run_data.bb_export.get_repo_full_name()
        merge_bb_hash = bb_pull["merge_commit"]["hash"]
        merge_gh_repo = map_bb_repo_to_gh_repo(merge_bb_repo)
        merge_gh_hash = merge_bb_hash
        sb.append(f"> Merge commit: https://github.com/{merge_gh_repo}/commit/{merge_gh_hash}\n")

    sb.append(">\n")
    sb.append(f"> State: **`{bb_pull['state']}`**\n")

    # Content
    sb.append("\n")
    sb.append(bb_pull["description"])
    sb.append("\n")

    return "".join(sb)


def construct_gh_comment_body_for_change(bb_change: Dict[str, Any]):
    created_on = time_string_to_date_string(bb_change["created_on"])
    sb: List[str] = []
    for changed_key, change in bb_change["changes"].items():
        old = change.get("old")
        new = change.get("new")
        if changed_key == "assignee_account_id":
            continue
        if not sb:
            user_mention = format_bb_user_mention(bb_change["user"], capitalize=True)
            sb.append(f"> {user_mention} on {created_on}:\n")
        if changed_key == "content":
            sb.append("> * edited the description\n")
        elif changed_key == "title":
            sb.append("> * edited the title\n")
        elif changed_key == "assignee":
            old_assignee = format_bb_user_mention({"nickname": old}) if old else "(none)"
            new_assignee = format_bb_user_mention({"nickname": new}) if new else "(none)"
            sb.append(f"> * changed the assignee from {old_assignee} to {new_assignee}\n")
        else:
            sb.append(f"> * changed `{changed_key}` from `{old or '(none)'}` to `{new or '(none)'}`\n")
    return "".join(sb)


def construct_gh_comment_body_for_update_activity(update_activity: Dict[str, Any]):
    on_date = time_string_to_date_string(update_activity["date"])
    if update_activity["author"] is None:
        return f"> the status has been changed to `{update_activity['state']}` on {on_date}"
    else:
        user_mention = format_bb_user_mention(update_activity["author"], capitalize=True)
        return f"> {user_mention} changed the status to `{update_activity['state']}` on {on_date}"


def construct_gh_comment_body_for_approval_activity(approval_activity: Dict[str, Any]) -> str:
    user_mention = format_bb_user_mention(approval_activity["user"], capitalize=True)
    on_date = time_string_to_date_string(approval_activity["date"])
    return f"> {user_mention} approved :heavy_check_mark: the pull request on {on_date}"


def construct_gh_issue_comments(
    bb_comments: Dict[int, Dict[str, Any]], run_data: MigrationConfig
) -> List[Dict[str, str]]:
    comments = []

    for comment_id, bb_comment in bb_comments.items():
        try:
            # Skip empty comments
            if bb_comment["content"]["raw"] is None:
                continue
            # Skip deleted comments
            if bb_comment.get("deleted"):
                continue
            # Construct comment
            comment = {
                "body": construct_gh_comment_body(bb_comment, run_data),
                "created_at": convert_date(bb_comment["created_on"]),
            }
            comments.append(comment)
        except Exception as ex:
            print(ex)
            print(f"Failed to get comment id {comment_id}")

    comments.sort(key=lambda x: x["created_at"])
    return comments


def construct_gist_description_for_issue_attachments(bb_issue: Dict[str, Any], bb_export: BitbucketExport) -> str:
    gh_repo_name = map_bb_repo_to_gh_repo(bb_export.get_repo_full_name())
    return f"Attachments for issue https://github.com/{gh_repo_name}/issues/{bb_issue['id']}"


def construct_gist_from_bb_issue_attachments(
    bb_issue: Dict[str, Any], bb_export: BitbucketExport
) -> Optional[Dict[str, Union[str, Dict[str, InputFileContent]]]]:
    issue_id = bb_issue["id"]
    bb_attachments = bb_export.get_issue_attachments(issue_id)

    if not bb_attachments:
        return None

    gist_description = construct_gist_description_for_issue_attachments(bb_issue, bb_export)
    gist_files = {"# README.md": InputFileContent(gist_description)}

    for name in bb_attachments.keys():
        content = bb_export.get_issue_attachment_content(issue_id, name)
        if len(content) == 0:
            print(f"Warning: file '{name}' of bitbucket issue {bb_export.get_repo_full_name()}/#{issue_id} is empty.")
            content = "(empty)"
        elif len(content) > 500 * 1000:
            print(
                f"Error: file '{name}' of bitbucket issue {bb_export.get_repo_full_name()}/#{issue_id} is too big and "
                "cannot be uploaded as a gist file. This has to be done manually."
            )
            content = "(too big)"
        gist_files[name] = InputFileContent(content)

    return {"description": gist_description, "files": gist_files}


def construct_gh_issue_comments_for_changes(bb_changes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    comments = []
    for bb_change in bb_changes:
        body = construct_gh_comment_body_for_change(bb_change)
        # Skip empty comments
        if body:
            comment = {"body": body, "created_at": convert_date(bb_change["created_on"])}
            comments.append(comment)
    return comments


def construct_gh_issue_comments_for_activity(bb_activity: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    comments = []
    for single_activity in bb_activity:
        if "approval" in single_activity:
            approval_activity = single_activity["approval"]
            activity_date = approval_activity["date"]
            body = construct_gh_comment_body_for_approval_activity(approval_activity)
        else:
            # comment activity or update
            continue
        comment = {"body": body, "created_at": convert_date(activity_date)}
        comments.append(comment)
    return comments


def construct_gh_issue_from_bb_issue(
    bb_issue: Dict[str, Any], run_data: MigrationConfig, attachment_gist_by_issue_id: Dict[int, Gist]
):
    issue_id = bb_issue["id"]
    bb_attachments = run_data.bb_export.get_issue_attachments(issue_id)
    bb_comments = run_data.bb_export.get_issue_comments(issue_id)
    bb_changes = run_data.bb_export.get_issue_changes(issue_id)

    issue_body = construct_gh_issue_body(bb_issue, bb_attachments, attachment_gist_by_issue_id)

    # Construct comments
    comments: List[Dict[str, str]] = []
    comments += construct_gh_issue_comments(bb_comments, run_data)
    comments += construct_gh_issue_comments_for_changes(bb_changes)
    comments.sort(key=lambda x: x["created_at"])

    # Construct labels
    labels = (
        map_bb_kind_to_gh_labels(bb_issue)
        + map_bb_state_to_gh_labels(bb_issue)
        + map_bb_priority_to_gh_labels(bb_issue)
        + map_bb_component_to_gh_labels(bb_issue)
    )

    return {
        "issue": {
            "title": bb_issue["title"],
            "body": issue_body,
            "created_at": convert_date(bb_issue["created_on"]),
            "updated_at": convert_date(bb_issue["updated_on"]),
            "assignee": map_bb_user_to_gh_user(bb_issue["assignee"]),
            "closed": map_bb_state_to_gh_state(bb_issue) == "closed",
            "labels": list(set(labels)),
        },
        "comments": comments,
    }


def bb_pull_is_closed(bb_pull: Dict) -> bool:
    return map_bb_state_to_gh_state(bb_pull) == "closed"


def bb_pull_maps_gh_pull(bb_pull: Dict) -> bool:
    if bb_pull_is_closed(bb_pull):
        return False

    base_branch = bb_pull["destination"]["branch"]["name"]
    head_branch = bb_pull["source"]["branch"]["name"]
    # Don't open a Github PR if the base or head branch is unknown
    if base_branch is None or head_branch is None:
        print(
            f"Warning: bitbucket pull request #{bb_pull['id']} is open but the source or destination branch does not "
            "exist. Consider closing the pull request."
        )
    if base_branch is None or head_branch is None:
        return False

    return True


def build_gh_title_from_bb_pull(bb_pull: Dict) -> str:
    return f"[BB pr#{bb_pull['id']}] " + bb_pull["title"]


def construct_gh_comments_from_bb_pull(bb_pull: Dict[str, Any], run_data: MigrationConfig) -> List[Dict[str, str]]:
    pull_id = bb_pull["id"]
    bb_comments = run_data.bb_export.get_pull_comments(pull_id)
    bb_activity = run_data.bb_export.get_pull_activity(pull_id)

    comments: List[Dict[str, str]] = []
    comments += construct_gh_issue_comments(bb_comments, run_data)
    comments += construct_gh_issue_comments_for_activity(bb_activity)
    comments.sort(key=lambda x: x["created_at"])

    return comments


def construct_gh_issue_from_bb_pull(bb_pull: Dict[str, Any], run_data: MigrationConfig) -> Dict[str, Any]:
    return {
        "issue": {
            "title": build_gh_title_from_bb_pull(bb_pull),
            "body": construct_gh_pull_request_body(bb_pull, run_data),
            "created_at": convert_date(bb_pull["created_on"]),
            "updated_at": convert_date(bb_pull["updated_on"]),
            "assignee": map_bb_user_to_gh_user(bb_pull["author"]),
            "closed": bb_pull_is_closed(bb_pull),
            "labels": list(set(["pull request"] + map_bb_state_to_gh_labels(bb_pull))),
        },
        "comments": construct_gh_comments_from_bb_pull(bb_pull, run_data),
    }


def construct_gh_pull_from_bb_pull(bb_pull: Dict[str, Any], run_data: MigrationConfig) -> Dict[str, Any]:
    base_branch = bb_pull["destination"]["branch"]["name"]
    head_branch = bb_pull["source"]["branch"]["name"]
    return {
        "pull": {
            "title": build_gh_title_from_bb_pull(bb_pull),
            "body": construct_gh_pull_request_body(bb_pull, run_data),
            "assignees": [gh_user for gh_user in [map_bb_user_to_gh_user(bb_pull["author"])] if gh_user is not None],
            "reviewers": [
                gh_user for gh_user in map(map_bb_user_to_gh_user, bb_pull["reviewers"]) if gh_user is not None
            ],
            "closed": bb_pull_is_closed(bb_pull),
            "labels": list(set(["pull request"] + map_bb_state_to_gh_labels(bb_pull))),
            "base": base_branch,
            "head": head_branch,
        },
        "comments": construct_gh_comments_from_bb_pull(bb_pull, run_data),
    }


def construct_empty_gh_issue(issue_id, from_bb_pull=False):
    issue_data = {
        "issue": {
            "title": f"Deleted issue #{issue_id}",
            "body": "(deleted)",
            "created_at": "2020-01-01T12:00:00Z",
            "updated_at": "2020-01-01T12:00:00Z",
            "assignee": None,
            "closed": True,
            "labels": ["pull request"] if from_bb_pull else [],
        },
        "comments": [],
    }
    return {"type": "issue", "data": issue_data}


def find_bb_id_in_gh_issue_or_pull(
    gh_issue: Optional[Issue], gh_pull: Optional[PullRequest]
) -> Tuple[Optional[int], Optional[int]]:
    issue_re = re.compile(r"\[BB i#(?P<issue_id>\d+)]")
    pull_re = re.compile(r"\[BB pr#(?P<pull_id>\d+)]")

    to_match: List[str] = []
    if gh_issue:
        to_match += [gh_issue.title, gh_issue.body]
    if gh_pull:
        to_match += [gh_pull.title, gh_pull.body]

    issue_id = None
    pull_id = None
    for str_to_match in to_match:
        if match := re.match(issue_re, str_to_match):
            issue_id = int(match.group("issue_id"))
        if match := re.match(pull_re, str_to_match):
            pull_id = int(match.group("pull_id"))

    return issue_id, pull_id


def print_limit(run_data: MigrationConfig) -> None:
    remaining_limit = run_data.gh_import.get_remaining_rate_limit()
    print(f"Remaining GitHub limit: {remaining_limit}")
    if remaining_limit < 1:
        time.sleep(2)


def bitbucket_to_github(run_data: MigrationConfig):
    # Get existing data from GitHub
    gh_issues = run_data.gh_import.get_issues()
    bb_issue_id_to_gh_issue: Dict[int, Issue] = {}
    bb_pull_id_to_gh_issue: Dict[int, Issue] = {}

    # Associate existing GitHub data with Bitbucket data from the title
    for issue_id, gh_issue in gh_issues.items():
        bb_issue_id, bb_pull_id = find_bb_id_in_gh_issue_or_pull(gh_issue, None)
        if bb_issue_id:
            bb_issue_id_to_gh_issue[bb_issue_id] = gh_issue
        if bb_pull_id:
            bb_pull_id_to_gh_issue[bb_pull_id] = gh_issue

    gh_pulls = run_data.gh_import.get_pulls()
    bb_pull_id_to_gh_pull: Dict[int, PullRequest] = {}
    for pull_number, gh_pull in gh_pulls.items():
        _, bb_pull_id = find_bb_id_in_gh_issue_or_pull(None, gh_pull)
        if bb_pull_id:
            bb_pull_id_to_gh_pull[bb_pull_id] = gh_pull

    # Get existing Bitbucket issues
    bb_issues = run_data.bb_export.get_issues()

    # Migrate attachments
    attachment_gist_by_issue_id: Dict[int, Gist] = {}
    if not run_data.skip_attachments:
        print("Migrate bitbucket attachments to github...")
        for bb_issue in bb_issues:
            issue_id = bb_issue["id"]
            print(f"Migrate attachments for bitbucket issue #{issue_id}...")
            print_limit(run_data)
            bb_attachments = run_data.bb_export.get_issue_attachments(issue_id)
            if bb_attachments:
                gist_data = construct_gist_from_bb_issue_attachments(bb_issue, run_data.bb_export)
                gist = run_data.gh_import.get_or_create_gist_by_description(gist_data)
                attachment_gist_by_issue_id[issue_id] = gist
    else:
        print("Warning: migration of Bitbucket attachments to GitHub has been skipped.")

    print("Transferring Bitbucket issues...")
    for bb_issue in bb_issues:
        print_limit(run_data)

        bb_issue_id = bb_issue["id"]
        existing_issue = bb_issue_id_to_gh_issue.get(bb_issue_id)
        if existing_issue:
            if run_data.update:
                print(f"Updating GitHub issue #{existing_issue.number} from Bitbucket issue #{bb_issue_id}")
                data = construct_gh_issue_from_bb_issue(bb_issue, run_data, attachment_gist_by_issue_id)
                run_data.gh_import.update_issue_with_comments(existing_issue, data, run_data.dry_run)
            else:
                print(
                    f"Skipping update of issue #{existing_issue.number} from Bitbucket issue #{bb_issue_id}... "
                    "(--skip-update flag)"
                )
        else:
            print(f"Creating GitHub issue from Bitbucket issue #{bb_issue_id}")
            data = construct_gh_issue_from_bb_issue(bb_issue, run_data, attachment_gist_by_issue_id)
            run_data.gh_import.create_issue_with_comments(data, run_data.dry_run)

    print("Transferring Bitbucket Pull Requests")
    for bb_pull in run_data.bb_export.get_pulls():
        print_limit(run_data)

        bb_pull_id = bb_pull["id"]
        if bb_pull_maps_gh_pull(bb_pull):
            # Construct a GH PR
            existing_pull = bb_pull_id_to_gh_pull.get(bb_pull_id)
            if existing_pull:
                if run_data.update:
                    print(f"Updating github pull #{existing_pull.number} from Bitbucket pull #{bb_pull_id}...")
                    data = construct_gh_pull_from_bb_pull(bb_pull, run_data)
                    run_data.gh_import.update_pull_with_comments(existing_pull, data, run_data.dry_run)
                else:
                    print(
                        f"Skipping update of pull #{existing_pull.number} from Bitbucket pull #{bb_pull_id}... "
                        "(--skip-update flag)"
                    )
            else:
                print(f"Creating GitHub pull from Bitbucket pull #{bb_pull_id}...")
                data = construct_gh_pull_from_bb_pull(bb_pull, run_data)
                try:
                    run_data.gh_import.create_pull_with_comments(data, run_data.dry_run)
                except:
                    print(f"Problem creating GitHub pull from Bitbucket pull #{bb_pull_id}#")
                    traceback.print_exc()

        else:
            # Construct a GH Issue
            existing_issue = bb_pull_id_to_gh_issue.get(bb_pull["id"])
            if existing_issue:
                if run_data.update:
                    print(f"Updating github issue #{existing_issue.number} from Bitbucket pull #{bb_pull['id']}...")
                    data = construct_gh_issue_from_bb_pull(bb_pull, run_data)
                    run_data.gh_import.update_issue_with_comments(existing_issue, data, run_data.dry_run)
                else:
                    print(
                        f"Skipping update of issue #{existing_issue} from Bitbucket pull #{bb_pull_id}... "
                        "(--skip-update flag)"
                    )

            else:
                print(f"Creating github issue from Bitbucket pull #{bb_pull_id}...")
                data = construct_gh_issue_from_bb_pull(bb_pull, run_data)
                run_data.gh_import.create_issue_with_comments(data, run_data.dry_run)


def main(
    github_access_token: str = typer.Option(..., help="Github Access Token", envvar="GITHUB_ACCESS_TOKEN"),
    bitbucket_repository: str = typer.Option(
        ..., help="Full name of the Bitbucket repository (e.g. yourteamname/your-repo-name)"
    ),
    github_repository: str = typer.Option(
        ..., help="Full name of the Github repository (e.g. yourorganizationanme/your-repo-name)"
    ),
    bitbucket_username: str = typer.Option(..., help="BitBucket username with access to repository"),
    bitbucket_password: str = typer.Option(...),
    skip_attachments: bool = typer.Option(False, help="Skip the migration of attachments (development only!)"),
    update: bool = typer.Option(True, help="Update Github issues and Pull Requests from Bitbucket if both exists"),
    dry_run: bool = typer.Option(False, help="Skip calls to GitHub and print the payload instead"),
) -> None:
    """Migrate Bitbucket issues and pull requests to Github"""
    run_data = MigrationConfig(
        bb_repo=bitbucket_repository,
        bb_export=BitbucketExport(bitbucket_repository, bitbucket_username, bitbucket_password),
        gh_repo=github_repository,
        gh_import=GithubImport(github_access_token, github_repository, debug=False),
        skip_attachments=skip_attachments,
        update=update,
        dry_run=dry_run,
    )

    bitbucket_to_github(run_data=run_data)


if __name__ == "__main__":
    main()
