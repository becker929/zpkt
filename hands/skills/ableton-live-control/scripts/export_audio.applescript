-- export_audio.applescript
-- Drives Ableton Live 12's "Export Audio/Video" dialog + native Save panel via
-- AppleScript accessibility. All Export-dialog controls (track chooser, file
-- type, bit depth, sample rate, MP3 toggle) are driven by DIRECT accessibility
-- addressing (positional `pop up button N` / `button N` inside `group 1`, and
-- named `menu item` clicks in the transient popup window) -- no `cliclick`
-- pixel-guessing needed there. `cliclick` is still used for the native Save
-- panel's filename field, which has no name/description to target directly.
--
-- Usage:
--   osascript export_audio.applescript <absOutPath> [fileType] [bitDepth] [sampleRate] [lengthBars] [trackMode] [startBar]
--
--   item 1  absOutPath   REQUIRED absolute path, e.g. /tmp/render.wav
--                        For a multi-file trackMode (see below), this is used
--                        as the PREFIX: Live writes "<name> <TrackName>.wav"
--                        per rendered track next to it.
--   item 2  fileType      WAV | AIFF | FLAC          (default WAV)
--   item 3  bitDepth      16 | 24 | 32               (default 16)
--   item 4  sampleRate    22050|32000|44100|48000|88200|96000|176400|192000 (default 44100)
--   item 5  lengthBars    render length in bars; 0 = leave dialog default (default 2)
--   item 6  trackMode     "Main" (default) | "All Individual Tracks" |
--                         "Selected Tracks Only" | an exact track name
--                         (must match the "Rendered Track" dropdown's text,
--                         e.g. "Kick (G)") -- isolates that one track.
--   item 7  startBar      render start, in 0-based bars; -1 = leave dialog
--                         default (default 0, i.e. from the top of the
--                         arrangement). GOTCHA: the dialog's Render Start
--                         defaults to wherever the arrangement's insert
--                         marker/edit cursor currently sits, NOT bar 0 -- a
--                         near-silent bounce is often just a start position
--                         with no content there, not an isolation bug.
--
-- Returns the output path (or prefix, for a multi-file trackMode) on success;
-- errors on timeout / failure.
--
-- GROUND-TRUTH ELEMENT MAP (Live 12.4.5, verified 2026-09, re-verified 2026-09-09
-- with the "Rendered Track" chooser added):
--   Export dialog = window "Export Audio/Video"; all controls are children of
--     `group 1`, addressed POSITIONALLY (title/description are blank on most):
--       pop up button 1   Rendered Track   (Main | All Individual Tracks |
--                                           Selected Tracks Only | <track name> ...)
--       slider 1/2/3      Render Start (Bar/Beat/Sixteenths)   [has a `description`]
--       slider 4/5/6      Render Length (Bar/Beat/Sixteenths)  [has a `description`]
--       button 1..5       Include Return+Main Fx / Render as Loop / Convert to
--                         Mono / Normalize / Create Analysis File (checkboxes)
--       pop up button 2   Sample Rate
--       button 6          Encode PCM (checkbox, default On)
--       pop up button 3   File Type
--       pop up button 4   Bit Depth
--       pop up button 5   Dither Options
--       button 7          Encode MP3 (CBR 320) (checkbox, DEFAULT ON -- turn
--                         off or every bounce doubles up as an unwanted .mp3)
--       button 8          Create Video (checkbox)
--       pop up button 6   Video Encoder
--       button 9/10/11    Edit / Export / Cancel (these DO have `description`)
--     Opening any pop up button (`click`) spawns a NEW top-level window (name
--     "") whose `group 1 of group 1` holds real, NAMED `menu item` elements
--     (the currently-selected one is prefixed "✔ "). Click the item by name
--     directly -- no menu-window geometry hunting, no cliclick, for ANY popup
--     in this dialog, including "Rendered Track".
--
--   Save panel = window "Save" (a real window, NOT a sheet). Controls live under
--                `splitter group 1`:
--       TextField (description "text field")  = the "Save As:" filename field
--       Button title "Save"                   = commit  (responds to AXPress)
--       Button title "Cancel"                 = cancel
--       Button title "New Folder"
--     A "replace existing?" confirmation appears as `sheet 1 of window "Save"`
--     with a button titled "Replace". Still driven via cliclick (its filename
--     field has no name/description to focus directly).
--     For a multi-file trackMode, this SAME filename-based Save panel is used;
--     the typed name becomes a shared prefix for every rendered track.
--
--   GOTCHA (verified 2026-09-09): picking ANY single named track (not just
--     "All Individual Tracks" / "Selected Tracks Only") ALSO makes Live
--     append " <TrackName>" before the extension -- e.g. requesting
--     "/tmp/foo.wav" with trackMode "Kick (G)" actually writes
--     "/tmp/foo Kick (G).wav", NOT "/tmp/foo.wav". Only trackMode "Main"
--     writes the exact requested path. The script computes and polls for
--     this actual suffixed path in the named-track case, and returns it.

-- Resolved at runtime (Apple Silicon vs Intel Homebrew vs PATH). See resolveCliclick.
property cliclickPath : "cliclick"

-- Deterministic cursor-return: this script drives the physical pointer, so it
-- ALWAYS parks the cursor at the center of the primary physical display when it
-- finishes -- on success and on error alike. The real work lives in doExport;
-- this wrapper guarantees parkCursor runs on every exit path.
on run argv
	try
		set res to my doExport(argv)
		my parkCursor()
		return res
	on error errMsg number errNum
		my parkCursor()
		error errMsg number errNum
	end try
end run

-- Return the pointer to the primary physical display's center. Best-effort:
-- never let a parking failure mask the export's own result.
on parkCursor()
	try
		do shell script "bash ~/.agents/skills/virtual-display/scripts/park-cursor.sh"
	end try
end parkCursor

on doExport(argv)
	if (count of argv) < 1 then error "Usage: export_audio.applescript <absOutPath> [WAV|AIFF|FLAC] [16|24|32] [sampleRate] [lengthBars] [trackMode] [startBar]"
	set cliclickPath to my resolveCliclick()
	set outPath to item 1 of argv
	set fileType to "WAV"
	set bitDepth to "16"
	set sampleRate to "44100"
	set lengthBars to 2
	set trackMode to "Main"
	set startBar to 0
	if (count of argv) ≥ 2 then set fileType to item 2 of argv
	if (count of argv) ≥ 3 then set bitDepth to item 3 of argv
	if (count of argv) ≥ 4 then set sampleRate to item 4 of argv
	if (count of argv) ≥ 5 then set lengthBars to ((item 5 of argv) as integer)
	if (count of argv) ≥ 6 then set trackMode to item 6 of argv
	if (count of argv) ≥ 7 then set startBar to ((item 7 of argv) as integer)
	set isMultiFile to (trackMode is "All Individual Tracks") or (trackMode is "Selected Tracks Only")

	-- derive directory + filename
	set tid to AppleScript's text item delimiters
	set AppleScript's text item delimiters to "/"
	set parts to text items of outPath
	set theName to last item of parts
	if (count of parts) > 1 then
		set theDir to ((items 1 thru -2 of parts) as text)
	else
		set theDir to ""
	end if
	set AppleScript's text item delimiters to tid
	if theDir is "" then set theDir to "/"
	do shell script "/bin/mkdir -p " & quoted form of theDir

	-- a single NAMED track (not "Main", not the two multi-file modes) still
	-- writes exactly one file, but Live appends " <TrackName>" before the
	-- extension -- compute the actual path we must poll for/return.
	set isNamedTrack to (not isMultiFile) and (trackMode is not "Main")
	if isNamedTrack then
		set tid to AppleScript's text item delimiters
		set AppleScript's text item delimiters to "."
		set nameParts to text items of theName
		if (count of nameParts) > 1 then
			set theExt to last item of nameParts
			set theStem to ((items 1 thru -2 of nameParts) as text)
		else
			set theExt to ""
			set theStem to theName
		end if
		set AppleScript's text item delimiters to tid
		if theExt is "" then
			set actualOutPath to theDir & "/" & theStem & " " & trackMode
		else
			set actualOutPath to theDir & "/" & theStem & " " & trackMode & "." & theExt
		end if
	else
		set actualOutPath to outPath
	end if

	-- validate popup targets up-front (file type / bit depth still checked;
	-- sample rate and trackMode are matched by exact menu-item text, so any
	-- typo simply fails loudly when the menu item isn't found)
	set ft to my ftIndex(fileType)
	if (item 1 of ft) < 0 then error "Unknown file type: " & fileType
	set bd to my bdIndex(bitDepth)
	if (item 1 of bd) < 0 then error "Unknown bit depth: " & bitDepth

	tell application "Live" to activate
	delay 0.5

	-- close any leftover export / save dialog so we start clean. Raise first:
	-- a stray dialog left behind by a prior run can be BEHIND the main Live
	-- window, in which case Escape (and any pixel click) misses it entirely.
	repeat 4 times
		tell application "System Events" to tell process "Live"
			if (exists window "Save") or (exists window "Export Audio/Video") then
				try
					if exists window "Export Audio/Video" then perform action "AXRaise" of window "Export Audio/Video"
					if exists window "Save" then perform action "AXRaise" of window "Save"
				end try
				key code 53 -- escape
			else
				exit repeat
			end if
		end tell
		delay 0.4
	end repeat

	-- open the Export dialog (Cmd+Shift+R)
	tell application "System Events" to tell process "Live"
		keystroke "r" using {command down, shift down}
	end tell
	if not my waitForWindow("Export Audio/Video", 12) then error "Export dialog did not open"
	delay 0.6
	my raiseExportWindow()

	-- which track(s) to render FIRST: selecting a track/mode can reset the
	-- dialog's Render Start/Length to that track's own clip bounds, so any
	-- length we set before this would get silently wiped out.
	my setPopupByIndex(1, trackMode)

	-- render start (bars) — leave dialog default if -1. Must also come before
	-- length: the dialog's Start defaults to wherever the arrangement's edit
	-- cursor sits (not bar 0), which silently produces a "valid" but
	-- content-free bounce if left alone.
	if startBar ≥ 0 then my setStart(startBar)

	-- render length (bars) — leave dialog default if 0
	if lengthBars > 0 then my setLength(lengthBars)

	-- format / bit depth / sample rate (positional popups 3 / 4 / 2)
	my setPopupByIndex(3, fileType)
	my setPopupByIndex(4, bitDepth)
	my setPopupByIndex(2, sampleRate)

	-- make sure exactly one PCM file per track comes out: PCM on, MP3 off
	my setCheckbox(6, true)
	my setCheckbox(7, false)

	-- click Export. Uses AXPress (not a pixel click) so it can't miss even if
	-- the dialog isn't the frontmost window in z-order.
	my raiseExportWindow()
	my pressButtonByDesc("Export")

	-- native Save panel
	if not my waitForWindow("Save", 20) then error "Save panel did not appear"
	delay 0.7

	-- navigate to target directory via Go-to-folder (Cmd+Shift+G)
	tell application "System Events" to tell process "Live"
		set frontmost to true
		keystroke "g" using {command down, shift down}
	end tell
	delay 0.8
	tell application "System Events" to tell process "Live"
		keystroke theDir
	end tell
	delay 0.4
	tell application "System Events" to tell process "Live"
		key code 36 -- return / Go
	end tell
	delay 0.8

	-- set the filename: click the field explicitly (avoids typing into the file
	-- list and triggering type-select), select all, type the name
	tell application "System Events" to tell process "Live"
		set sg to splitter group 1 of window "Save"
		set nf to (first text field of sg whose description is "text field")
		set pp to position of nf
		set ps to size of nf
		set cx to (item 1 of pp) + ((item 1 of ps) div 2)
		set cy to (item 2 of pp) + ((item 2 of ps) div 2)
	end tell
	my clickAt(cx, cy)
	delay 0.3
	tell application "System Events" to tell process "Live"
		keystroke "a" using {command down}
		delay 0.2
		keystroke theName
	end tell
	delay 0.4

	-- commit
	tell application "System Events" to tell process "Live"
		set sg to splitter group 1 of window "Save"
		perform action "AXPress" of (first button of sg whose title is "Save")
	end tell
	delay 1.0

	-- handle "replace existing?" confirmation if it appears
	tell application "System Events" to tell process "Live"
		try
			if exists window "Save" then
				if exists sheet 1 of window "Save" then
					try
						perform action "AXPress" of (first button of sheet 1 of window "Save" whose title is "Replace")
					on error
						key code 36
					end try
				end if
			end if
		end try
	end tell

	if isMultiFile then
		-- Multiple files land next to `outPath` (one per track, named
		-- "<prefix> <TrackName>.<ext>"). There is no single path to poll for,
		-- so just wait for the Save panel to close (export done) plus a
		-- settle, then hand back the prefix; the caller verifies the actual
		-- per-track files itself (it already knows the track name list).
		set elapsed to 0
		repeat while elapsed < 120
			tell application "System Events" to tell process "Live"
				if not (exists window "Save") and not (exists window "Export Audio/Video") then exit repeat
			end tell
			delay 1
			set elapsed to elapsed + 1
		end repeat
		delay 1.0 -- let the last file's write settle
		return outPath
	end if

	-- single-file modes: poll for the rendered file (up to 120s). A named
	-- track writes to `actualOutPath` (== outPath for "Main"), see above.
	set elapsed to 0
	repeat while elapsed < 120
		try
			do shell script "/bin/test -s " & quoted form of actualOutPath
			delay 0.5 -- let the write settle
			return actualOutPath
		end try
		delay 1
		set elapsed to elapsed + 1
	end repeat
	error "Timed out (120s) waiting for export file: " & actualOutPath
end doExport


-- ---- helpers -------------------------------------------------------------

on ftIndex(v)
	ignoring case
		if v is "WAV" then return {0, 3}
		if v is "AIFF" then return {1, 3}
		if v is "FLAC" then return {2, 3}
	end ignoring
	return {-1, 3}
end ftIndex

on bdIndex(v)
	if v is "16" then return {0, 3}
	if v is "24" then return {1, 3}
	if v is "32" then return {2, 3}
	return {-1, 3}
end bdIndex

-- Set an Export-dialog pop up button (1-based, POSITIONAL: 1=Rendered Track,
-- 2=Sample Rate, 3=File Type, 4=Bit Depth, 5=Dither Options, 6=Video Encoder)
-- to an exact target value, by clicking it open and clicking the real, named
-- `menu item` in the transient menu window it spawns. No coordinates.
on setPopupByIndex(popupIndex, targetVal)
	tell application "System Events" to tell process "Live"
		set g to group 1 of window "Export Audio/Video"
		set p to pop up button popupIndex of g
		if (value of p as text) is targetVal then return -- already set
		click p
	end tell
	delay 0.4
	tell application "System Events" to tell process "Live"
		-- the freshly-opened menu is its own top-level window (name "");
		-- items live at group 1 of group 1 of that window, real AX names.
		set mi to missing value
		repeat with w in windows
			try
				set mi to (first menu item of group 1 of group 1 of w whose name is targetVal)
				exit repeat
			end try
		end repeat
		if mi is missing value then error "menu item not found for popup " & popupIndex & ": " & targetVal
		click mi
	end tell
	delay 0.3
	tell application "System Events" to tell process "Live"
		set g to group 1 of window "Export Audio/Video"
		set p to pop up button popupIndex of g
		if (value of p as text) is not targetVal then error "Failed to set popup " & popupIndex & " to " & targetVal & " (got " & (value of p as text) & ")"
	end tell
end setPopupByIndex

-- Set an Export-dialog checkbox (1-based, positional within group 1) to On/Off.
on setCheckbox(btnIndex, wantOn)
	tell application "System Events" to tell process "Live"
		set b to button btnIndex of group 1 of window "Export Audio/Video"
		set curOn to ((value of b as text) is "On")
	end tell
	if curOn is not wantOn then
		tell application "System Events" to tell process "Live"
			click button btnIndex of group 1 of window "Export Audio/Video"
		end tell
		delay 0.2
	end if
end setCheckbox

-- Set the Render Start bar count (0-based) by focusing the field and typing.
on setStart(bars)
	my raiseExportWindow()
	tell application "System Events" to tell process "Live"
		set g to group 1 of window "Export Audio/Video"
		set s to (first slider of g whose description is "Start of Rendered Sample (Bar)")
		set pp to position of s
		set ps to size of s
		set cx to (item 1 of pp) + ((item 1 of ps) div 2)
		set cy to (item 2 of pp) + ((item 2 of ps) div 2)
	end tell
	my clickAt(cx, cy)
	delay 0.4
	tell application "System Events" to tell process "Live"
		keystroke (bars as text)
		key code 36 -- return commits the value
	end tell
	delay 0.4
end setStart

-- Set the Render Length bar count by focusing the numeric field and typing.
on setLength(bars)
	my raiseExportWindow()
	tell application "System Events" to tell process "Live"
		set g to group 1 of window "Export Audio/Video"
		set s to (first slider of g whose description is "Length of Rendered Sample (Bar)")
		set pp to position of s
		set ps to size of s
		set cx to (item 1 of pp) + ((item 1 of ps) div 2)
		set cy to (item 2 of pp) + ((item 2 of ps) div 2)
	end tell
	my clickAt(cx, cy)
	delay 0.4
	tell application "System Events" to tell process "Live"
		keystroke (bars as text)
		key code 36 -- return commits the value
	end tell
	delay 0.4
end setLength

-- Press a described button via AXPress (not a pixel click), so it can't miss
-- the target even if the dialog window isn't frontmost in z-order.
on pressButtonByDesc(theDesc)
	tell application "System Events" to tell process "Live"
		set g to group 1 of window "Export Audio/Video"
		set e to (first button of g whose description is theDesc)
		perform action "AXPress" of e
	end tell
end pressButtonByDesc

-- Bring the Export dialog to the front of the z-order (best-effort; no-op if
-- the window doesn't exist yet). A GUI-hidden/behind-the-main-window dialog
-- is the root cause we hit where Escape and pixel clicks silently missed it.
on raiseExportWindow()
	try
		tell application "System Events" to tell process "Live"
			perform action "AXRaise" of window "Export Audio/Video"
		end tell
	on error
	end try
end raiseExportWindow

on clickAt(x, y)
	do shell script quoted form of cliclickPath & " c:" & (x as integer) & "," & (y as integer)
end clickAt

on waitForWindow(winName, timeoutSecs)
	set t to 0
	repeat while t < timeoutSecs
		with timeout of 3 seconds
			tell application "System Events" to tell process "Live"
				if exists window winName then return true
			end tell
		end timeout
		delay 0.3
		set t to t + 0.3
	end repeat
	return false
end waitForWindow

-- Resolve an absolute cliclick path: PATH first, then the two Homebrew prefixes.
on resolveCliclick()
	try
		set p to do shell script "command -v cliclick 2>/dev/null || true"
		if p is not "" then return p
	end try
	repeat with cand in {"/opt/homebrew/bin/cliclick", "/usr/local/bin/cliclick"}
		try
			do shell script "/bin/test -x " & quoted form of (cand as text)
			return (cand as text)
		end try
	end repeat
	error "cliclick not found on PATH or Homebrew prefixes (brew install cliclick)"
end resolveCliclick
