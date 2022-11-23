import re
import sys

import pipenv.vendor.click as click

try:
    import github as pygithub
except ImportError:
    pygithub = None

from . import utils, requirements

def create_branch(repo, base_branch, new_branch):
    ref = repo.get_git_ref("heads/" + base_branch)
    repo.create_git_ref(ref="refs/heads/" + new_branch, sha=ref.object.sha)

def delete_branch(repo, branch):
    ref = repo.get_git_ref(f"heads/{branch}")
    ref.delete()

@click.command()
@click.option('--repo', help='GitHub standard repo path (eg, my-org/my-project)')
@click.option('--token', help='GitHub Access Token')
@click.option('--base-url', help='Optional custom Base URL, if you\'re using GitHub enterprise', default=None)
@click.pass_obj
@utils.require_files_report
def github_pr(obj, repo, token, base_url):
    """
    Create a GitHub PR to fix any vulnerabilities using PyUp's remediation data.

    Normally, this is run by a GitHub action. If you're running this manually, ensure that your local repo is up to date and on HEAD - otherwise you'll see strange results.
    """
    if pygithub is None:
        click.secho("pygithub is not installed. Did you install Safety with GitHub support? Try pip install safety[github]", fg='red')
        sys.exit(1)

    # TODO: Improve access to our config in future.
    branch_prefix = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('branch-prefix', 'pyup/')
    pr_prefix = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('pr-prefix', '[PyUp] ')
    assignees = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('assignees', [])
    labels = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('labels', ['security'])
    label_severity = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('label-severity', True)
    ignore_cvss_severity_below = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('ignore-cvss-severity-below', 0)
    ignore_cvss_unknown_severity = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('ignore-cvss-unknown-severity', False)

    gh = pygithub.Github(token, **({"base_url": base_url} if base_url else {}))
    repo = gh.get_repo(repo)
    try:
        self_user = gh.get_user().login
    except pygithub.GithubException:
        # If we're using a token from an action (or integration) we can't call `get_user()`. Fall back
        # to assuming we're running under an action
        self_user = "web-flow"

    pulls = repo.get_pulls(state='open', sort='created', base=repo.default_branch)
    pending_updates = set(obj.report['remediations'].keys())

    # TODO: Refactor this loop into a fn to iterate over remediations nicely
    for name, contents in obj.requirements_files.items():
        raw_contents = contents
        contents = contents.decode('utf-8') # TODO - encoding?
        parsed_req_file = requirements.RequirementFile(name, contents)
        for pkg, remediation in obj.report['remediations'].items():
            if remediation['recommended_version'] is None:
                print(f"The GitHub PR alerter only currently supports remediations that have a recommended_version: {pkg}")
                continue

            # We have a single remediation that can have multiple vulnerabilities
            vulns = [x for x in obj.report['vulnerabilities'] if x['package_name'] == pkg and x['analyzed_version'] == remediation['current_version']]

            if ignore_cvss_unknown_severity and all(x['severity'] is None for x in vulns):
                print("All vulnerabilities have unknown severity, and ignore_cvss_unknown_severity is set.")
                continue

            highest_base_score = 0
            for vuln in vulns:
                if vuln['severity'] is not None:
                    highest_base_score = max(highest_base_score, (vuln['severity'].get('cvssv3', {}) or {}).get('base_score', 10))

            if ignore_cvss_severity_below:
                at_least_one_match = False
                for vuln in vulns:
                    # Consider a None severity as a match, since it's controlled by a different flag
                    # If we can't find a base_score but we have severity data, assume it's critical for now.
                    if vuln['severity'] is None or (vuln['severity'].get('cvssv3', {}) or {}).get('base_score', 10) >= ignore_cvss_severity_below:
                        at_least_one_match = True

                if not at_least_one_match:
                    print(f"None of the vulnerabilities found have a score greater than or equal to the ignore_cvss_severity_below of {ignore_cvss_severity_below}")
                    continue

            for parsed_req in parsed_req_file.requirements:
                if parsed_req.name == pkg:
                    updated_contents = parsed_req.update_version(contents, remediation['recommended_version'])
                    pending_updates.discard(pkg)

                    new_branch = branch_prefix + utils.generate_branch_name(pkg, remediation)
                    skip_create = False

                    # Few possible cases:
                    # 1. No existing PRs exist for this change (don't need to handle)
                    # 2. An existing PR exists, and it's out of date (eg, recommended 0.5.1 and we want 0.5.2)
                    # 3. An existing PR exists, and it's not mergable anymore (eg, needs a rebase)
                    # 4. An existing PR exists, and everything's up to date.
                    # 5. An existing PR exists, but it's not needed anymore (perhaps we've been updated to a later version)
                    # 6. No existing PRs exist, but a branch does exist (perhaps the PR was closed but a stale branch left behind)
                    # In any case, we only act if we've been the only committer to the branch.
                    for pr in pulls:
                        if not pr.head.ref.startswith(branch_prefix):
                            continue

                        authors = [commit.committer.login for commit in pr.get_commits()]
                        only_us = all([x == self_user for x in authors])

                        try:
                            _, pr_pkg, pr_ver = pr.head.ref.split('/')
                        except ValueError:
                            # It's possible that something weird has manually been done, so skip that
                            print('Found an invalid branch name on an open PR, that matches our prefix. Skipping.')
                            continue

                        if pr_pkg != pkg:
                            continue

                        # Case 4
                        if pr_pkg == pkg and pr_ver == remediation['recommended_version'] and pr.mergeable:
                            print(f"An up to date PR #{pr.number} for {pkg} was found, no action will be taken.")

                            skip_create = True
                            continue

                        if not only_us:
                            print(f"There are other committers on the PR #{pr.number} for {pkg}. No further action will be taken.")
                            continue

                        # Case 2
                        if pr_pkg == pkg and pr_ver != remediation['recommended_version']:
                            print(f"Closing stale PR #{pr.number} for {pkg} as a newer recommended version became")

                            pr.create_issue_comment("This PR has been replaced, since a newer recommended version became available.")
                            pr.edit(state='closed')
                            delete_branch(repo, pr.head.ref)

                        # Case 3
                        if not pr.mergeable:
                            print(f"Closing PR #{pr.number} for {pkg} as it has become unmergable and we were the only committer")

                            pr.create_issue_comment("This PR has been replaced since it became unmergable.")
                            pr.edit(state='closed')
                            delete_branch(repo, pr.head.ref)

                    if updated_contents == contents:
                        print(f"Couldn't update {pkg} to {remediation['recommended_version']}")
                        continue

                    if skip_create:
                        continue

                    try:
                        create_branch(repo, repo.default_branch, new_branch)
                    except pygithub.GithubException as e:
                        if e.data['message'] == "Reference already exists":
                            # There might be a stale branch. If the bot is the only committer, nuke it.
                            comparison = repo.compare(repo.default_branch, new_branch)
                            authors = [commit.committer.login for commit in comparison.commits]
                            only_us = all([x == self_user for x in authors])

                            if only_us:
                                delete_branch(repo, new_branch)
                                create_branch(repo, repo.default_branch, new_branch)
                            else:
                                print(f"The branch '{new_branch}' already exists - but there is no matching PR and this branch has committers other than us. This remediation will be skipped.")
                                continue
                        else:
                            raise e

                    try:
                        repo.update_file(
                                path=name,
                                message=utils.generate_commit_message(pkg, remediation),
                                content=updated_contents,
                                branch=new_branch,
                                sha=utils.git_sha1(raw_contents)
                            )
                    except pygithub.GithubException as e:
                        if "does not match" in e.data['message']:
                            click.secho(f"GitHub blocked a commit on our branch to the requirements file, {name}, as the local hash we computed didn't match the version on {repo.default_branch}. Make sure you're running safety against the latest code on your default branch.", fg='red')
                            continue
                        else:
                            raise e

                    pr = repo.create_pull(title=pr_prefix + utils.generate_title(pkg, remediation, vulns), body=utils.generate_body(pkg, remediation, vulns, api_key=obj.key), head=new_branch, base=repo.default_branch)
                    print(f"Created Pull Request to update {pkg}")

                    for assignee in assignees:
                        pr.add_to_assignees(assignee)

                    for label in labels:
                        pr.add_to_labels(label)

                    if label_severity:
                        score_as_label = utils.cvss3_score_to_label(highest_base_score)
                        if score_as_label:
                            pr.add_to_labels(score_as_label)

    if len(pending_updates) > 0:
        click.secho("The following remediations were not followed: {}".format(', '.join(pending_updates)), fg='red')

@click.command()
@click.option('--repo', help='GitHub standard repo path (eg, my-org/my-project)')
@click.option('--token', help='GitHub Access Token')
@click.option('--base-url', help='Optional custom Base URL, if you\'re using GitHub enterprise', default=None)
@click.pass_obj
@utils.require_files_report # TODO: For now, it can be removed in the future to support env scans.
def github_issue(obj, repo, token, base_url):
    """
    Create a GitHub Issue for any vulnerabilities found using PyUp's remediation data.

    Normally, this is run by a GitHub action. If you're running this manually, ensure that your local repo is up to date and on HEAD - otherwise you'll see strange results.
    """
    if pygithub is None:
        click.secho("pygithub is not installed. Did you install Safety with GitHub support? Try pip install safety[github]", fg='red')
        sys.exit(1)

    # TODO: Improve access to our config in future.
    issue_prefix = obj.policy.get('alert', {}).get('security', {}).get('github-issue', {}).get('issue-prefix', '[PyUp] ')
    assignees = obj.policy.get('alert', {}).get('security', {}).get('github-issue', {}).get('assignees', [])
    labels = obj.policy.get('alert', {}).get('security', {}).get('github-issue', {}).get('labels', ['security'])
    label_severity = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('label-severity', True)
    ignore_cvss_severity_below = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('ignore-cvss-severity-below', 0)
    ignore_cvss_unknown_severity = obj.policy.get('alert', {}).get('security', {}).get('github-pr', {}).get('ignore-cvss-unknown-severity', False)

    gh = pygithub.Github(token, **({"base_url": base_url} if base_url else {}))
    repo = gh.get_repo(repo)

    issues = list(repo.get_issues(state='open', sort='created'))
    ISSUE_TITLE_REGEX = re.escape(issue_prefix) + r"Security Vulnerability in (.+)"

    for name, contents in obj.requirements_files.items():
        raw_contents = contents
        contents = contents.decode('utf-8') # TODO - encoding?
        parsed_req_file = requirements.RequirementFile(name, contents)
        for pkg, remediation in obj.report['remediations'].items():
            if remediation['recommended_version'] is None:
                print(f"The GitHub Issue alerter only currently supports remediations that have a recommended_version: {pkg}")
                continue

            # We have a single remediation that can have multiple vulnerabilities
            vulns = [x for x in obj.report['vulnerabilities'] if x['package_name'] == pkg and x['analyzed_version'] == remediation['current_version']]

            if ignore_cvss_unknown_severity and all(x['severity'] is None for x in vulns):
                print("All vulnerabilities have unknown severity, and ignore_cvss_unknown_severity is set.")
                continue

            highest_base_score = 0
            for vuln in vulns:
                if vuln['severity'] is not None:
                    highest_base_score = max(highest_base_score, (vuln['severity'].get('cvssv3', {}) or {}).get('base_score', 10))

            if ignore_cvss_severity_below:
                at_least_one_match = False
                for vuln in vulns:
                    # Consider a None severity as a match, since it's controlled by a different flag
                    # If we can't find a base_score but we have severity data, assume it's critical for now.
                    if vuln['severity'] is None or (vuln['severity'].get('cvssv3', {}) or {}).get('base_score', 10) >= ignore_cvss_severity_below:
                        at_least_one_match = True

                if not at_least_one_match:
                    print(f"None of the vulnerabilities found have a score greater than or equal to the ignore_cvss_severity_below of {ignore_cvss_severity_below}")
                    continue

            for parsed_req in parsed_req_file.requirements:
                if parsed_req.name == pkg:
                    skip = False
                    for issue in issues:
                        match = re.match(ISSUE_TITLE_REGEX, issue.title)
                        if match:
                            if match.group(1) == pkg:
                                skip = True

                    # For now, we just skip issues if they already exist - we don't try and update them.
                    if skip:
                        print(f"An issue already exists for {pkg} - skipping")
                        continue

                    pr = repo.create_issue(title=issue_prefix + utils.generate_issue_title(pkg, remediation), body=utils.generate_issue_body(pkg, remediation, vulns, api_key=obj.key))
                    print(f"Created issue to update {pkg}")

                    for assignee in assignees:
                        pr.add_to_assignees(assignee)

                    for label in labels:
                        pr.add_to_labels(label)

                    if label_severity:
                        score_as_label = utils.cvss3_score_to_label(highest_base_score)
                        if score_as_label:
                            pr.add_to_labels(score_as_label)
