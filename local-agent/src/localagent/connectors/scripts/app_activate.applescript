-- argv: app name. Opens the app (or brings it to the front).
on run argv
	tell application (item 1 of argv) to activate
	return "ok"
end run
