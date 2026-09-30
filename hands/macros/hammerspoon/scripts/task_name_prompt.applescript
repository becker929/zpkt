display dialog "Task name (included in the saved filename):" default answer "" buttons {"Skip", "Save"} default button "Save" with title "Auto-save before workspace"
set btn to button returned of result
if btn is "Skip" then return "SKIP"
return "SAVE:" & text returned of result
