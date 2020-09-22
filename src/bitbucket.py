from typing import Any, Dict, Iterator, List, Optional

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from .utils import get_request_content, get_request_json


def get_paginated_json(url: str, session: requests.Session = None) -> Iterator[Dict[str, Any]]:
    next_url = url

    while next_url is not None:
        result = get_request_json(next_url, session)
        next_url = result.get("next", None)
        for value in result["values"]:
            yield value


class BitbucketExport:
    def __init__(
        self, repository_name: str = None, team_name: str = None, username: str = None, app_password: str = None
    ):
        if repository_name and "/" in repository_name:
            self.team_name, self.short_repo_name = repository_name.split("/", maxsplit=1)
        elif not repository_name and not team_name:
            raise ValueError("BitbucketExport: Please provide at least one of repository_name or team_name")
        else:
            self.short_repo_name = repository_name
            self.team_name = team_name
        # Share TCP connection and add a delay between failing requests
        session = Session()
        if username is not None and app_password is not None:
            session.auth = (username, app_password)
        retry = Retry(total=10, connect=10, read=10, backoff_factor=0.3, status_forcelist=(500, 502, 503, 504))
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self.session = session

    @property
    def repo_url(self) -> Optional[str]:
        if not (self.team_name and self.short_repo_name):
            return None
        return f"https://api.bitbucket.org/2.0/repositories/{self.team_name}/{self.short_repo_name}"

    @property
    def team_url(self) -> str:
        return f"https://api.bitbucket.org/2.0/teams/{self.team_name}"

    def get_repo_full_name(self) -> str:
        return f"{self.team_name}/{self.short_repo_name}"

    def get_repo_description(self) -> str:
        repository = get_request_content(self.repo_url, self.session)
        return repository["description"]

    def get_issues(self) -> List[Dict[str, Any]]:
        print("Get all bitbucket issues...")
        try:
            issues = list(get_paginated_json(self.repo_url + "/issues", self.session))
            issues.sort(key=lambda x: x["id"])
        except requests.exceptions.HTTPError as r:
            if r.response.status_code == 404:
                print("Issues not activated for this repo, skipping")
                return []
            raise r
        return issues

    def get_issue_comments(self, issue_id: int) -> Dict[int, List[Dict[str, Any]]]:
        if issue_id == 0:
            return {}
        comments = list(get_paginated_json(self.repo_url + "/issues/" + str(issue_id) + "/comments", self.session))
        return {comment["id"]: comment for comment in comments}

    def get_issue_changes(self, issue_id: int) -> List[Dict[str, Any]]:
        if issue_id == 0:
            return []
        changes = list(get_paginated_json(self.repo_url + "/issues/" + str(issue_id) + "/changes", self.session))
        changes.sort(key=lambda x: x["id"])
        return changes

    def get_issue_attachments(self, issue_id: int) -> Dict[str, Any]:
        if issue_id == 0:
            return {}
        attachments_query = get_paginated_json(
            self.repo_url + "/issues/" + str(issue_id) + "/attachments", self.session
        )
        attachments = {attachment["name"]: attachment for attachment in attachments_query}
        return attachments

    def get_issue_attachment_content(self, issue_id: int, attachment_name: str) -> Dict[str, Any]:
        data = get_request_content(
            self.repo_url + "/issues/" + str(issue_id) + "/attachments/" + attachment_name, self.session
        )
        return data

    def get_simplified_pulls(self) -> List[Dict[str, Any]]:
        print("Get all simplified bitbucket pull requests...")
        pulls = list(
            get_paginated_json(
                self.repo_url + "/pullrequests?state=MERGED&state=SUPERSEDED&state=OPEN&state=DECLINED", self.session
            )
        )
        pulls.sort(key=lambda x: x["id"])
        return pulls

    def get_team_users(self) -> List[Dict[str, Any]]:
        return list(get_paginated_json(self.team_url + "/members", self.session))

    def get_pulls_count(self) -> int:
        pulls_page = get_request_json(
            self.repo_url + "/pullrequests?state=MERGED&state=SUPERSEDED&state=OPEN&state=DECLINED", self.session
        )
        return pulls_page["size"]

    def get_pull(self, pull_id: int) -> Dict[str, Any]:
        pull = get_request_json(self.repo_url + "/pullrequests/" + str(pull_id), self.session)
        return pull

    def get_pulls(self, pulls_to_get: Optional[List[int]]) -> Iterator[Dict[str, Any]]:
        if not pulls_to_get:
            pulls_count = self.get_pulls_count()
            print(f"Get all {pulls_count} detailed Bitbucket pull requests...")
            for pull_id in range(1, pulls_count + 1):
                print(f"{pull_id}/{pulls_count}...")
                yield self.get_pull(pull_id)
        else:
            print(f"Getting specific Bitbucket pull requests")
            for pull_id in pulls_to_get:
                yield self.get_pull(pull_id)

    def get_pull_comments(self, pulls_id: int) -> Dict[int, List[Dict[str, Any]]]:
        comments = list(
            get_paginated_json(self.repo_url + "/pullrequests/" + str(pulls_id) + "/comments", self.session)
        )
        return {comment["id"]: comment for comment in comments}

    def get_pull_activity(self, pulls_id: int) -> List[Dict[str, Any]]:
        activity = list(
            get_paginated_json(self.repo_url + "/pullrequests/" + str(pulls_id) + "/activity", self.session)
        )
        return activity

    def get_detailed_comment(self, shallow_comment: Dict[str, Any]) -> Dict[str, Any]:
        return get_request_json(shallow_comment["links"]["self"]["href"], self.session)
