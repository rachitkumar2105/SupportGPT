# Sync troubleshooting

## How sync works

Every edit is saved locally first and then sent to Fieldnote's servers. Other devices pick up changes within a few seconds while they are online. When the same note is edited on two offline devices, Fieldnote keeps both versions: the later edit becomes the note, and the earlier one is saved as a "Conflicted copy" in the same notebook so nothing is lost.

## Notes are not syncing

1. Check the sync indicator at the bottom of the sidebar. A grey cloud means the device is offline; an orange cloud means changes are waiting to upload.
2. Make sure you are signed in to the same account on every device. A surprising number of sync issues are two different accounts.
3. On the Free plan, sync works on two devices. A third device can sign in but won't sync until you remove a device under Settings, then Devices, or upgrade.
4. Quit and reopen the app. On mobile, make sure background app refresh is allowed for Fieldnote.
5. If a single note refuses to sync, copy its contents into a new note. Notes larger than 20 MB of text (not counting attachments) cannot sync.

## Error codes

E-401 means your session expired; sign out and sign in again. E-402 means your plan's device or storage limit was reached. E-409 means a sync conflict that will resolve itself as a conflicted copy. E-503 means our servers are temporarily unavailable; your edits are safe locally and will upload automatically when service returns. You can check service status at status.fieldnote.example.

## Attachments not uploading

Individual attachments are limited to 25 MB on Free and 200 MB on Plus and Team. Uploads pause on mobile networks if "Upload attachments on Wi-Fi only" is turned on in Settings, then Sync.

## Offline use

Desktop apps keep every note available offline. On mobile, only notebooks marked "Available offline" are stored on the device, and offline notebooks require the Plus or Team plan.
