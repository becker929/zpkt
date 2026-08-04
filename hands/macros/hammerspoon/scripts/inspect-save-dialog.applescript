-- inspect-save-dialog.applescript
-- Run this while Live's Save sheet is open (after manually clicking Export
-- in the Export Audio/Video dialog). Dumps all window and sheet contents
-- so element names and indices can be confirmed.
--
-- Usage:
--   osascript src/inspect-save-dialog.applescript

tell application "System Events"
  tell process "Live"
    set winCount to count of windows
    log "Windows: " & winCount
    repeat with i from 1 to winCount
      log "=== window " & i & " ==="
      log get entire contents of window i
    end repeat
  end tell
end tell
