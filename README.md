# Checkov Results Manager

This tool can be integrated into your pipelines to give you finding tracking capabilities with Checkov CLI. There are some oddities in it to meet requirements of $org.

## Description

You need to setup a jira user with api access read write to the projects it needs to manage. For this to work you need two projects. a "master" project that tracks all findings and the project that the work for a given ticket will actually be tracked.

A unique value is appended to each finding to know when something has already been seen

If running from a Develop/release*/Master branch (you can change this), findings will result in detailed tickets that are saved to the master tracking project and a child will be made in the work tracking project. No builds will fail.

When running from a lower branch, findings will break the build to prevent the introduction of new misconfigurations. if you need to except something force merge it and the higher level branch will make a ticket and it wont cause an issue again.

## To run
needs JIRA user: ENV Variables JIRA_URL, SECURITY_JIRA_USER, SECURITY_JIRA_TOKEN and BRANCH in your pieline runner

jira_project_slug is the project name for work tracking

How to run: checkov -d . --soft-fail --quiet -o json | python3 checkov-result-manager.py -b $BRANCH -p jira_project_slug

Tickets look like this

![image](https://github.com/mrogers63/checkov-jira-integrator/assets/29712752/53b981af-c152-4ed5-bbf8-6a104010c1fe)

