-- save_as.applescript DIR NAME
-- File > Save Live Set As..., then the native Save panel the way hands' export_audio.applescript
-- drives it: Go-to-folder (Cmd+Shift+G), the name set through accessibility (no cliclick, so the
-- pointer never moves), then AXPress on Save. Never presses Replace: if a sheet appears it reports
-- SHEET_OPEN and leaves it for a screenshot. Returns PRESSED_SAVE, NO_SAVE_PANEL, NAME_NOT_SET:<v>,
-- SHEET_OPEN or SAVE_PANEL_STILL_OPEN. Run through scripts/live_step.py save-as.
on run argv
	set theDir to item 1 of argv
	set theName to item 2 of argv
	tell application "System Events" to tell process "Live"
		set frontmost to true
		click menu item "Save Live Set As..." of menu "File" of menu bar 1
	end tell
	set t to 0
	repeat while t < 20
		tell application "System Events" to tell process "Live"
			if exists window "Save" then exit repeat
		end tell
		delay 0.25
		set t to t + 0.25
	end repeat
	tell application "System Events" to tell process "Live"
		if not (exists window "Save") then return "NO_SAVE_PANEL"
	end tell
	delay 0.7
	tell application "System Events" to tell process "Live"
		keystroke "g" using {command down, shift down}
	end tell
	delay 0.8
	tell application "System Events" to tell process "Live"
		keystroke theDir
	end tell
	delay 0.4
	tell application "System Events" to tell process "Live"
		key code 36
	end tell
	delay 0.8
	tell application "System Events" to tell process "Live"
		set nf to (first text field of (splitter group 1 of window "Save") whose description is "text field")
		set focused of nf to true
		delay 0.2
		set value of nf to theName
	end tell
	delay 0.4
	tell application "System Events" to tell process "Live"
		set v to value of (first text field of (splitter group 1 of window "Save") whose description is "text field")
		if v is not theName then return "NAME_NOT_SET:" & v
		perform action "AXPress" of (first button of (splitter group 1 of window "Save") whose title is "Save")
	end tell
	delay 1.0
	tell application "System Events" to tell process "Live"
		if exists window "Save" then
			if exists sheet 1 of window "Save" then return "SHEET_OPEN"
			return "SAVE_PANEL_STILL_OPEN"
		end if
	end tell
	return "PRESSED_SAVE"
end run
