# Team workspaces

## Inviting members

Team admins can invite people under Admin console, then Members, then Invite. Invitations expire after 7 days. Each accepted invitation uses one seat; if all seats are used, the admin is asked to add seats before the invite can be sent. Guests from outside your organisation can be given access to individual shared notebooks without using a seat, up to 10 guests per workspace.

## Roles and permissions

There are three workspace roles. Owners manage billing and can delete the workspace. Admins manage members, single sign-on and security settings. Members create and edit notes in notebooks shared with them. Within a shared notebook, access can be set to "Can view", "Can comment" or "Can edit".

## Single sign-on

Team plans support SAML 2.0 single sign-on with Okta, Microsoft Entra ID, Google Workspace and any standards-compliant identity provider. SSO is configured by an admin in Admin console, then Security. Once "Require SSO" is on, members can no longer sign in with a password. SCIM provisioning is available for Okta and Entra ID.

## Removing a member

When an admin removes a member, their private notes are transferred to an admin of the admin's choosing, and their seat becomes free immediately. Notes in shared notebooks stay where they are. The removed person can keep using Fieldnote with a personal Free account, but loses access to everything in the workspace.

## Transferring ownership

Only the current owner can transfer ownership, under Admin console, then Settings, then Transfer ownership. The new owner must already be an admin in the workspace.
