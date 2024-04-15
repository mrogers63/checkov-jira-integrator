#! /usr/bin/env python3
# Checkov to Jira tool
# needs JIRA user: ENV Variables JIRA_URL, SECURITY_JIRA_USER and SECURITY_JIRA_TOKEN
# How to run: checkov -d . --soft-fail --quiet -o json | python3 checkov-result-manager.py -b $BRANCH -p JIRA_PROJECT

import argparse
import hashlib
import json
import os
import sys
import traceback
from jira import JIRA
import pdb

class Jira:
    def __init__(self, jira_url, token, email, project_id):
        self.project_id = project_id
        self.connection = JIRA(jira_url, basic_auth=(email, token))
    def issue_exists(self, hash_out):
        """
        Searches jira for issue based on hash.
        :param self: self
        :param hash_out: hash to search by
        :return: boolean
        """
        search = self.connection.search_issues(f'project={self.project_id} AND description ~ {hash_out}')
        if search == []:
            return True
        for this_result in search:
            if hash_out in this_result.fields.description:
                return False
        return True
    def issue(self, id):
        """
        gets issue by id
        :param self: self
        :param id: id to collect data of
        :return: dictionary of issue data
        """
        output = self.connection.issue(id)
        return output
    def link(self, inward, outward, message):
        """
        links issues when duplicating to team project
        :param self: self
        :param inward: devsec ticket for tool tracking
        :param outward: project ticket to track work
        :param message: comment on the link
        :return: status
        """
        output = self.connection.create_issue_link(type="Relates",
                                                   inwardIssue=inward,
                                                   outwardIssue=outward,
                                                   comment={'body': message})
        return output
    def create_issue(self, ticket_obj):
        """
        creates ticket under devsec board
        :param self: self
        :param ticket_obj: ticket object to make ticket under devsec board
        :return: ticket id
        """
        output = self.connection.create_issue(fields=ticket_obj)
        return output
    def create_sub_issue(self, sub_obj):
        """
        creates ticket under team's board
        :param self: self
        :param sub_obj: ticket object to make ticket under team's board
        :return: ticket id
        """
        output = self.connection.create_issue(fields=sub_obj)
        return output

def get_project(result):
    """
        gets project that finding is part of
        :param result: finding obj from checkov
        :return: string of project
    """
    proj = result['file_abs_path'].replace(result['file_path'], "")
    proj = os.path.basename(proj)
    return proj

def ticket_safe_name(result, proj):
    """
        creates a jira search safe version of the name
        :param result: finding obj from checkov
        :param proj: the project the finding belongs to
        :return: string of the safename
    """
    safe_name = result['check_name'].translate( { ord(i): None for i in '?!%@*"'} )
    title = f"Project: {proj} ISSUE: {safe_name} File: {result['file_path']}"
    return title

def create_hash(result, proj):
    """
        creates a hash with a salt+project name+finding name+path
        :param result: finding obj from checkov
        :param proj: the project the finding belongs to
        :return: hash used for searching
    """
    key_string = f"devops1{proj}{result['check_name']}{result['file_path']}"
    hash_out = hashlib.md5(key_string.encode('utf-8')).hexdigest()
    return hash_out

def create_code_snippet(line_array):
    """
        makes the code snippet it checkov fit into code block in jira
        :param line_array: array with the lines from the finding
        :return: code string for jira ticket
    """
    offending_lines = '{code}'
    for line in line_array:
        ln = f"{str(line[0])}: {line[1]}"
        offending_lines +=ln
    offending_lines += '{code}'
    return offending_lines

def create_description(result, offending_lines, hash, proj):
    """
        creates the ticket body
        if a description/guidance is available, adds to ticket
        :param result: the checkov finding object
        :param offending_lines: the code snippet
        :param hash: the hash needed for searching
        :param proj: project finding is under
        :return: string thats used for ticket body
    """
    guidance = ''
    if result['guideline'] is not None:
        guidance = f"Guideline: {result['guideline']}\n"
    description = f"ISSUE: {result['check_name']}\nREPO: {proj}\nFILE: {result['file_path']} LINES: {str(result['file_line_range'])}\n{guidance}{offending_lines}\n\n{hash}"
    return description

def create_ticket_obj(safe_name, project_id, description):
    """
        creates object that is used by Jiira to create ticket
        :param safename: jira safe name for ticket
        :param project_id: project_id that the ticket is made under
        :param description: ticket body
        :return: string ticket_id
    """
    tick_obj= {
        'project': {'key': project_id},
        'summary': safe_name,
        'description': description,
        'issuetype': {'name': 'Task'},
    }
    return tick_obj

def local_print(local_obj, branch):
    """
        if running on lower branch, (ot develop, master, release) prints new issues to pipeline console
        :param local_obj: all new findings
        :param branch: the branch the test is running under
    """
    print(f"[*] NEW Issues in {branch}\n")
    for obj in local_obj:
        print(f"[!] {obj['summary']}\n")
        print(f"{obj['description'].replace('{code}','')}\n\n\n\n")

def get_key(jira, id):
    """
        gets key from ticket_id
        :param jira: connection object to query jira
        :param id: id of ticket to search for
        :return: issue key
    """
    issue_id = jira.issue(id)
    return issue_id.key

def main():
    """
        takes in cli arguements and piped stdout from checkov.
        from every checkov finding it queries jira to see if its new or not, if new it does the following:
        master, develop, release branches: creates a ticket, build will not break
        all other branches: breaks build and prints all newly introduced findings as bb pipeline output
    """
    local_obj = []
    ticket_branches = ["master", "develop", "release"]
    parser = argparse.ArgumentParser(
        prog='Checkov to Jira',
        description='Takes Json output of checkov and either sends slack messages or creates tickets')
    parser.add_argument('-b', '--branch', help="bitbucket branch variable: BITBUCKET_BRANCH")
    parser.add_argument('-c', '--commit', help="commit hash: BITBUCKET_COMMIT")
    parser.add_argument('-p', '--project', help="project to assign work to")
    parser.add_argument('--input-file', '-i',type=argparse.FileType('r'),default=sys.stdin,)
    args = parser.parse_args()

    if str(type(args.input_file)) == "<class '_io.TextIOWrapper'>":
        print("reading from stdin")
    f = json.loads(args.input_file.read())
    jira_url = os.environ['JIRA_URL']
    token = os.environ['SECURITY_JIRA_TOKEN']
    email = os.environ['SECURITY_JIRA_USER']
    project_id = "DEVSEC"
    results = f[0]['results']['failed_checks']
    jira = Jira(jira_url, token, email, project_id)

    for result in results:
        project = get_project(result)
        hash_out = create_hash(result, project)
        safe_name = ticket_safe_name(result, project)
        make_ticket = jira.issue_exists(hash_out)

        if make_ticket == True:
            offending_lines = create_code_snippet(result['code_block'])
            description = create_description(result, offending_lines, hash_out, project)
            ticket_obj = create_ticket_obj(safe_name, project_id, description)

            if args.branch.lower().startswith(tuple(ticket_branches)):
                jira_response = jira.create_issue(ticket_obj)
                print(f"Master Ticket Created: {jira_response}")
                sub_obj = create_ticket_obj(safe_name, "DEVOPS", description)
                sub_ticket = jira.create_issue(sub_obj)
                print(f"Sub Ticket Created: {sub_ticket}")
                link_from = get_key(jira, jira_response)
                link_to = get_key(jira, sub_ticket)
                issue_text = "Ticket used for Secuirty Metric, Project ticket used to track work"
                linked = jira.link(link_from, link_to, issue_text)
                print(linked)
            else:
                local_obj.append(ticket_obj)

    if local_obj != []:
        local_print(local_obj, args.branch)
        exit(1)
    print('Checkov completed, no new findings')
    exit(0)
if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(traceback.format_exc())
