-- export.applescript
-- Drives Live's Export Audio/Video dialog to produce a post-FX mixdown.
--
-- Usage:
--   osascript export.applescript <outputPath> [format] [bitDepth] [sampleRate]
--
-- Arguments:
--   outputPath  Absolute path for the output file, e.g. /tmp/render.wav
--   format      "WAV" or "AIFF"  (default: WAV)
--   bitDepth    "16", "24", or "32"  (default: 24)
--   sampleRate  "44100", "48000", "88200", "96000"  (default: 44100)
--
-- Live's popup menus use a custom renderer invisible to the Accessibility API.
-- Values are selected by clicking the popup and pressing arrow keys.
-- Known menu orders are documented below; retest after each Live update.
--
-- Live 12 GA — group 1 of window "Export Audio/Video" (confirmed 2026-08-02):
--   Popups (AXPopUpButton):
--     popup 1: Rendered Track (Main, individual stems, …)
--     popup 2: Sample Rate — 44100, 48000, 88200, 96000, 192000
--     popup 3: File Type   — WAV, AIFF, FLAC
--     popup 4: Bit Depth   — 16, 24, 32
--     popup 5: Dither Options
--     popup 6: Video Encoder
--   Buttons (AXButton) in order:
--     button 1:  Include Return and Main Effects (disabled when rendering Main track)
--     button 2:  Render as Loop
--     button 3:  Convert to Mono
--     button 4:  Normalize
--     button 5:  Create Analysis File
--     button 6:  Encode PCM
--     button 7:  Encode MP3 (CBR 320)
--     button 8:  Create Video (disabled when no video clip present)
--     button 9:  Encoder Settings (disabled when video is off)
--     button 10: Export
--     button 11: Cancel
--   Render range (Render Start, Render Length sliders) is pre-populated by Live
--   from the current loop-brace selection if any, or the full arrangement otherwise.
--   This script does not touch the range sliders — Live's default satisfies the
--   "time selection if any, else full arrangement" requirement automatically.

-- Returns how many arrow key presses (+ = down, - = up) to go from current to target.
on arrowDelta(currentVal, targetVal, orderedList)
  set fromIdx to 0
  set toIdx to 0
  repeat with i from 1 to count of orderedList
    if item i of orderedList is currentVal then set fromIdx to i
    if item i of orderedList is targetVal then set toIdx to i
  end repeat
  if fromIdx is 0 then error "Current value not in list: " & currentVal
  if toIdx is 0 then error "Target value not in list: " & targetVal
  return toIdx - fromIdx
end arrowDelta

on run argv
  if (count of argv) < 1 then
    error "outputPath required. Usage: osascript export.applescript <outputPath> [format] [bitDepth] [sampleRate]"
  end if

  set outputPath to item 1 of argv
  set fileFormat to "WAV"
  if (count of argv) >= 2 then set fileFormat to item 2 of argv
  set bitDepth to "24"
  if (count of argv) >= 3 then set bitDepth to item 3 of argv
  set sampleRate to "44100"
  if (count of argv) >= 4 then set sampleRate to item 4 of argv

  set dirPath to do shell script "dirname " & quoted form of outputPath
  set fileName to do shell script "basename " & quoted form of outputPath

  set formatList to {"WAV", "AIFF", "FLAC"}
  set bitDepthList to {"16", "24", "32"}
  set sampleRateList to {"44100", "48000", "88200", "96000", "192000"}

  tell application "Ableton Live 12 Suite" to activate
  delay 0.5

  tell application "System Events"
    tell process "Live"

      keystroke "r" using {command down, shift down}
      delay 1.0

      if not (exists window "Export Audio/Video") then
        error "Export Audio/Video dialog did not open"
      end if

      -- File Type: popup 3
      set currentFormat to value of pop up button 3 of group 1 of window "Export Audio/Video"
      set fmtDelta to my arrowDelta(currentFormat, fileFormat, formatList)
      if fmtDelta is not 0 then
        click pop up button 3 of group 1 of window "Export Audio/Video"
        delay 0.3
        if fmtDelta > 0 then
          repeat fmtDelta times
            key code 125
            delay 0.15
          end repeat
        else
          repeat (-fmtDelta) times
            key code 126
            delay 0.15
          end repeat
        end if
        keystroke return
        delay 0.2
      end if

      -- Bit Depth: popup 4
      set currentDepth to value of pop up button 4 of group 1 of window "Export Audio/Video"
      set depthDelta to my arrowDelta(currentDepth, bitDepth, bitDepthList)
      if depthDelta is not 0 then
        click pop up button 4 of group 1 of window "Export Audio/Video"
        delay 0.3
        if depthDelta > 0 then
          repeat depthDelta times
            key code 125
            delay 0.15
          end repeat
        else
          repeat (-depthDelta) times
            key code 126
            delay 0.15
          end repeat
        end if
        keystroke return
        delay 0.2
      end if

      -- Sample Rate: popup 2
      set currentRate to value of pop up button 2 of group 1 of window "Export Audio/Video"
      set rateDelta to my arrowDelta(currentRate, sampleRate, sampleRateList)
      if rateDelta is not 0 then
        click pop up button 2 of group 1 of window "Export Audio/Video"
        delay 0.3
        if rateDelta > 0 then
          repeat rateDelta times
            key code 125
            delay 0.15
          end repeat
        else
          repeat (-rateDelta) times
            key code 126
            delay 0.15
          end repeat
        end if
        keystroke return
        delay 0.2
      end if

      -- "Include Return and Main Effects" must be on for post-FX output (button 1)
      if (enabled of button 1 of group 1 of window "Export Audio/Video") and ¬
         (value of button 1 of group 1 of window "Export Audio/Video" is "Off") then
        click button 1 of group 1 of window "Export Audio/Video"
        delay 0.2
      end if

      -- Ensure PCM encoding is on (button 6); without it the Export button stays disabled
      if value of button 6 of group 1 of window "Export Audio/Video" is "Off" then
        click button 6 of group 1 of window "Export Audio/Video"
        delay 0.2
      end if

      -- Turn off "Encode MP3 (CBR 320)" (button 7) so only the primary file is written
      if value of button 7 of group 1 of window "Export Audio/Video" is "On" then
        click button 7 of group 1 of window "Export Audio/Video"
        delay 0.2
      end if

      -- Click Export (button 10, description="Export"; button 11 is Cancel)
      click button 10 of group 1 of window "Export Audio/Video"
      delay 1.0

      -- Wait for Save window.
      -- Live's "windows" property is unreliable (count returns 0 even when windows exist).
      -- Use UI elements and match by role + title instead.
      set saveWin to missing value
      set waited to 0
      repeat
        set allUI to UI elements
        repeat with e in allUI
          try
            if (role of e as text) is "AXWindow" and (title of e as text) is "Save" then
              set saveWin to e
              exit repeat
            end if
          end try
        end repeat
        if saveWin is not missing value then exit repeat
        delay 0.3
        set waited to waited + 0.3
        if waited > 5 then error "Save dialog did not appear after clicking Export"
      end repeat

      -- Set filename in the Save As field
      set focused of text field "Save As:" of splitter group 1 of saveWin to true
      delay 0.2
      keystroke "a" using {command down}
      delay 0.1
      keystroke fileName
      delay 0.2

      -- Navigate to output directory via Go to Folder (Cmd+Shift+G)
      keystroke "g" using {command down, shift down}
      delay 0.5

      -- Go to Folder appears as a sheet on the Save window
      set waited to 0
      repeat
        if exists sheet 1 of saveWin then exit repeat
        delay 0.2
        set waited to waited + 0.2
        if waited > 3 then error "Go to Folder sheet did not appear"
      end repeat

      set focused of text field 1 of sheet 1 of saveWin to true
      keystroke "a" using {command down}
      keystroke dirPath
      delay 0.2
      keystroke return
      delay 0.5

      click button "Save" of splitter group 1 of saveWin

    end tell
  end tell

  -- Poll until the file exists on disk (max 180 seconds)
  set waited to 0
  repeat
    delay 1
    set waited to waited + 1
    if waited > 180 then
      error "Export timed out after 180 seconds — file not found at " & outputPath
    end if
    try
      do shell script "test -f " & quoted form of outputPath
      exit repeat
    end try
  end repeat

  return outputPath
end run
