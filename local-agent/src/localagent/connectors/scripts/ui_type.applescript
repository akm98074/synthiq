-- argv: app name, text. Brings the app to the front and types the text where the cursor is.
on run argv
	tell application (item 1 of argv) to activate
	delay 0.3
	tell application "System Events" to keystroke (item 2 of argv)
	return "typed"
end run
