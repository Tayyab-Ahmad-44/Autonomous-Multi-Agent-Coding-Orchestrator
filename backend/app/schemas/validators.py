VALID_REPO_URL_PREFIXES = ("https://", "http://", "git@", "ssh://", "git://")


def validate_repo_url(v: str) -> str:
    if not v.startswith(VALID_REPO_URL_PREFIXES):
        raise ValueError("repo_url must start with https://, http://, git@, ssh://, or git://")
    return v
