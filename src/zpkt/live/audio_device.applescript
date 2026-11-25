-- audio_device.applescript - choose Live's audio output device through its Settings window.
-- Live 12 exposes Settings to Accessibility: the page buttons have no names, so each is pressed
-- until the "Audio Output Device" pop-up shows; its menu opens as a window of its own.
--     osascript audio_device.applescript read            -> the device shown now
--     osascript audio_device.applescript set NAME [NAME...] -> chooses the first menu item that starts
--                                                             with one of the names; prints it, or NONE
-- Settings is closed again afterwards if this script opened it.

on findPopup(w)
	tell application "System Events"
		set els to entire contents of w
		repeat with i from 1 to count of els
			set e to item i of els
			try
				if (role of e as text) is "AXPopUpButton" and (description of e as text) is "Audio Output Device" then return e
			end try
		end repeat
	end tell
	return missing value
end findPopup

on run argv
	set mode to item 1 of argv
	set wanted to {}
	if (count of argv) > 1 then set wanted to items 2 thru -1 of argv
	tell application "System Events"
		if not (exists process "Live") then return "NO_LIVE"
		tell process "Live"
			set opened to false
			if not (exists window "Settings") then
				set frontmost to true
				keystroke "," using command down
				set opened to true
				repeat 20 times
					if exists window "Settings" then exit repeat
					delay 0.25
				end repeat
			end if
			if not (exists window "Settings") then return "NO_SETTINGS"
			set w to window "Settings"
			set pop to my findPopup(w)
			if pop is missing value then
				set pageList to {}
				set els to entire contents of w
				repeat with i from 1 to count of els
					set e to item i of els
					try
						if (role of e as text) is "AXRadioButton" then set end of pageList to e
					end try
				end repeat
				repeat with p in pageList
					perform action "AXPress" of p
					delay 0.4
					set pop to my findPopup(w)
					if pop is not missing value then exit repeat
				end repeat
			end if
			if pop is missing value then return "NO_POPUP"
			set result_ to (value of pop as text)
			if mode is "set" then
				perform action "AXPress" of pop
				delay 0.8
				set result_ to "NONE"
				set items_ to entire contents of window 1
				repeat with nm in wanted
					repeat with i from 1 to count of items_
						set e to item i of items_
						try
							if (role of e as text) is "AXMenuItem" and (name of e as text) starts with (nm as text) then
								set result_ to (name of e as text)
								perform action "AXPress" of e
								exit repeat
							end if
						end try
					end repeat
					if result_ is not "NONE" then exit repeat
				end repeat
				if result_ is "NONE" then key code 53
				delay 0.5
			end if
			if opened or mode is "set" then
				try
					perform action "AXPress" of (first button of window "Settings" whose description is "close button")
				end try
			end if
			return result_
		end tell
	end tell
end run
