-- inspect-export-dialog.applescript
-- Opens Live's Export Audio/Video dialog and dumps every UI element in group 1
-- with its 1-based index, role, value, and enabled state. Also lists menu items
-- for popups and button titles for radio groups. Closes the dialog when done.
--
-- Usage:
--   osascript ~/.hammerspoon/scripts/inspect-export-dialog.applescript

tell application "Ableton Live 12 Suite" to activate
delay 0.5

tell application "System Events"
  tell process "Live"
    keystroke "r" using {command down, shift down}
    delay 1.5

    if not (exists window "Export Audio/Video") then
      error "Export Audio/Video dialog did not open"
    end if

    set g to group 1 of window "Export Audio/Video"
    set elems to UI elements of g
    log "=== Export Audio/Video — group 1 has " & (count of elems) & " elements ==="

    repeat with i from 1 to count of elems
      set e to item i of elems
      set roleStr to role of e as text
      set valueStr to ""
      set enabledStr to ""
      try
        set valueStr to value of e as text
      end try
      try
        set enabledStr to enabled of e as text
      end try
      log "[" & i & "] " & roleStr & " | value=" & valueStr & " | enabled=" & enabledStr

      if roleStr is "AXPopUpButton" then
        try
          set menuItems to every menu item of menu 1 of e
          set names to {}
          repeat with mi in menuItems
            try
              set end of names to (title of mi as text)
            end try
          end repeat
          log "     popup items: " & names
        end try
      end if

      if roleStr is "AXRadioGroup" then
        try
          set rbs to every radio button of e
          set names to {}
          repeat with rb in rbs
            try
              set end of names to (title of rb as text)
            end try
          end repeat
          log "     radio buttons: " & names
        end try
      end if
    end repeat

    -- Cancel without exporting
    key code 53
  end tell
end tell
