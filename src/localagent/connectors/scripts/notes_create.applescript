-- argv: title, htmlBody
on run argv
	tell application "Notes"
		set theFolder to default folder of default account
		make new note at theFolder with properties {name:(item 1 of argv), body:(item 2 of argv)}
		return name of theFolder
	end tell
end run
