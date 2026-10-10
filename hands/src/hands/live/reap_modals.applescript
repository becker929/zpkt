-- reap_modals.applescript - the accessibility half of dismiss_modals.sh.
-- Enumerates every window + sheet of the Live process and, per mode, reports or
-- safely dismisses modal dialogs. Called as:
--     osascript reap_modals.applescript [check|reap]
-- Output: pipe-separated lines, or CLEAN / NO_LIVE. See dismiss_modals.sh.
--
-- Buttons are gathered across nested containers (native Save/Open panels nest
-- their Save/Cancel under a splitter group; the Export dialog under group 1),
-- so an overwrite sheet AND the parent panel are both handled.

on run argv
	set mode to "check"
	if (count of argv) >= 1 then set mode to item 1 of argv
	-- Safe buttons, in priority order. We press the FIRST that exists.
	set safeButtons to {"Cancel", "Don't Save", "No", "Close", "OK"}
	-- Destructive buttons we NEVER auto-press (reporting only).
	set destructiveButtons to {"Save", "Replace", "Overwrite", "Yes", "Delete", "Don't Restore", "Remove"}
	-- Known blocking dialog windows that are always Escape-cancellable if we
	-- can't find a titled safe button (native panels).
	set escapableWindows to {"Save", "Open", "Export Audio/Video"}
	set out to ""
	with timeout of 8 seconds
		tell application "System Events"
			if not (exists process "Live") then return "NO_LIVE"
			tell process "Live"
				set wins to every window
				repeat with w in wins
					set wname to "?"
					try
						set wname to name of w as text
					end try
					set target to missing value
					set label to ""
					set isKnownWindow to false
					-- A window's sheet (role AXSheet) is always a blocking modal.
					try
						if (exists sheet 1 of w) then
							set target to sheet 1 of w
							set label to "sheet-of[" & wname & "]"
						end if
					end try
					-- Standalone dialog windows we recognize as blocking.
					if target is missing value then
						if wname is in escapableWindows then
							set target to w
							set label to "window[" & wname & "]"
							set isKnownWindow to true
						end if
					end if
					if target is not missing value then
						set btns to my buttonTitlesOf(target)
						set btnStr to my joinList(btns)
						set safeHit to my firstMatch(btns, safeButtons)
						set destrHit to my firstMatch(btns, destructiveButtons)
						if mode is "reap" then
							if safeHit is not "" then
								my pressButton(target, safeHit)
								set out to out & "REAPED | " & label & " | " & safeHit & " | {" & btnStr & "}" & linefeed
							else if isKnownWindow then
								-- native panel we know: Escape safely cancels it
								with timeout of 4 seconds
									key code 53
								end timeout
								set out to out & "REAPED | " & label & " | ESC | {" & btnStr & "}" & linefeed
							else if (count of btns) is 0 then
								with timeout of 4 seconds
									key code 53
								end timeout
								set out to out & "REAPED | " & label & " | ESC | {}" & linefeed
							else
								set out to out & "ABORT | " & label & " | " & destrHit & " | {" & btnStr & "}" & linefeed
							end if
						else
							set out to out & "MODAL | " & label & " | safe=" & safeHit & " | {" & btnStr & "}" & linefeed
						end if
					end if
				end repeat
			end tell
		end tell
	end timeout
	if out is "" then return "CLEAN"
	return out
end run

-- Collect button titles from an element AND one level of nested containers
-- (splitter groups, groups), which is where native panels hide Save/Cancel.
on buttonTitlesOf(target)
	set titles to {}
	tell application "System Events"
		try
			set titles to titles & (title of every button of target)
		end try
		try
			repeat with g in (splitter groups of target)
				try
					set titles to titles & (title of every button of g)
				end try
			end repeat
		end try
		try
			repeat with g in (groups of target)
				try
					set titles to titles & (title of every button of g)
				end try
			end repeat
		end try
	end tell
	-- drop missing values
	set clean to {}
	repeat with t in titles
		try
			if (t as text) is not "" and (t as text) is not "missing value" then set end of clean to (t as text)
		end try
	end repeat
	return clean
end buttonTitlesOf

-- Press a button by title, searching target then nested containers.
on pressButton(target, theTitle)
	tell application "System Events"
		with timeout of 4 seconds
			try
				perform action "AXPress" of (first button of target whose title is theTitle)
				return true
			end try
			try
				repeat with g in (splitter groups of target)
					try
						perform action "AXPress" of (first button of g whose title is theTitle)
						return true
					end try
				end repeat
			end try
			try
				repeat with g in (groups of target)
					try
						perform action "AXPress" of (first button of g whose title is theTitle)
						return true
					end try
				end repeat
			end try
			-- last resort
			key code 53
		end timeout
	end tell
	return false
end pressButton

on firstMatch(have, want)
	repeat with wch in want
		repeat with hv in have
			if (hv as text) is (wch as text) then return (wch as text)
		end repeat
	end repeat
	return ""
end firstMatch

on joinList(lst)
	set AppleScript's text item delimiters to ", "
	set s to lst as text
	set AppleScript's text item delimiters to ""
	return s
end joinList
